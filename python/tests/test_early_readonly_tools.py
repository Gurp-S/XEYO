"""只读工具 SSE 闭合即投机执行（XEYO_EARLY_READONLY_TOOLS）。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import (
	_eligible_for_early,
	early_readonly_tools_enabled,
	query_loop,
)
from model.chunks import ModelChunk
from msgtypes.events import FinalEvent, ToolResultEvent
from msgtypes.message import ToolUse, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.base_tool import ToolResult
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


class _TimingEcho(EchoTool):
	"""记录 execute 开始墙钟，便于断言与模型流重叠。"""

	starts: list[float] = []

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		_TimingEcho.starts.append(time.monotonic())
		await asyncio.sleep(0.05)
		return await super().execute(input, abort)


class _StaggerModel:
	"""先 yield 完整 echo tool_use，再 sleep，再结束流（第二轮纯文本）。"""

	def __init__(self) -> None:
		self.stream_ended_at: float | None = None
		self._turn = 0

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		abort.raise_if_aborted()
		self._turn += 1
		if self._turn == 1:
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id="call_early_echo",
					name="echo",
					input={"text": "overlap"},
				),
			)
			await asyncio.sleep(0.2)
			self.stream_ended_at = time.monotonic()
			return
		yield ModelChunk(kind="text_delta", text="done")


class _EditOnlyTool:
	name = "Edit"

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict:
		return {
			"name": "Edit",
			"description": "test edit",
			"input_schema": {"type": "object", "properties": {}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		abort.raise_if_aborted()
		return ToolResult(content="edited")


@pytest.fixture(autouse=True)
def _reset_timing() -> None:
	_TimingEcho.starts = []


def test_early_flag_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_EARLY_READONLY_TOOLS", raising=False)
	assert early_readonly_tools_enabled() is True


def test_eligible_echo_yes_edit_no(tmp_path: Path) -> None:
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(EchoTool())
	reg.register(_EditOnlyTool())
	echo_tu = ToolUse(id="a", name="echo", input={"text": "x"})
	edit_tu = ToolUse(id="b", name="Edit", input={"file_path": "a.py"})
	assert _eligible_for_early(reg, echo_tu, forced_wrap_up=False) is True
	assert _eligible_for_early(reg, edit_tu, forced_wrap_up=False) is False
	assert _eligible_for_early(reg, echo_tu, forced_wrap_up=True) is False


@pytest.mark.asyncio
async def test_early_echo_overlaps_model_tail(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_EARLY_READONLY_TOOLS", raising=False)
	model = _StaggerModel()
	reg = ToolRegistry()
	reg.register(_TimingEcho())
	store = MessageStore([user_message("go")])
	events = []
	async for ev in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		events.append(ev)

	assert model.stream_ended_at is not None
	assert _TimingEcho.starts, "echo should have started"
	assert _TimingEcho.starts[0] < model.stream_ended_at
	assert any(isinstance(e, ToolResultEvent) and e.output == "overlap" for e in events)
	assert any(isinstance(e, FinalEvent) for e in events)


@pytest.mark.asyncio
async def test_early_disabled_starts_after_stream(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "0")
	model = _StaggerModel()
	reg = ToolRegistry()
	reg.register(_TimingEcho())
	store = MessageStore([user_message("go")])
	async for _ in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		pass

	assert model.stream_ended_at is not None
	assert _TimingEcho.starts
	assert _TimingEcho.starts[0] >= model.stream_ended_at
