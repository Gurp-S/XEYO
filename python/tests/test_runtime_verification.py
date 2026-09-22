"""runtime 完成前一致性检查契约。"""

from __future__ import annotations

import pytest

from engine.runtime_verification import verify_runtime
from msgtypes.message import Message, assistant_text_message, tool_result_message, ToolUse
from session.message_store import MessageStore


def test_verification_accepts_paired_tools_and_reports_detached_jobs(tmp_path) -> None:  # type: ignore[no-untyped-def]
	use = ToolUse(id="call-1", name="Read", input={})
	store = MessageStore(
		[
			assistant_text_message("", [use]),
			tool_result_message("call-1", "Read", "ok"),
		]
	)
	report = verify_runtime(
		store=store,
		cwd=str(tmp_path),
		jobs=[{"job_id": "j1", "status": "running"}],
	)
	assert report.ok is True
	assert report.active_jobs == 1


def test_verification_rejects_unpaired_or_unknown_execution(tmp_path) -> None:  # type: ignore[no-untyped-def]
	store = MessageStore(
		[assistant_text_message("", [ToolUse(id="call-2", name="Write", input={})])]
	)
	report = verify_runtime(
		store=store,
		cwd=str(tmp_path),
		action_summary={
			"actions": [
				{"action_id": "a1", "status": "unknown"},
				{"action_id": "a2", "status": "executing"},
			]
		},
	)
	assert report.ok is False
	assert report.unpaired_tool_calls == 1
	assert report.unknown_actions == 1
	assert report.pending_actions == 1


@pytest.mark.asyncio
async def test_query_engine_can_record_verification_without_changing_answer(tmp_path) -> None:  # type: ignore[no-untyped-def]
	from engine.query_engine import build_default_engine

	engine = build_default_engine(
		cwd=str(tmp_path),
		model_backend="fake",
		runtime_verify=True,
		session_id="runtime-verification-test",
	)
	events = [event async for event in engine.submit("hello")]
	assert events[-1].type == "result"
	snapshot = engine.runtime_snapshot()
	assert snapshot["verification"]["checked"] is True
	assert snapshot["verification"]["ok"] is True
