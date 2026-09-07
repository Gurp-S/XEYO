"""主循环四刀：跨 submit 投影缓存、early 即 yield+占配额、XML 流式、queue 唤醒。"""

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
from engine.query_loop import query_loop
from engine.xml_tool_call import XmlToolCallBuffer
from memory.working import WorkingSnapshot
from model.chunks import ModelChunk
from msgtypes.events import ToolCallEvent, ToolResultEvent
from msgtypes.message import ToolUse, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.base_tool import ToolResult
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# XML 流缓冲
# ---------------------------------------------------------------------------


def test_xml_buffer_feeds_complete_calls_incrementally():
	buf = XmlToolCallBuffer()
	assert buf.feed("<tool_call>Read\n") == []
	assert buf.feed("<arg_key>file_path</arg_key>\n") == []
	uses = buf.feed("<arg_value>a.py</arg_value>\n</tool_call>\nmore")
	assert len(uses) == 1
	assert uses[0].name == "Read"
	assert uses[0].input["file_path"] == "a.py"
	assert "more" in buf.buffer
	assert "<tool_call>" not in buf.buffer


# ---------------------------------------------------------------------------
# 跨提交 proj_cache
# ---------------------------------------------------------------------------


class _TextModel:
	def __init__(self) -> None:
		self.calls = 0

	async def stream(self, messages, tools, abort):
		self.calls += 1
		abort.raise_if_aborted()
		yield ModelChunk(kind="text_delta", text=f"ok{self.calls}")


@pytest.mark.asyncio
async def test_proj_cache_survives_across_submit(monkeypatch, mem_switch):
	monkeypatch.delenv("XEYO_L5", raising=False)
	# 2026-09-06：v61 默认开启（decide 每轮）；投影缓存是 project 快路径属性 →
	# 显式 project 测「缓存命中跨 submit 存活」。
	mem_switch(XEYO_L5="project")
	snap = WorkingSnapshot()
	store = MessageStore()
	model = _TextModel()
	reg = ToolRegistry()
	reg.register(EchoTool())

	store.append(user_message("one"))
	async for _ in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=2),
		working=snap,
	):
		pass
	assert snap.proj_cache is not None
	base_len_after_first = snap.proj_cache[0]
	assert base_len_after_first >= 1

	store.append(user_message("two"))
	prev_names = dict(snap.proj_cache[5])
	async for _ in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=2),
		working=snap,
	):
		pass
	assert snap.proj_cache is not None
	assert snap.proj_cache[0] >= base_len_after_first
	# 增量路径复用了 id→name 前缀映射
	assert snap.proj_cache[5].keys() >= prev_names.keys()
	assert model.calls == 2


# ---------------------------------------------------------------------------
# 提前：流未结束先到 ToolCallEvent；配额先于 run
# ---------------------------------------------------------------------------


class _TimingEcho(EchoTool):
	starts: list[float] = []

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		_TimingEcho.starts.append(time.monotonic())
		await asyncio.sleep(0.05)
		return await super().execute(input, abort)


class _StaggerEchoModel:
	def __init__(self) -> None:
		self.stream_ended_at: float | None = None
		self._turn = 0

	async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
		abort.raise_if_aborted()
		self._turn += 1
		if self._turn == 1:
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id="call_early",
					name="echo",
					input={"text": "hi"},
				),
			)
			await asyncio.sleep(0.2)
			self.stream_ended_at = time.monotonic()
			return
		yield ModelChunk(kind="text_delta", text="done")


@pytest.mark.asyncio
async def test_tool_call_event_before_stream_ends(monkeypatch):
	monkeypatch.delenv("XEYO_EARLY_READONLY_TOOLS", raising=False)
	_TimingEcho.starts = []
	model = _StaggerEchoModel()
	reg = ToolRegistry()
	reg.register(_TimingEcho())
	store = MessageStore([user_message("go")])
	call_at: float | None = None
	async for ev in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		if isinstance(ev, ToolCallEvent) and call_at is None:
			call_at = time.monotonic()
	assert model.stream_ended_at is not None
	assert call_at is not None
	assert call_at < model.stream_ended_at
	assert _TimingEcho.starts
	assert _TimingEcho.starts[0] < model.stream_ended_at


