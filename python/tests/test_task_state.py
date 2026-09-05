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
