"""空对话（无转录、pool 未知）里第一个动作就是 ``/goal``：目标必须可读、可收敛。

事故形状（GUI e2e ``gui/e2e/composer-slash.spec.ts`` 先登记，本文件把它钉回路由层）：

- ``POST /v1/slash {name: "goal"}`` 返回 200「已创建目标」——写侧不设「会话已知」
  门，目标按调用方给的工作区写进 ``.xeyo/goals/``；
- 紧接着回读 ``GET /v1/sessions/{sid}/goal`` 却是 **404 session not found**
  ——读侧 ``goals._require_known_session`` 要求 pool 钉过该会话或磁盘上有
  transcript，而全新会话（id 由前端自造，首个 chat 请求还没发生）两边都不满足；
- 后果：条带永远挂不出来，用户只拿到一条「目标投影读不到」的错误 toast。

修法（读写口径一致，而不是放宽读侧的门）：``/v1/slash`` 的 goal 命令成功后在
边缘把「会话 → 工作区」登记进 pool —— 与首个 chat 请求同一张表、同一
first-write-wins 语义；从未产生过任何落盘物的幻影 id 仍然 404（防幻影会话把
goal 写进服务器共享工作区的门保持原样）。

Windows GBK 控制台：用例内不打印中文。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
	home = tmp_path / "home"
	data = tmp_path / "data"
	sessions = tmp_path / "sessions"
	for d in (home, data, sessions):
		d.mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.setenv("XEYO_DATA_DIR", str(data))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(sessions))
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True)
	return {"tmp": tmp_path, "ws": ws, "sessions": sessions}


@pytest.fixture(autouse=True)
def _restore_pool_pins():
	"""登记直接写进单例 pool 的 ``_session_cwd``——用例后还原，防跨用例污染。"""
	from server.deps import _pool

	with _pool._lock:
		before = dict(_pool._session_cwd)
	try:
		yield
	finally:
		with _pool._lock:
			_pool._session_cwd.clear()
			_pool._session_cwd.update(before)


def _app():
	from server.app import app

	return app


def _ascii_only(text: str) -> str:
	return text.encode("ascii", "backslashreplace").decode("ascii")


def test_goal_as_first_action_on_fresh_session_is_readable(
	sandbox: dict[str, Path],
) -> None:
	"""/v1/slash 建目标 200 后，回读投影必须 200 且内容一致（核心回归）。"""
	sid = "sess-goal-first-action"
	ws = str(sandbox["ws"])
	with TestClient(_app()) as client:
		posted = client.post(
			"/v1/slash",
			json={
				"name": "goal",
				"arg": "Refactor login module and pass tests",
				"session_id": sid,
				"workspace": ws,
			},
		)
		assert posted.status_code == 200, _ascii_only(posted.text)[:200]
		body = posted.json()
		assert body["handled"] is True
		assert body["result"]["ok"] is True
		goal_id = body["result"]["goal_id"]

		got = client.get(f"/v1/sessions/{sid}/goal")
		assert got.status_code == 200, _ascii_only(got.text)[:200]
		goal = got.json()
		assert goal["goal_id"] == goal_id
		assert goal["text"] == "Refactor login module and pass tests"
		assert goal["status"] == "active"
		assert isinstance(goal["revision"], int) and goal["revision"] >= 1


def test_goal_verbs_work_on_fresh_session(sandbox: dict[str, Path]) -> None:
	"""读侧的门不止 GET：pause / resume / edit / drop 对空对话同样可用。"""
	sid = "sess-goal-verbs"
	ws = str(sandbox["ws"])
	with TestClient(_app()) as client:
		posted = client.post(
			"/v1/slash",
			json={
				"name": "goal",
				"arg": "goal verbs on fresh session",
				"session_id": sid,
				"workspace": ws,
			},
		)
		assert posted.status_code == 200, _ascii_only(posted.text)[:200]
		got = client.get(f"/v1/sessions/{sid}/goal")
		assert got.status_code == 200, _ascii_only(got.text)[:200]
		goal = got.json()

		paused = client.patch(
			f"/v1/sessions/{sid}/goal",
			json={"action": "pause", "revision": goal["revision"]},
		)
		assert paused.status_code == 200, _ascii_only(paused.text)[:200]
		assert paused.json()["status"] == "paused"

		resumed = client.patch(
			f"/v1/sessions/{sid}/goal",
			json={"action": "resume", "revision": paused.json()["revision"]},
		)
		assert resumed.status_code == 200, _ascii_only(resumed.text)[:200]
		assert resumed.json()["status"] == "active"

		edited = client.patch(
			f"/v1/sessions/{sid}/goal",
			json={
				"action": "edit",
				"revision": resumed.json()["revision"],
				"text": "edited objective body",
			},
		)
		assert edited.status_code == 200, _ascii_only(edited.text)[:200]
		assert edited.json()["text"] == "edited objective body"

		dropped = client.patch(
			f"/v1/sessions/{sid}/goal",
			json={"action": "drop", "revision": edited.json()["revision"]},
		)
		assert dropped.status_code == 200, _ascii_only(dropped.text)[:200]
		assert dropped.json()["status"] == "abandoned"


def test_phantom_session_never_touched_by_slash_still_404(
	sandbox: dict[str, Path],
) -> None:
	"""反向：没跑过 goal 的 id 不许被登记——GET/PATCH 仍 404，且不落任何盘。"""
	sid = "sess-phantom-untouched"
	with TestClient(_app()) as client:
		got = client.get(f"/v1/sessions/{sid}/goal")
		assert got.status_code == 404, _ascii_only(got.text)[:200]
		patch = client.patch(
			f"/v1/sessions/{sid}/goal",
			json={"action": "new", "text": "phantom"},
		)
		assert patch.status_code == 404, _ascii_only(patch.text)[:200]
	# pool 回落工作区（conftest 钉的 xeyo_ws）不许出现幻影 goal。
	fallback = sandbox["tmp"] / "xeyo_ws"
	assert not (fallback / ".xeyo" / "goals").exists()
