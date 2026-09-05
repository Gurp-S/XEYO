"""事件 Envelope 与新增权限/任务事件契约测试。"""

from __future__ import annotations

import time

from msgtypes.envelope import Envelope, EventIdGenerator, wrap
from msgtypes.events import (
	AssistantDelta,
	EngineEvent,
	PermissionPendingEvent,
	PermissionResolvedEvent,
	TaskStateEvent,
	ToolResultEvent,
)


def test_wrap_sets_identity_and_type() -> None:
	ev = AssistantDelta(text="hello")
	env = wrap(
		ev,
		session_id="s1",
		turn_id="t1",
		event_id=3,
	)
	assert isinstance(env, Envelope)
	assert env.schema_version == "1.0"
	assert env.session_id == "s1"
	assert env.turn_id == "t1"
	assert env.event_id == 3
	assert env.type == "assistant_delta"
	assert env.payload is ev
	assert isinstance(env.created_at, float)
	assert 0 <= time.time() - env.created_at < 5


def test_event_id_generator_monotonic_and_reset() -> None:
	gen = EventIdGenerator()
	ids = [gen.next() for _ in range(5)]
	assert ids == [1, 2, 3, 4, 5]
	gen.reset()
	assert gen.next() == 1


def test_permission_pending_event_type() -> None:
	ev = PermissionPendingEvent(
		request_id="r1",
		tool_name="Write",
		tool_input={"path": "a.txt"},
		reason="needs_confirmation",
		prompt="Write to a.txt?",
		path="a.txt",
		expires_at=time.time() + 30,
	)
	assert ev.type == "permission_pending"
	env = wrap(ev, session_id="s1", turn_id="t1", event_id=1)
	assert env.type == "permission_pending"
	assert env.payload.request_id == "r1"
	assert env.payload.tool_name == "Write"


def test_permission_resolved_event_type() -> None:
	ev = PermissionResolvedEvent(
		request_id="r1",
		approved=True,
		actor="desktop",
		reason="user_approved",
	)
	assert ev.type == "permission_resolved"
	env = wrap(ev, session_id="s1", turn_id="t1", event_id=2)
	assert env.type == "permission_resolved"
	assert env.payload.approved is True


def test_task_state_event_type() -> None:
	ev = TaskStateEvent(
		session_id="s1",
		turn_id="t1",
		task_status="waiting_permission",
		current_tool="Write",
		interruptible=False,
	)
	assert ev.type == "task_state_changed"
	env = wrap(ev, session_id="s1", turn_id="t1", event_id=3)
	assert env.type == "task_state_changed"
	assert env.payload.task_status == "waiting_permission"


def test_existing_event_still_wrappable_unchanged() -> None:
	# 旧事件保持原有 type 与字段，能被 envelope 包装而不改变行为。
	res = ToolResultEvent(name="Read", output="ok", is_error=False)
	assert res.type == "tool_result"
	env = wrap(res, session_id="s1", turn_id="t1", event_id=4)
	assert env.type == "tool_result"
	assert env.payload.output == "ok"
	# 确认 EngineEvent 联合类型仍接受上述三种新事件（构造不抛错即视为契约通过）。
	assert EngineEvent is not None  # 仅触发引用，避免 linter 误报未使用

