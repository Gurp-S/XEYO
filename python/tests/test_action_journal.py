from __future__ import annotations

import pytest

from engine.action_journal import ActionJournal, action_identity
from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


def test_action_journal_replays_completed_result(tmp_path) -> None:
	journal = ActionJournal("session-a", enabled=True, sessions_dir=tmp_path)
	action_id, idem = action_identity(
		session_id="session-a",
		turn_id="turn-a",
		tool_use_id="call-a",
		tool_name="Write",
		tool_input={"path": "a.txt", "content": "x"},
	)
	first = journal.begin(
		action_id=action_id,
		idempotency_key=idem,
		turn_id="turn-a",
		tool_use_id="call-a",
		tool_name="Write",
		side_effect="write",
	)
	assert first.action == "execute"
	journal.complete(
		action_id,
		ToolResult(
			content="written",
			side_effect="write",
			action_id=action_id,
		),
	)
	second = journal.begin(
		action_id=action_id,
		idempotency_key=idem,
		turn_id="turn-a",
		tool_use_id="call-a",
		tool_name="Write",
		side_effect="write",
	)
	assert second.action == "replay"
	assert second.record is not None
	assert second.record["result_content"] == "written"


def test_action_journal_does_not_repeat_unknown_side_effect(tmp_path) -> None:
	journal = ActionJournal("session-a", enabled=True, sessions_dir=tmp_path)
	action_id, idem = action_identity(
		session_id="session-a",
		turn_id="turn-a",
		tool_use_id="call-a",
		tool_name="Bash",
		tool_input={"command": "make"},
	)
	journal.begin(
		action_id=action_id,
		idempotency_key=idem,
		turn_id="turn-a",
		tool_use_id="call-a",
		tool_name="Bash",
		side_effect="process",
	)
	journal.unknown(action_id, "process exited during disconnect")
	decision = journal.begin(
		action_id=action_id,
		idempotency_key=idem,
		turn_id="turn-a",
		tool_use_id="call-a",
		tool_name="Bash",
		side_effect="process",
	)
	assert decision.action == "recovery_required"


@pytest.mark.asyncio
async def test_tool_registry_replays_same_side_effect_call(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_ACTION_JOURNAL", "1")
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	calls = 0

	class SideEffectTool:
		name = "Write"

		@staticmethod
		def is_read_only() -> bool:
			return False

		@staticmethod
		def is_concurrency_safe() -> bool:
			return False

		def schema(self):
			return {"name": self.name, "description": "test", "input_schema": {"type": "object"}}

		async def execute(self, input, abort):
			nonlocal calls
			calls += 1
			return ToolResult(content="write complete")

	registry = ToolRegistry(cwd=str(tmp_path))
	tool = SideEffectTool()
	abort = AbortController()
	use = ToolUse(id="call-1", name="Write", input={"file_path": "a.txt"})
	first = await registry._execute_audited(tool, use, abort, session_id="s", turn_id="t")
	second = await registry._execute_audited(tool, use, abort, session_id="s", turn_id="t")
	assert first.content == second.content == "write complete"
	assert calls == 1
	assert second.metadata == {"action_replayed": True}
