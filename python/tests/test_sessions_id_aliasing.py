"""会话身份键不得在磁盘上撞名：``"victim."`` 与 ``"victim"`` 是同一个文件。

``session.persistence.safe_session_filename`` 把 ':' 写成 '__'、把其余非法字符
写成 '_'、再剥掉首尾 '._'——于是带空白或点号的变体、以及 ``vi:ctim`` 这类写法
都会落到同一个磁盘文件名上。读错会话、改错标题、删错数据都只需要一次这样的
id，所以身份有歧义在边缘就 422，绝不静默清洗后继续执行。
"""

from __future__ import annotations

import urllib.parse as up

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
