"""Agent 工具进度旁路：progress_sink → ToolProgressEvent.xy。"""

from __future__ import annotations

from typing import Any

import pytest

from engine.abort import AbortController
from msgtypes.events import ToolProgressEvent
from tools.agent_tool import AgentTool
from tools.progress_sink import emit_progress, reset_progress_sink, set_progress_sink


def test_emit_progress_noop_without_sink():
	emit_progress(ToolProgressEvent(name="Agent", message="x"))  # 不抛


def test_emit_progress_delivers_to_sink():
	seen: list[Any] = []
	token = set_progress_sink(seen.append)
	try:
		ev = ToolProgressEvent(
			name="Agent",
			xy={"type": "multi_agent_task", "uid": "t1:abc", "agent_id": "agent-t1-abc"},
		)
		emit_progress(ev)
		assert len(seen) == 1
		assert seen[0].xy["type"] == "multi_agent_task"
	finally:
		reset_progress_sink(token)


@pytest.mark.asyncio
async def test_agent_tool_emits_failed_progress_without_runtime():
	seen: list[ToolProgressEvent] = []
	token = set_progress_sink(lambda e: seen.append(e))
	try:
		at = AgentTool(cwd=".", session_id="sess_x")
		res = await at.execute({"task_id": "t9", "desc": "hello"}, AbortController())
		assert res.is_error
		types = [getattr(e.xy, "get", lambda *_: None)("type") if e.xy else None for e in seen]
		# dataclass 形态下 xy 是 dict
		types = [(e.xy or {}).get("type") for e in seen]
		assert "multi_agent_task" in types
		assert "multi_agent_progress" in types
		prog = next(e for e in seen if (e.xy or {}).get("type") == "multi_agent_progress")
		assert prog.xy["status"] == "failed"
		assert prog.xy["agent_id"].startswith("agent-t9-")
	finally:
		reset_progress_sink(token)


def test_partition_allows_multiple_agents_concurrent():
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry
	from tools.orchestration import partition_tool_calls

	reg = build_default_registry(cwd=".")
	uses = [
		ToolUse(id="1", name="Agent", input={"task_id": "a", "desc": "1"}),
		ToolUse(id="2", name="Agent", input={"task_id": "b", "desc": "2"}),
		ToolUse(id="3", name="Read", input={"path": "x"}),
	]
	parts = partition_tool_calls(reg, uses)
	# 全部 concurrency_safe → 应并入同一安全批次
	assert len(parts) == 1
	safe, batch = parts[0]
	assert safe is True
	assert len(batch) == 3


def test_agent_always_registered_soft_hint():
	"""无 chip 也可调 Agent；chip 文案为纯事实(E2 裁决)。"""
	from tools.agent_tool.prompt import DESCRIPTION, MULTI_AGENT_HINT
	from tools.catalog import build_default_registry

	reg = build_default_registry(cwd=".")
	assert reg.get("Agent") is not None
	assert "Always available" in DESCRIPTION
	# E2 裁决：chip 只告知"用户开启了 multi-agent"这一事实，无行为偏向。
	assert "multi-agent" in MULTI_AGENT_HINT
	assert "优先用 Agent" not in MULTI_AGENT_HINT
	assert "MUST" not in MULTI_AGENT_HINT
