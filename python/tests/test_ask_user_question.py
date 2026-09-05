"""AskUserQuestion 挂起—恢复（ask_store + registry 复用权限骨架）契约测试。"""

from __future__ import annotations

import asyncio

import pytest

from engine.abort import AbortController
from engine.permission_coordinator import PermissionCoordinator
from engine.task_state import SessionTaskState
from msgtypes.events import AskUserPendingEvent, AskUserResolvedEvent
from msgtypes.message import ToolUse
from permissions.ask_store import PendingAskStore, default_ask_store
from permissions.store import PendingPermissionStore
from tools.ask_user_question_tool import AskUserQuestionTool, ASK_USER_TOOL_NAME
from tools.tool_registry import ToolRegistry


def _coordinator() -> PermissionCoordinator:
	return PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=SessionTaskState(session_id="s"),
		session_id="s",
		turn_id="t1",
	)


@pytest.mark.asyncio
async def test_registry_ask_creates_pending_and_does_not_execute(tmp_path) -> None:
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(AskUserQuestionTool())
	abort = AbortController()
	result = await reg.run(
		ToolUse(
			id="1",
			name=ASK_USER_TOOL_NAME,
			input={"question": "Which path?", "options": ["a", "b"]},
		),
		abort,
		coordinator=_coordinator(),
	)
	assert result.metadata is not None
	rid = result.metadata["ask_pending"]
	assert rid
	assert result.metadata["question"] == "Which path?"
	assert result.metadata["options"] == ["a", "b"]
	pending = default_ask_store().get(str(rid))
	assert pending is not None
	assert pending.question == "Which path?"
	assert pending.options == ["a", "b"]
	assert pending.resolved is False


@pytest.mark.asyncio
async def test_registry_ask_requires_question(tmp_path) -> None:
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(AskUserQuestionTool())
	abort = AbortController()
	result = await reg.run(
		ToolUse(id="1", name=ASK_USER_TOOL_NAME, input={}),
		abort,
		coordinator=_coordinator(),
	)
	assert result.is_error
	assert "question" in (result.content or "").lower()


@pytest.mark.asyncio
async def test_registry_ask_without_coordinator_errors(tmp_path) -> None:
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(AskUserQuestionTool())
	abort = AbortController()
	result = await reg.run(
		ToolUse(
			id="1", name=ASK_USER_TOOL_NAME, input={"question": "Proceed?"}
		),
		abort,
	)
	assert result.is_error


@pytest.mark.asyncio
async def test_store_resolve_then_wait_returns_answer() -> None:
	store = PendingAskStore()
	item = store.create(
		session_id="s", turn_id="t1", question="Pick one?", options=["x", "y"]
	)
	assert store.resolve_answer(item.request_id, "x", actor="desktop") is True
	resolved = await store.wait(item.request_id, timeout=1.0)
	assert resolved is not None
	assert resolved.resolved is True
	assert resolved.answer == "x"
	assert resolved.actor == "desktop"


@pytest.mark.asyncio
async def test_store_resolve_is_idempotent() -> None:
	store = PendingAskStore()
	item = store.create(
		session_id="s", turn_id="t1", question="Pick one?", options=["x", "y"]
	)
	assert store.resolve_answer(item.request_id, "x") is True
	assert store.resolve_answer(item.request_id, "y") is False


@pytest.mark.asyncio
async def test_store_timeout_returns_unresolved() -> None:
	store = PendingAskStore()
	item = store.create(session_id="s", turn_id="t1", question="Pick one?")
	resolved = await store.wait(item.request_id, timeout=0.05)
	assert resolved is not None
	assert resolved.resolved is False
	assert resolved.answer is None


@pytest.mark.asyncio
async def test_pending_events_carry_question_and_answer() -> None:
	store = default_ask_store()
	item = store.create(
		session_id="s", turn_id="t1", question="Proceed?", options=["yes", "no"]
	)
	pending_ev = AskUserPendingEvent(
		request_id=item.request_id,
		session_id="s",
		turn_id="t1",
		question=item.question,
		options=item.options,
		default=item.default,
		expires_at=item.expires_at,
	)
	assert pending_ev.question == "Proceed?"
	assert pending_ev.options == ["yes", "no"]

	store.resolve_answer(item.request_id, "yes", actor="desktop")
	resolved = await store.wait(item.request_id, timeout=1.0)
	assert resolved is not None
	resolved_ev = AskUserResolvedEvent(
		request_id=item.request_id,
		answer=resolved.answer if resolved.answer is not None else "",
		actor=resolved.actor,
		timeout=resolved.answer is None,
	)
	assert resolved_ev.answer == "yes"
	assert resolved_ev.timeout is False
