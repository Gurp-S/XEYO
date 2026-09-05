"""主循环 P2：配对修复仅入口、围栏增量、observe 延后。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from memory.working import WorkingSnapshot
from model.chunks import ModelChunk
from model.fake import FakeModelClient
from msgtypes.events import FinalEvent
from msgtypes.message import ToolUse, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from prompt.fence import is_fenced_tool_output
from session.message_store import MessageStore
from tools.base_tool import ToolResult
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


class _SlowEcho(EchoTool):
	async def execute(self, input: dict, abort) -> ToolResult:
		abort.raise_if_aborted()
		await asyncio.sleep(0.05)
		return ToolResult(content=str(input.get("text", "ok-body")))


class _TwoShotModel:
	"""首轮 tool_use，次轮文本结束；并校验投影里的 tool_result 已围栏。"""

	def __init__(self) -> None:
		self.n = 0
		self.last_usage = {"prompt_tokens": 10, "completion_tokens": 2}
		self.last_context_tokens = 10
		self.context_limit = 128_000

	async def stream(self, messages, tools, abort):
		del tools
		abort.raise_if_aborted()
		self.n += 1
		if self.n == 1:
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(id="t1", name="echo", input={"text": "ok-body"}),
			)
			return
		for m in messages:
			if not isinstance(m, dict):
				continue
			content = m.get("content")
			if not isinstance(content, list):
				continue
			for b in content:
				if isinstance(b, dict) and b.get("type") == "tool_result":
					assert is_fenced_tool_output(str(b.get("content") or ""))
		yield ModelChunk(kind="text_delta", text="done")


@pytest.mark.asyncio
async def test_repair_runs_once_per_submit(monkeypatch):
	calls = {"n": 0}
	import engine.query_loop as ql

	orig = ql._repair_unpaired_tool_calls

	def wrapped(store, reason="aborted"):
		calls["n"] += 1
		return orig(store, reason)

	monkeypatch.setattr(ql, "_repair_unpaired_tool_calls", wrapped)

	reg = ToolRegistry()
	reg.register(EchoTool())
	events = []
	async for ev in query_loop(
		store=MessageStore([user_message("echo:a")]),
		model=FakeModelClient(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=6),
	):
		events.append(ev)
	assert any(isinstance(e, FinalEvent) for e in events)
	assert calls["n"] == 1


@pytest.mark.asyncio
async def test_fences_in_projection_not_store_and_incremental(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="project")
	mem_switch.reset("XEYO_C2_GATE")
	reg = ToolRegistry()
	reg.register(_SlowEcho())
	store = MessageStore([user_message("read")])
	snap = WorkingSnapshot()
	events = []
	async for ev in query_loop(
		store=store,
		model=_TwoShotModel(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
		working=snap,
	):
		events.append(ev)
	assert any(isinstance(e, FinalEvent) for e in events)
	for m in store.items:
		if m.role != "tool":
			continue
		raw = ""
		if isinstance(m.content, list):
			for b in m.content:
				if isinstance(b, dict) and b.get("type") == "tool_result":
					raw = str(b.get("content") or "")
		assert raw == "ok-body"
		assert not is_fenced_tool_output(raw)
	assert snap.proj_cache is not None
	cached = snap.proj_cache[4]
	fenced_any = False
	for m in cached:
		content = m.get("content") if isinstance(m, dict) else None
		if not isinstance(content, list):
			continue
		for b in content:
			if isinstance(b, dict) and b.get("type") == "tool_result":
				if is_fenced_tool_output(str(b.get("content") or "")):
					fenced_any = True
	assert fenced_any


@pytest.mark.asyncio
async def test_observe_overlaps_tools(monkeypatch):
	"""observe 丢到后台后，工具仍能在其完成前启动（不挡关键路径）。"""
	import memory.observe as obs

	started = {"t": None}
	entered_tool = {"t": None}

	orig = obs.observe_shot

	def slow_observe(*a, **k):
		started["t"] = time.perf_counter()
		time.sleep(0.08)
		return orig(*a, **k)

	monkeypatch.setattr(obs, "observe_shot", slow_observe)

	class _MarkEcho(EchoTool):
		async def execute(self, input: dict, abort) -> ToolResult:
			abort.raise_if_aborted()
			entered_tool["t"] = time.perf_counter()
			await asyncio.sleep(0.05)
			return ToolResult(content=str(input.get("text", "x")))

	class _Model:
		n = 0
		last_usage = {"prompt_tokens": 5, "completion_tokens": 1}
		last_context_tokens = 5
		context_limit = 1000

		async def stream(self, messages, tools, abort):
			del messages, tools
			abort.raise_if_aborted()
			type(self).n += 1
			if type(self).n == 1:
				yield ModelChunk(
					kind="tool_use",
					tool_use=ToolUse(id="m1", name="echo", input={"text": "1"}),
				)
				return
			yield ModelChunk(kind="text_delta", text="fin")

	reg = ToolRegistry()
	reg.register(_MarkEcho())
	events = []
	async for ev in query_loop(
		store=MessageStore([user_message("go")]),
		model=_Model(),
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
		working=WorkingSnapshot(),
	):
		events.append(ev)
	assert any(isinstance(e, FinalEvent) for e in events)
	assert started["t"] is not None and entered_tool["t"] is not None
	# early 只读在 stream 期就启动，必然早于 observe；至少证明 observe 没挡住工具
	assert entered_tool["t"] < started["t"] + 0.07
