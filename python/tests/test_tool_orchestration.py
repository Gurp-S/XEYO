"""工具分区：安全∥ / 不安全串行；超时与批内隔离。"""

from __future__ import annotations

import asyncio

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.echo import EchoTool
from tools.file_edit_tool.file_edit_tool import FileEditTool
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.orchestration import (
	is_concurrency_safe,
	partition_tool_calls,
	run_tools_partitioned,
)
from tools.tool_registry import ToolRegistry


def _reg(tmp_path) -> ToolRegistry:
	reg = ToolRegistry()
	reg.register(EchoTool())
	reg.register(FileReadTool(cwd=str(tmp_path)))
	reg.register(FileEditTool(cwd=str(tmp_path)))
	return reg


def test_partition_coalesces_safe_then_splits_unsafe(tmp_path):
	reg = _reg(tmp_path)
	uses = [
		ToolUse(id="1", name="echo", input={"text": "a"}),
		ToolUse(id="2", name="Read", input={"file_path": str(tmp_path / "x")}),
		ToolUse(
			id="3",
			name="Edit",
			input={
				"file_path": str(tmp_path / "x"),
				"old_string": "a",
				"new_string": "b",
			},
		),
		ToolUse(id="4", name="echo", input={"text": "b"}),
	]
	# 确认安全标志
	assert is_concurrency_safe(reg, "echo")
	assert is_concurrency_safe(reg, "Read")
	assert not is_concurrency_safe(reg, "Edit")

	batches = partition_tool_calls(reg, uses)
	# [echo, Read] 安全批次 → Edit 单独 → echo 单独（安全但在 unsafe 之后）
	assert len(batches) == 3
	assert batches[0][0] is True and [u.name for u in batches[0][1]] == [
		"echo",
		"Read",
	]
	assert batches[1][0] is False and batches[1][1][0].name == "Edit"
	assert batches[2][0] is True and batches[2][1][0].name == "echo"


def test_unknown_tool_not_safe(tmp_path):
	reg = _reg(tmp_path)
	assert not is_concurrency_safe(reg, "nope")


class _BoomTool:
	name = "Boom"

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict:
		return {
			"name": self.name,
			"description": "boom",
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		raise RuntimeError("boom")


class _OkSafeTool:
	name = "OkSafe"

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict:
		return {
			"name": self.name,
			"description": "ok",
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		return ToolResult(content="ok", is_error=False)


class _SlowTool:
	name = "Slow"

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict:
		return {
			"name": self.name,
			"description": "slow",
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		await asyncio.sleep(2.0)
		return ToolResult(content="late", is_error=False)


@pytest.mark.asyncio
async def test_safe_batch_isolates_sibling_on_exception(tmp_path, monkeypatch):
	"""安全批内一工具抛错，不得丢弃同批其它结果。"""
	from permissions.filesystem import PermissionDecision
	from permissions.policy import PolicyDecision

	monkeypatch.setattr(
		"tools.tool_registry.evaluate_policy",
		lambda *a, **k: PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="test_allow",
			matched_rule="test",
		),
	)
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(_BoomTool())
	reg.register(_OkSafeTool())
	abort = AbortController()
	results = await run_tools_partitioned(
		reg,
		[
			ToolUse(id="1", name="Boom", input={}),
			ToolUse(id="2", name="OkSafe", input={}),
		],
		abort,
	)
	assert len(results) == 2
	assert results[0].is_error
	assert "boom" in results[0].content.lower()
	assert not results[1].is_error
	assert results[1].content == "ok"


@pytest.mark.asyncio
async def test_tool_timeout_returns_error(tmp_path, monkeypatch):
	from permissions.filesystem import PermissionDecision
	from permissions.policy import PolicyDecision

	monkeypatch.setenv("XEYO_TOOL_TIMEOUT_S", "0.05")
	monkeypatch.setattr(
		"tools.tool_registry.evaluate_policy",
		lambda *a, **k: PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="test_allow",
			matched_rule="test",
		),
	)
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(_SlowTool())
	abort = AbortController()
	results = await run_tools_partitioned(
		reg,
		[ToolUse(id="1", name="Slow", input={})],
		abort,
	)
	assert len(results) == 1
	assert results[0].is_error
	assert "timed out" in results[0].content
	# 局部 abort 不应污染父控制器
	assert not abort.aborted
