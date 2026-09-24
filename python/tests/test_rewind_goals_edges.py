"""rewind.py / goals.py 路由边缘回归（2026-09-25 别名 id 事故模板）。

全部缺陷均为 TestClient 实测复现后才修：
- 修复前：``GET /v1/sessions/victim./rewind`` 200 返回 victim 的回溯事件；
  ``POST /v1/sessions/victim./rewind``（confirmed=true）200 并**原子重写了
  victim 的 transcript**；锚点路由把 anchor 行追加进 victim 的
  checkpoints.jsonl；``" victim "`` 被 ``.strip()`` 静默清洗后直接命中 victim；
  构造良好的不存在 id 一律 200+空列表。
- 修复后：非「文件名清洗固定点」的 id 在边缘 422；不存在会话 404
  session_not_found；破坏性路由对歧义 id 明确拒绝。
- goals.py 的 binding 文件名带 sha1 摘要，``victim.`` 读不到 victim 的 goal
  （磁盘别名被摘要挡住，probe 实测），但不存在的会话经 ``_pool.cwd`` 回落把
  幻影 goal 写进了服务器共享工作区 —— 现在 mutation 与 GET 都先 404。

Windows GBK 控制台：测试内不打印中文。所有可写根目录先重定向到 tmp。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="rg_edges_"))
os.environ["XEYO_DATA_DIR"] = str(_TMP / "data")
os.environ["XEYO_SESSIONS_DIR"] = str(_TMP / "sessions")
os.environ["XEYO_DIAGNOSTICS_DIR"] = str(_TMP / "diag")
_SESS = Path(os.environ["XEYO_SESSIONS_DIR"])
_SESS.mkdir(parents=True, exist_ok=True)
_WS_V = _TMP / "ws_victim"
_WS_V.mkdir()
_SERVER_WS = _TMP / "server_ws"  # pool 回落工作区：任何测试都不允许它出现 .xeyo/goals
_SERVER_WS.mkdir()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import deps  # noqa: E402
from server.app import app  # noqa: E402


def _q(s: str) -> str:
	return quote(s, safe="")


@pytest.fixture(scope="module")
def client() -> TestClient:
	return TestClient(app)


@pytest.fixture(autouse=True)
def _pool_map(monkeypatch):
	"""pool 只认识 victim / worker（均钉在 _WS_V）；其余会话磁盘上也只有 transcript。"""

	def fake_cwd(sid: str):
		return str(_WS_V) if sid in {"victim", "worker"} else None

	monkeypatch.setattr(deps._pool, "session_cwd", fake_cwd)
	monkeypatch.setattr(deps._pool, "_ui_cwd", str(_SERVER_WS))


def _sessions_root() -> Path:
	# conftest 每个用例把 XEYO_SESSIONS_DIR 钉进该用例的 tmp_path——必须动态解析
	# 路由真正读的目录，而不是模块导入时的快照。
	from session.persistence import default_sessions_dir

	return default_sessions_dir()


def _write(name: str, text: str) -> Path:
	p = _sessions_root() / name
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(text, encoding="utf-8")
	return p


@pytest.fixture()
def victim():
	tr = _write(
		"victim.jsonl",
		json.dumps({"id": "u1", "role": "user", "text": "hello", "ts": 1.0}) + "\n"
		+ json.dumps({"id": "a1", "role": "assistant", "text": "hi", "ts": 2.0}) + "\n",
	)
	ev = _write(
		"victim/rewind_events.jsonl",
		json.dumps(
			{"rewind_id": "rw_1_aaaa", "session_id": "victim", "status": "restored",
			 "mode": "continue", "orphan_count": 0, "retained_row_count": 2, "undone": False}
		) + "\n",
	)
	cp = _write(
		"victim/checkpoints.jsonl",
		json.dumps(
			{"checkpoint_id": "cp3_test", "user_message_id": "u1", "ts": 1.0,
			 "entries": [["a.py", "h1"]]}
		) + "\n",
	)
	return {"transcript": tr, "events": ev, "checkpoints": cp}


# ---------------------------------------------------------------- rewind ----

def test_rewind_list_rejects_disk_colliding_ids(client, victim):
	# 修复前 200 + victim 的事件列表（``victim.``/``vi:ctim`` 清洗后与 victim 同名）。
	assert victim["events"].read_text(encoding="utf-8").count("rw_1_aaaa") == 1
	for alias in ("victim.", "vi:ctim"):
		r = client.get(f"/v1/sessions/{_q(alias)}/rewind")
		assert r.status_code == 422, (alias, r.text)
		assert "collide" in r.text or "outside" in r.text


def test_rewind_list_does_not_silently_strip(client, victim):
	# 修复前 ``.strip()`` 把 ``" victim "`` 静默清洗成 victim → 200 + victim 数据。
	for padded in (" victim ", "victim "):
		r = client.get(f"/v1/sessions/{_q(padded)}/rewind")
		assert r.status_code == 422, (padded, r.text)


def test_rewind_unknown_wellformed_session_is_404_not_empty(client, victim):
	# 修复前 200 + []，与「存在但从没回溯过」不可区分。
	r = client.get("/v1/sessions/well-formed-ghost/rewind")
	assert r.status_code == 404
	assert "session_not_found" in r.text


def test_destructive_rewind_routes_refuse_ambiguous_ids(client, victim):
	# 破坏性路由（原子重写 transcript / 追加 checkpoint 行 / undo 回放）对
	# 歧义 id 必须 422 且不触盘——修复前分别实测为：200+transcript 被改、
	# 200+anchor 行写进 victim 的 checkpoints.jsonl、undo 选中 victim 的事件。
	tr_before = victim["transcript"].read_text(encoding="utf-8")
	cp_before = victim["checkpoints"].read_text(encoding="utf-8")
	r = client.post(
		f"/v1/sessions/{_q('victim.')}/rewind",
		json={"mode": "continue", "target_message_id": "u1",
			  "edited_text": "redo", "confirmed": True},
	)
	assert r.status_code == 422, r.text
	assert victim["transcript"].read_text(encoding="utf-8") == tr_before
	r = client.post(
		f"/v1/sessions/{_q('victim.')}/rewind/checkpoint/u1/anchor",
		json={"anchor": True},
	)
	assert r.status_code == 422, r.text
	assert victim["checkpoints"].read_text(encoding="utf-8") == cp_before
	r = client.post(
		f"/v1/sessions/{_q('vi:ctim')}/rewind/rw_1_aaaa/undo",
		json={"confirmed": True},
	)
	assert r.status_code == 422, r.text


def test_rewind_shape_edge_cases_never_500(client, victim):
	# NUL/超长 → 422；``.``/``..``/空段在路由层就被 404/405 挡掉——任何
	# 形态都不得落到 500，也不得改动 victim 的文件。
	tr_before = victim["transcript"].read_text(encoding="utf-8")
	cases = ["vic\x00tim", "v" * 300, "victim\x7f"]
	for bad in cases:
		r = client.get(f"/v1/sessions/{_q(bad)}/rewind")
		assert r.status_code == 422, (repr(bad), r.status_code, r.text)
	for dot in (".", "..", ""):
		r = client.get(f"/v1/sessions/{_q(dot)}/rewind")
		assert r.status_code in (404, 405, 422), (dot, r.status_code, r.text)
	assert victim["transcript"].read_text(encoding="utf-8") == tr_before


def test_rewind_known_session_still_works(client, victim):
	r = client.get("/v1/sessions/victim/rewind")
	assert r.status_code == 200
	assert r.json()[0]["rewind_id"] == "rw_1_aaaa"


def test_rewind_checkpoint_anchor_unknown_message_is_404(client, victim):
	# 「无 checkpoint」在锚点路由是事实性 404，不是 200-with-empty。
	r = client.post("/v1/sessions/victim/rewind/checkpoint/no-such-msg/anchor",
					json={"anchor": True})
	assert r.status_code == 404


# ----------------------------------------------------------------- goals ----

def _bind_goal(store, session_id: str, text: str):
	import asyncio

	return asyncio.run(
		store.create_and_bind_async(
			title="t", text=text, session_id=session_id, owner=session_id
		)
	)


def test_goal_ghost_new_does_not_pollute_fallback_workspace(client):
	# 修复前实测：PATCH action=new 对不存在的会话返回 200，并把 goal +
	# binding 写进 ``_pool.cwd`` 回落的服务器共享工作区。
	from engine.goal_state import GoalStore

	bindings_before = 0
	bdir = _SERVER_WS / ".xeyo" / "goals" / "bindings"
	if bdir.is_dir():
		bindings_before = len(list(bdir.iterdir()))
	r = client.patch("/v1/sessions/well-formed-ghost/goal",
					 json={"action": "new", "text": "evil phantom goal"})
	assert r.status_code == 404, r.text
	bindings_after = len(list(bdir.iterdir())) if bdir.is_dir() else 0
	assert bindings_after == bindings_before
	assert GoalStore(str(_SERVER_WS)).current("well-formed-ghost") is None


def test_goal_unknown_session_404_known_session_no_goal_empty(client, victim):
	# 「查无此会话」≠「会话存在没目标」：前者 404，后者维持 {} 契约（41 号）。
	r = client.get("/v1/sessions/well-formed-ghost/goal")
	assert r.status_code == 404
	_write("worker.jsonl", json.dumps({"id": "u1", "role": "user"}) + "\n")
	r = client.get("/v1/sessions/worker/goal")
	assert r.status_code == 200 and r.json() == {}


def test_goal_round_driver_disarm_unknown_session_is_404(client):
	# 修复前：对幻影会话 disarm 返回 200（缺失当成功）。
	r = client.post("/v1/sessions/well-formed-ghost/goal/round-driver",
					json={"action": "disarm"})
	assert r.status_code == 404


def test_goal_routes_reject_colliding_ids(client, victim):
	# goals 的 binding 文件名带 sha1 摘要，磁盘别名本就撞不上（probe：修复前
	# ``victim.`` 读到 {}）；但固定点判据统一在边缘执行——别名 id 一律 422，
	# 不得再以 200 形态穿透到 goal 面。
	for alias in ("victim.", "vi:ctim", " victim "):
		r = client.get(f"/v1/sessions/{_q(alias)}/goal")
		assert r.status_code == 422, (alias, r.text)
		r = client.patch(f"/v1/sessions/{_q(alias)}/goal",
						 json={"action": "confirm_complete"})
		assert r.status_code == 422, (alias, r.text)
		r = client.post(f"/v1/sessions/{_q(alias)}/goal/round-driver",
						json={"action": "arm"})
		assert r.status_code == 422, (alias, r.text)


def test_goal_bound_session_flow_unaffected(client, victim):
	from engine.goal_state import GoalStore

	goal = _bind_goal(GoalStore(str(_WS_V)), "victim", "real goal")
	r = client.get("/v1/sessions/victim/goal")
	assert r.status_code == 200
	body = r.json()
	assert body["goal_id"] == goal.goal_id
	assert body["driver"]["activation"] == "disarmed"
	r = client.post("/v1/sessions/victim/goal/round-driver", json={"action": "arm"})
	assert r.status_code == 200
	assert r.json()["driver"]["activation"] == "armed"
	r = client.post("/v1/sessions/victim/goal/round-driver", json={"action": "disarm"})
	assert r.status_code == 200