@pytest.mark.asyncio
async def test_early_respects_tool_call_quota(monkeypatch):
	"""超配额的 early 不得启动 execute。"""
	monkeypatch.delenv("XEYO_EARLY_READONLY_TOOLS", raising=False)
	_TimingEcho.starts = []

	class _ManyEcho:
		def __init__(self) -> None:
			self._turn = 0

		async def stream(self, messages, tools, abort):
			self._turn += 1
			if self._turn == 1:
				for i in range(5):
					yield ModelChunk(
						kind="tool_use",
						tool_use=ToolUse(
							id=f"c{i}",
							name="echo",
							input={"text": f"t{i}"},
						),
					)
				return
			yield ModelChunk(kind="text_delta", text="done")

	reg = ToolRegistry()
	reg.register(_TimingEcho())
	store = MessageStore([user_message("go")])
	events = []
	async for ev in query_loop(
		store=store,
		model=_ManyEcho(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4, max_tool_calling=2),
	):
		events.append(ev)
	calls = [e for e in events if isinstance(e, ToolCallEvent)]
	results = [e for e in events if isinstance(e, ToolResultEvent)]
	assert len(calls) == 2
	assert len(results) == 5
	assert sum(1 for e in results if e.is_error) == 3
	assert len(_TimingEcho.starts) == 2


# ---------------------------------------------------------------------------
# XML 流式提前
# ---------------------------------------------------------------------------


class _XmlReadTool:
	name = "Read"
	started = asyncio.Event()

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict:
		return {
			"name": "Read",
			"description": "read",
			"input_schema": {"type": "object", "properties": {"file_path": {}}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		_XmlReadTool.started.set()
		await asyncio.sleep(0.05)
		return ToolResult(content="file body")


class _XmlStreamModel:
	def __init__(self) -> None:
		self.stream_ended_at: float | None = None
		self._turn = 0

	async def stream(self, messages, tools, abort):
		self._turn += 1
		if self._turn == 1:
			parts = [
				"Let me read.\n",
				"<tool_call>Read\n",
				"<arg_key>file_path</arg_key>\n",
				"<arg_value>a.py</arg_value>\n",
				"</tool_call>\n",
			]
			for p in parts:
				yield ModelChunk(kind="text_delta", text=p)
				await asyncio.sleep(0.02)
			await asyncio.sleep(0.15)
			self.stream_ended_at = time.monotonic()
			return
		yield ModelChunk(kind="text_delta", text="done")


@pytest.mark.asyncio
async def test_xml_stream_early_starts_before_stream_ends(monkeypatch):
	monkeypatch.delenv("XEYO_EARLY_READONLY_TOOLS", raising=False)
	_XmlReadTool.started = asyncio.Event()
	model = _XmlStreamModel()
	reg = ToolRegistry()
	reg.register(_XmlReadTool())
	# 工作区内 Read 的策略为 ALLOW
	store = MessageStore([user_message("read")])
	started_at: float | None = None

	async def _watch():
		nonlocal started_at
		await _XmlReadTool.started.wait()
		started_at = time.monotonic()

	watcher = asyncio.create_task(_watch())
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
	await watcher
	assert model.stream_ended_at is not None
	assert started_at is not None
	assert started_at < model.stream_ended_at


# ---------------------------------------------------------------------------
# 队列唤醒：快速工具后不再垫 0.25s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_tool_batch_does_not_pad_quarter_second(monkeypatch):
	monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "0")

	class _Fast:
		def __init__(self) -> None:
			self._turn = 0

		async def stream(self, messages, tools, abort):
			self._turn += 1
			if self._turn == 1:
				yield ModelChunk(
					kind="tool_use",
					tool_use=ToolUse(id="e1", name="echo", input={"text": "x"}),
				)
				return
			yield ModelChunk(kind="text_delta", text="done")

	reg = ToolRegistry()
	reg.register(EchoTool())
	store = MessageStore([user_message("go")])
	t0 = time.monotonic()
	async for _ in query_loop(
		store=store,
		model=_Fast(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		pass
	elapsed = time.monotonic() - t0
	# 旧路径工具结束后最多空转 0.25s；新路径应明显更短
	assert elapsed < 0.35
