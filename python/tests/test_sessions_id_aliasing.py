"""会话身份键不得在磁盘上撞名：``"victim."`` 与 ``"victim"`` 是同一个文件。

``session.persistence.safe_session_filename`` 把 ':' 写成 '__'、把其余非法字符
写成 '_'、再剥掉首尾 '._'——于是带空白或点号的变体、以及 ``vi:ctim`` 这类写法
都会落到同一个磁盘文件名上。读错会话、改错标题、删错数据都只需要一次这样的
id，所以身份有歧义在边缘就 422，绝不静默清洗后继续执行。
"""

from __future__ import annotations

import urllib.parse as up
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app

#: 真实数据里出现过的形状（28,017 条实测值全部是 sanitizer 的不动点）。
_REAL_IDS = [
	"sess_mubdqg8h_b4z3tx",
	"build-cython-ext__PwuPNqz__agent",
	"raman-fitting__NMDquYH__agent",
	"xeyo-af7426a13585",
	"agent-task-7-r1",
	"main",
]

#: 每一个都会在磁盘上撞上别的 id，或者根本不成其为一个身份。
_ALIASES = [
	"victim ",
	" victim",
	"victim.",
	".victim",
	"victim..",
	"vi:ctim",
	"vic/tim",
	r"vic\tim",
	"victim\x00",
	"victim\n",
	"..",
	".",
	"",
	"   ",
	"x" * 200,
]


@pytest.fixture
def client() -> TestClient:
	return TestClient(app)


def test_collisions_are_real_before_any_route_is_judged() -> None:
	"""先证明危害存在：这些写法在磁盘上确实是同一个文件，不是想象中的问题。"""
	from session.persistence import safe_session_filename as sanitized

	assert sanitized("victim ") == sanitized("victim")
	assert sanitized("victim.") == sanitized("victim")
	assert sanitized(".victim") == sanitized("victim")
	assert sanitized("vi:ctim") == sanitized("vi__ctim")
	assert sanitized("..") == sanitized(".") == sanitized("session")


@pytest.mark.parametrize("ident", _REAL_IDS)
def test_real_shaped_ids_are_not_rejected(client: TestClient, ident: str) -> None:
	"""合法形状不该被新校验挡住：422 才算误伤，其余状态码都算放行。"""
	for route in ("messages", "compression"):
		res = client.get(f"/v1/sessions/{ident}/{route}")
		assert res.status_code != 422, f"{ident} 被误判为非法身份（{route} → {res.status_code}）"


#: 这几个形状到不了处理程序（%2F 不进路径段、'.'/'..' 被路由归一化、空段匹配
#: 不上 {session_id}），所以只能在校验函数这一层判，不走 HTTP。
_UNROUTABLE = ["vic/tim", "..", ".", ""]
_ROUTABLE = [a for a in _ALIASES if a not in _UNROUTABLE]


@pytest.mark.parametrize("alias", _ROUTABLE)
def test_ambiguous_ids_are_refused_over_http(client: TestClient, alias: str) -> None:
	"""歧义 id 在读、删两条路上都必须 422，且不得被"清洗后照用"。"""
	quoted = up.quote(alias, safe="")
	res = client.get(f"/v1/sessions/{quoted}/compression")
	assert res.status_code == 422, f"GET compression {alias!r} → {res.status_code}"
	res = client.delete(f"/v1/sessions/{quoted}")
	assert res.status_code == 422, f"DELETE {alias!r} → {res.status_code}"


@pytest.mark.parametrize("alias", _ALIASES)
def test_validator_refuses_every_ambiguous_shape(alias: str) -> None:
	"""校验函数层面对全部变体一致拒绝，包括路由根本送不进来的那几个。"""
	from server.routers.sessions import require_session_id

	with pytest.raises(Exception):
		require_session_id(alias)


def test_generated_agent_id_still_passes() -> None:
	"""侧链 id 由 ``agent-{task}-{tail}`` 生成，必须仍在放行集合里。"""
	from server.routers.sessions import require_agent_id
	from tools.agent_tool.agent_tool import _safe_agent_id

	generated = _safe_agent_id("task-7", tail="r1")
	assert require_agent_id(generated) == generated


def test_non_filename_keys_keep_their_own_charset() -> None:
	"""job/queue/item 键不是文件名，不该被不动点规则误伤。"""
	from server.routers.sessions import _require_stable_id

	assert _require_stable_id("job:abc", field="job_id") == "job:abc"
	with pytest.raises(Exception) as exc:
		_require_stable_id("job:abc", field="session_id", filename_bearing=True)
	assert "collide" in str(exc.value)


# --------------------------------------------------------------------------- #
# 清洗器的**包含性**（containment）——不动点规则管的是别名，这一条管的是越界
# --------------------------------------------------------------------------- #

_TRAVERSAL_INPUTS = [
	"../x",
	"..",
	"../../etc/passwd",
	"a/../../b",
	"a\\..\\b",
	"....",
	".",
	"",
	" ",
	"x" * 300,
	"..%2f..",
	"C:/Windows",
	"a/../b",
	"\x00evil",
	"..\n",
	"/absolute/path",
]


def test_sanitizer_output_is_always_a_single_contained_segment() -> None:
	"""任何输入清洗后都必须是一个不含分隔符、不逃逸根目录、且非空的文件名段。

	这条性质是"14 处 ``root / safe_session_filename(...)`` 只靠边缘校验"够用
	的真正理由：包含性是**结构性**的，不需要每处再加一个 containment assert。
	如果哪天有人放宽 ``_SAFE_CHAR`` 放进了分隔符，这条用例会立刻红。
	"""
	from session.persistence import safe_session_filename

	root = (Path.cwd() / "SESSION_ID_PROBE_ROOT").resolve()
	for raw in _TRAVERSAL_INPUTS:
		name = safe_session_filename(raw)
		assert name, f"清洗成空串会让 join 指向根目录本身：{raw!r}"
		assert "/" not in name and "\\" not in name, f"产出含路径分隔符：{raw!r} -> {name!r}"
		assert name not in (".", ".."), f"产出目录指针：{raw!r} -> {name!r}"
		assert not name.startswith(".") and not name.endswith("."), (
			f"首尾点会被 strip 掉，说明产出与输入已不同名：{raw!r} -> {name!r}"
		)
		joined = (root / name).resolve()
		assert joined.parent == root, f"join 后逃逸根目录：{raw!r} -> {name!r}"


def test_fixed_point_inputs_pass_through_unchanged() -> None:
	"""不动点的输入必须逐字穿过清洗器 —— 边缘校验与磁盘布局说的是同一件事。"""
	from session.persistence import safe_session_filename

	for raw in ("sess_1", "task-7", "a.b_c-d", "x" * 180, "agent__r1"):
		assert safe_session_filename(raw) == raw, raw

