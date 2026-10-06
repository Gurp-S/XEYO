"""SessionTaskState 状态机与 QueryEngine 集成契约测试。"""

from __future__ import annotations

import pytest

from engine.task_state import SessionTaskState
from msgtypes.events import TaskStateEvent


def test_initial_status_queued_and_snapshot() -> None:
	st = SessionTaskState(session_id="s")
	snap = st.snapshot()
	assert snap["session_id"] == "s"
	assert snap["task_status"] == "queued"
	assert snap["revision"] == 0
	assert snap["interruptible"] is True


def test_set_status_advances_and_bumps_revision() -> None:
	st = SessionTaskState(session_id="s")
	assert st.set_status("running") is True
	assert st.status == "running"
	assert st.revision == 1
	# 可观察状态无变化 -> 返回 False（供事件去重），revision 仍推进。
	assert st.set_status("running") is False
	assert st.revision == 2


def test_set_status_updates_fields() -> None:
	st = SessionTaskState(session_id="s")
	st.set_status(
		"waiting_permission",
		turn_id="t1",
		current_tool="Write",
		interruptible=False,
	)
	snap = st.snapshot()
	assert snap["task_status"] == "waiting_permission"
	assert snap["turn_id"] == "t1"
	assert snap["current_tool"] == "Write"
	assert snap["interruptible"] is False


def test_task_state_event_type() -> None:
	ev = TaskStateEvent(
		session_id="s",
		turn_id="t1",
		task_status="running",
		current_tool=None,
	)
	assert ev.type == "task_state_changed"
	assert ev.task_status == "running"


@pytest.mark.asyncio
async def test_engine_task_state_terminal_after_submit() -> None:
	from engine.query_engine import build_default_engine

	eng = build_default_engine(model_backend="fake")
	async for _ev in eng.submit("hello"):
		pass
	snap = eng.task_state_snapshot()
	assert snap["task_status"] == "succeeded"
	assert snap["session_id"] == eng.session_id


# ---------- 显式 None = 清空；参数没给 = 保持 ----------


def test_explicit_none_clears_current_tool_and_error() -> None:
	st = SessionTaskState(session_id="s")
	st.set_status("waiting_permission", current_tool="Bash", interruptible=False)
	assert st.set_status("running", current_tool=None, interruptible=True) is True
	assert st.current_tool is None
	assert st.snapshot()["current_tool"] is None
	st.set_status("failed", error="boom")
	st.set_status("succeeded", error=None)
	assert st.error is None
	assert st.snapshot()["error"] is None


def test_absent_arguments_keep_previous_fields() -> None:
	"""反向自证：修复不得把「没给参数」也变成清空。"""
	st = SessionTaskState(session_id="s")
	st.set_status("waiting_permission", turn_id="t1", current_tool="Write")
	st.set_status("running")
	assert st.current_tool == "Write"
	assert st.turn_id == "t1"
	st.set_status("failed", error="boom")
	st.set_status("stopped")
	assert st.error == "boom"


def test_dedup_flag_counts_a_clear_as_an_observable_change() -> None:
	"""去重标记：同状态下的清空必须是「可观察变化」，否则前端收不到纠正事件。

	先 waiting_permission 再 running 的写法恒真 —— status 本身就变了，量不到
	clear 这一项，故这里把 status 钉死。
	"""
	st = SessionTaskState(session_id="s")
	st.set_status("running", current_tool="Bash")
	assert st.set_status("running", current_tool=None) is True
	# 已经是 None 再给 None：无变化（事件去重仍成立）。
	assert st.set_status("running", current_tool=None) is False


@pytest.mark.asyncio
async def test_permission_resolve_clears_current_tool_through_coordinator() -> None:
	"""生产接线：request 写工具名，wait 收尾必须把它清掉（诊断面读的就是这里）。"""
	from engine.permission_coordinator import PermissionCoordinator
	from permissions.store import PendingPermissionStore

	st = SessionTaskState(session_id="s")
	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=st,
		session_id="s",
		turn_id="t1",
		on_event=lambda ev: None,
	)
	rid = coord.request(
		tool_name="Bash",
		tool_input={"command": "ls"},
		reason="needs_confirmation",
		prompt="run ls?",
	)
	assert st.current_tool == "Bash"
	coord.resolve(rid, True, actor="user")
	assert await coord.wait(rid, timeout=2.0) == "allow"
	assert st.status == "running"
	assert st.current_tool is None
	assert st.interruptible is True
