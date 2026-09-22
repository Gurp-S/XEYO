"""ToolCall 状态机和编排接线契约。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.tool_call_state import InvalidToolCallTransition, ToolCallState
from msgtypes.message import ToolUse
from tools.echo import EchoTool
from tools.orchestration import _run_one_tool
from tools.tool_registry import ToolRegistry


def test_tool_call_state_rejects_terminal_reentry() -> None:
	state = ToolCallState("u1")
	state.transition("validated")
	state.transition("running")
	state.transition("completed")

	assert state.terminal
	assert state.history == ["new", "validated", "running", "completed"]
	with pytest.raises(InvalidToolCallTransition):
		state.transition("running")


def test_orchestration_records_completed_state_metadata() -> None:
	registry = ToolRegistry()
	registry.register(EchoTool())
	result = asyncio.run(
		_run_one_tool(
			registry,
			ToolUse(id="u1", name="echo", input={"text": "ok"}),
			AbortController(),
			coordinator=None,
		)
	)

	assert result.content == "ok"
	assert result.metadata["tool_call_state"] == "completed"
	assert result.metadata["tool_call_state_history"] == [
		"new",
		"validated",
		"running",
		"completed",
	]
