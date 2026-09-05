"""工具进度心跳：orchestration → ToolProgressEvent。"""

from __future__ import annotations

import asyncio

import pytest

from engine.abort import AbortController
from msgtypes.events import ToolProgressEvent
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.orchestration import run_tools_partitioned
from tools.tool_registry import ToolRegistry


class _SlowTool:
	name = "echo"  # 命中 policy always_allow，避免 unknown_tool ASK

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict:
		return {
			"name": self.name,
			"description": "slow",
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		await asyncio.sleep(0.35)
		abort.raise_if_aborted()
		return ToolResult(content="done")


@pytest.mark.asyncio
async def test_progress_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_TOOL_PROGRESS_S", "0.1")
	monkeypatch.setenv("XEYO_TOOL_TIMEOUT_S", "5")
	reg = ToolRegistry(cwd=".")
	reg.register(_SlowTool())
	q: asyncio.Queue[ToolProgressEvent] = asyncio.Queue()
	results = await run_tools_partitioned(
		reg,
		[ToolUse(id="c1", name="echo", input={})],
		AbortController(),
		progress_q=q,
	)
	assert len(results) == 1
	assert results[0].content == "done"
	events: list[ToolProgressEvent] = []
	while not q.empty():
		events.append(q.get_nowait())
	assert any(isinstance(e, ToolProgressEvent) for e in events)
	assert events[0].name == "echo"
	assert events[0].tool_use_id == "c1"
