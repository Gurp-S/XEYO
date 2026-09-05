from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from permissions.policy import (
	readonly_gate,
	set_agent_mode,
	tool_allowed_in_mode,
)
from tools.catalog import build_default_registry


def test_ask_and_plan_only_allow_readonly_tools() -> None:
	set_agent_mode("ask")
	try:
		assert tool_allowed_in_mode("Read")
		assert tool_allowed_in_mode("Glob")
		assert tool_allowed_in_mode("Grep")
		assert not tool_allowed_in_mode("MemorySearch")  # 已收敛:读走 Grep
		assert tool_allowed_in_mode("echo")
		assert tool_allowed_in_mode("getTime")
		assert not tool_allowed_in_mode("Write")
		assert not tool_allowed_in_mode("Bash")
		assert not tool_allowed_in_mode("TodoWrite")
		assert not tool_allowed_in_mode("Echo")  # 错误大小写不得放行
		assert not tool_allowed_in_mode("GetTime")
		readable_gate = readonly_gate("Write")
		assert readable_gate
		assert readable_gate == "readonly_mode_deny"
		assert readonly_gate("echo") is None
		assert readonly_gate("getTime") is None
		assert readonly_gate("SendToWeChat") == "readonly_mode_deny"
		assert readonly_gate("Screenshot") == "readonly_mode_deny"
		assert readonly_gate("WebFetch") == "readonly_mode_deny"
		assert readonly_gate("WebSearch") == "readonly_mode_deny"
	finally:
		set_agent_mode("agent")


def test_ask_mode_uses_tool_is_read_only_flag(tmp_path: Path) -> None:
	"""有工具实例时以 is_read_only() 为准，不再只靠名字表。"""
	reg = build_default_registry(cwd=str(tmp_path))
	set_agent_mode("ask")
	try:
		assert tool_allowed_in_mode("Read", tool=reg.get("Read"))
		assert not tool_allowed_in_mode("Screenshot", tool=reg.get("Screenshot"))
		assert not tool_allowed_in_mode("SendToWeChat", tool=reg.get("SendToWeChat"))
		assert not tool_allowed_in_mode("WebFetch", tool=reg.get("WebFetch"))
		assert not tool_allowed_in_mode("WebSearch", tool=reg.get("WebSearch"))
		assert not tool_allowed_in_mode("Write", tool=reg.get("Write"))
		assert readonly_gate("Screenshot", tool=reg.get("Screenshot")) == "readonly_mode_deny"
		assert readonly_gate("Read", tool=reg.get("Read")) is None
	finally:
		set_agent_mode("agent")


def test_plan_allows_exit_plan_mode_but_not_write(tmp_path: Path) -> None:
	set_agent_mode("plan")
	try:
		assert tool_allowed_in_mode("Read")
		assert tool_allowed_in_mode("ExitPlanMode")
		assert not tool_allowed_in_mode("Write")
		assert readonly_gate("Write") == "readonly_mode_deny"
	finally:
		set_agent_mode("agent")


@pytest.mark.asyncio
async def test_tool_registry_denies_write_in_ask_mode(tmp_path: Path) -> None:
	reg = build_default_registry(cwd=str(tmp_path))
	abort = AbortController()
	set_agent_mode("ask")
	try:
		result = await reg.run(
			ToolUse(
				id="1",
				name="Write",
				input={"file_path": str(tmp_path / "out.txt"), "content": "x"},
			),
			abort,
		)
		assert result.is_error
		assert "read-only mode" in result.content
		assert not (tmp_path / "out.txt").exists()
	finally:
		set_agent_mode("agent")


def test_mode_prompt_helpers_remain_agent_by_default() -> None:
	set_agent_mode(None)
	try:
		assert tool_allowed_in_mode("Write")
		assert readonly_gate("Write") is None
	finally:
		set_agent_mode("agent")
