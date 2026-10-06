"""agent_send（F5）：向运行中子 agent 追加消息的动词契约。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.live_agents as la  # noqa: E402
from engine.abort import AbortController  # noqa: E402
from engine.execution_context import ExecutionContext  # noqa: E402
from engine.workspace_context import set_workspace_context  # noqa: E402
from tools.error_taxonomy import INVALID_ARGUMENT, NOT_FOUND  # noqa: E402

SID = "s-agent-send"


@pytest.fixture(autouse=True)
def _clean():
	la.clear_all_for_tests()
	yield
	la.clear_all_for_tests()


def _ctx():
	set_workspace_context(ExecutionContext(session_id=SID, cwd=".", runtime="local"))


@pytest.mark.asyncio
async def test_send_to_live_agent_parks_message():
	from tools.agent_message_tool import AgentSendTool

	la.register_live_agent(SID, "ag-1", AbortController())
	_ctx()
	try:
		out = await AgentSendTool().execute(
			{"agent_id": "ag-1", "text": "补充一点"}, AbortController()
		)
	finally:
		set_workspace_context(None)
	assert out.is_error is False
	assert "queued follow-up" in out.content and "settles" in out.content
	assert la.inbox_count(SID, "ag-1") == 1
	items = la.drain_agent_inbox(SID, "ag-1")
	assert items[0]["text"] == "补充一点"


@pytest.mark.asyncio
async def test_send_unknown_agent_is_not_found():
	from tools.agent_message_tool import AgentSendTool

	_ctx()
	try:
		out = await AgentSendTool().execute(
			{"agent_id": "nope", "text": "hi"}, AbortController()
		)
	finally:
		set_workspace_context(None)
	assert out.is_error is True and out.error_kind == NOT_FOUND


@pytest.mark.asyncio
async def test_send_missing_text_or_too_long_is_invalid():
	from tools.agent_message_tool import AgentSendTool

	la.register_live_agent(SID, "ag-2", AbortController())
	_ctx()
	try:
		miss = await AgentSendTool().execute({"agent_id": "ag-2"}, AbortController())
		long = await AgentSendTool().execute(
			{"agent_id": "ag-2", "text": "x" * 2001}, AbortController()
		)
	finally:
		set_workspace_context(None)
	assert miss.is_error is True and miss.error_kind == INVALID_ARGUMENT
	assert long.is_error is True and long.error_kind == INVALID_ARGUMENT
	assert la.inbox_count(SID, "ag-2") == 0
