"""主循环三刀：T_now 尾插、Ask/Permission 即挂起并行、Before 与 stream 重叠。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.permission_coordinator import PermissionCoordinator
from engine.query_loop import _attach_turn_context, query_loop
from engine.task_state import SessionTaskState
from model.chunks import ModelChunk
from msgtypes.events import (
	AskUserPendingEvent,
	FinalEvent,
	PermissionPendingEvent,
	PermissionResolvedEvent,
	ToolResultEvent,
)
from msgtypes.message import ToolUse, user_message
from permissions.ask_store import default_ask_store
from permissions.policy import set_permission_mode
from permissions.store import PendingPermissionStore
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from prompt.turn_context import append_text_blocks_to_last_user
from session.message_store import MessageStore
from tools.ask_user_question_tool import AskUserQuestionTool, ASK_USER_TOOL_NAME
from tools.base_tool import ToolResult
from tools.echo import EchoTool
from tools.file_write_tool.file_write_tool import FileWriteTool
from tools.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# 第一刀：T_now
# ---------------------------------------------------------------------------


def test_append_blocks_after_tool_result_inserts_projection_user():
	msgs = [
		{"role": "user", "content": "hi"},
		{"role": "assistant", "content": "…"},
		{"role": "tool", "name": "Grep", "tool_call_id": "c1", "content": "hits"},
	]
	out = append_text_blocks_to_last_user(msgs, ["# Wrap-up required\nok"])
	assert msgs[-1]["role"] == "tool"  # store / 投影入参未改
	assert out[-1]["role"] == "user"
	assert out[-1]["content"][0]["text"].startswith("# Wrap-up")
	assert len(out) == len(msgs) + 1


def test_attach_turn_context_after_tool_includes_wrap_up_and_notice(monkeypatch):
	monkeypatch.setattr(
		"memory.runtime._append_memory_index",
		lambda msgs: msgs,
	)
	projected = [
		{"role": "user", "content": "task"},
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": "1", "name": "Grep"}],
		},
		{"role": "tool", "tool_call_id": "1", "name": "Grep", "content": "x"},
	]
	out = _attach_turn_context(
		projected,
		approved_plan="do the thing",
		forced_wrap_up=True,
		runtime_notice="工具使用已经过多，请检查是否已经实现任务。",
		include_memory_index=False,
	)
	assert out[-1]["role"] == "user"
	# 声道无关：legacy=text 块；env_channel（方案A）=伪对 tool_result 正文
	joined = "\n".join(
		str(b.get("text") or b.get("content") or "")
		for b in out[-1]["content"]
		if isinstance(b, dict)
	)
	assert "Approved plan" in joined
	assert "Wrap-up required" in joined
	assert "Runtime budget notice" in joined


def test_memory_index_appends_after_tool(monkeypatch):
	monkeypatch.setattr(
		"memory.memdir.load_index_text",
		lambda wsid: "[feedback] keep-me -> topics/x.md",
	)
	from memory.runtime import _append_memory_index

	msgs = [
		{"role": "user", "content": "hi"},
		{"role": "tool", "name": "Read", "tool_call_id": "t", "content": "body"},
	]
	out = _append_memory_index(msgs)
	assert out[-1]["role"] == "user"
	joined = "\n".join(b["text"] for b in out[-1]["content"])
	assert "Memory index" in joined
	# P0 一行化：只发计数摘要，条目标题/路径不进投影（防弱模型把索引当任务）
	assert "entries" in joined
	assert '<memory_index readonly="true">' in joined
	assert "keep-me" not in joined
	assert "topics/" not in joined


# ---------------------------------------------------------------------------
# 第二刀：兄弟任务运行中等待 pending yields；并行等待
# ---------------------------------------------------------------------------


class _SlowBash:
	name = "Bash"
	started = asyncio.Event()
	release = asyncio.Event()

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict:
		return {
			"name": "Bash",
			"description": "slow bash",
			"input_schema": {"type": "object", "properties": {"command": {}}},
		}

	async def execute(self, input: dict, abort: AbortController) -> ToolResult:
		_SlowBash.started.set()
		await _SlowBash.release.wait()
		return ToolResult(content="bash done")


class _WriteThenBashModel:
	"""一轮：Write + Bash；二轮：纯文本。"""

	def __init__(self) -> None:
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
					id="call_write",
					name="Write",
					input={"file_path": "a.txt", "content": "x\n"},
				),
			)
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id="call_bash",
					name="Bash",
					input={"command": "echo hi"},
				),
			)
			return
		yield ModelChunk(kind="text_delta", text="done")


@pytest.mark.asyncio
async def test_permission_pending_yields_while_sibling_bash_runs(
	tmp_path, monkeypatch
) -> None:
	monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "0")
	set_permission_mode("always")
	_SlowBash.started = asyncio.Event()
	_SlowBash.release = asyncio.Event()

	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(FileWriteTool(cwd=str(tmp_path)))
	reg.register(_SlowBash())
	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=SessionTaskState(session_id="s"),
		session_id="s",
		turn_id="t1",
	)
	store = MessageStore([user_message("write then bash")])
	model = _WriteThenBashModel()
	events: list[Any] = []
	pending_at: float | None = None
	bash_started_at: float | None = None

	async def _drive() -> None:
		nonlocal pending_at, bash_started_at
		async for ev in query_loop(
			store=store,
			model=model,
			tools=reg,
			prompt=PromptAssembler(),
			system_prompt=DEFAULT_SYSTEM,
			abort=AbortController(),
			budget=BudgetTracker(max_turns=4, max_tool_calling=8),
			coordinator=coord,
		):
			events.append(ev)
			if isinstance(ev, PermissionPendingEvent):
				if pending_at is None:
					pending_at = time.monotonic()
				# always 模式下该批首个工具（Write）挂起；Bash 在写批放行后直接
				# 执行（不产生独立 pending 事件）。此处先把控制交回事件循环，让
				# run_tools_partitioned 推进到 Bash（execute 首行 set started），
				# 再释放 release —— 否则 Bash 在 execute 内 await release 而自锁。
				if not _SlowBash.started.is_set():
					await asyncio.wait_for(_SlowBash.started.wait(), timeout=3.0)
				_SlowBash.release.set()
				if bash_started_at is None:
					bash_started_at = time.monotonic()
				assert coord.resolve(ev.request_id, True, actor="test")
			if bash_started_at is None and _SlowBash.started.is_set():
				bash_started_at = time.monotonic()

	await asyncio.wait_for(_drive(), timeout=8.0)
	assert pending_at is not None
	assert bash_started_at is not None
	assert bash_started_at >= pending_at  # 串行语义：Bash 不早于 Write 挂起
	assert any(isinstance(e, PermissionResolvedEvent) for e in events)
	assert any(
		isinstance(e, ToolResultEvent) and e.name == "Write" and not e.is_error
		for e in events
	)
	assert any(
		isinstance(e, ToolResultEvent) and e.name == "Bash" and not e.is_error
		for e in events
	)
	assert any(isinstance(e, FinalEvent) for e in events)
	assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x\n"


class _TwinAskModel:
	def __init__(self) -> None:
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
					id="ask1",
					name=ASK_USER_TOOL_NAME,
					input={"question": "Q1?", "options": ["a"]},
				),
			)
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id="ask2",
					name=ASK_USER_TOOL_NAME,
					input={"question": "Q2?", "options": ["b"]},
				),
			)
			return
		yield ModelChunk(kind="text_delta", text="answered")


@pytest.mark.asyncio
async def test_two_asks_pending_before_either_resolved(tmp_path) -> None:
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(AskUserQuestionTool())
	coord = PermissionCoordinator(
		store=PendingPermissionStore(),
		task_state=SessionTaskState(session_id="s"),
		session_id="s",
		turn_id="t1",
	)
	store = MessageStore([user_message("ask twice")])
	pending_ids: list[str] = []

	async def _drive() -> None:
		async for ev in query_loop(
			store=store,
			model=_TwinAskModel(),
			tools=reg,
			prompt=PromptAssembler(),
			system_prompt=DEFAULT_SYSTEM,
			abort=AbortController(),
			budget=BudgetTracker(max_turns=4, max_tool_calling=8),
			coordinator=coord,
		):
			if isinstance(ev, AskUserPendingEvent):
				pending_ids.append(ev.request_id)
				if len(pending_ids) == 2:
					ask_store = default_ask_store()
					assert ask_store.resolve_answer(pending_ids[0], "a", actor="t")
					assert ask_store.resolve_answer(pending_ids[1], "b", actor="t")

	await asyncio.wait_for(_drive(), timeout=5.0)
	assert len(pending_ids) == 2
	assert pending_ids[0] != pending_ids[1]


# ---------------------------------------------------------------------------
# 第三刀：Before 与首个流重叠；写入在闸口等待
# ---------------------------------------------------------------------------


class _WriteModel:
	def __init__(self) -> None:
		self._turn = 0
		self.first_stream_at: float | None = None

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		abort.raise_if_aborted()
		self._turn += 1
		if self._turn == 1:
			self.first_stream_at = time.monotonic()
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id="w1",
					name="Write",
					input={"file_path": "b.txt", "content": "y\n"},
				),
			)
			return
		yield ModelChunk(kind="text_delta", text="wrote")


@pytest.mark.asyncio
async def test_ensure_before_blocks_write_until_ready(tmp_path) -> None:
	set_permission_mode("never")  # Write ALLOW without ASK for this test
	gate_opened = asyncio.Event()
	write_started = asyncio.Event()
	model = _WriteModel()

	class _TrackingWrite(FileWriteTool):
		async def execute(self, input: dict, abort: AbortController) -> ToolResult:
			write_started.set()
			assert gate_opened.is_set()
			return await super().execute(input, abort)

	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(_TrackingWrite(cwd=str(tmp_path)))

	async def _gate() -> None:
		await asyncio.sleep(0.15)
		gate_opened.set()

	def _ensure() -> Any:
		return _gate()

	store = MessageStore([user_message("write")])
	t0 = time.monotonic()
	async for _ in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4, max_tool_calling=8),
		ensure_before=_ensure,
	):
		pass
	assert model.first_stream_at is not None
	# 首轮 stream 在 gate 打开前就已开始（重叠）
	assert model.first_stream_at < t0 + 0.15
	assert write_started.is_set()
	assert gate_opened.is_set()
	assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "y\n"


@pytest.mark.asyncio
async def test_ensure_before_failure_blocks_write_not_text(tmp_path) -> None:
	set_permission_mode("never")
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(FileWriteTool(cwd=str(tmp_path)))
	model = _WriteModel()

	def _ensure() -> Any:
		async def _fail() -> None:
			raise RuntimeError("snapshot boom")

		return _fail()

	store = MessageStore([user_message("write")])
	results: list[ToolResultEvent] = []
	async for ev in query_loop(
		store=store,
		model=model,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4, max_tool_calling=8),
		ensure_before=_ensure,
	):
		if isinstance(ev, ToolResultEvent):
			results.append(ev)
	assert results
	assert results[0].is_error
	assert "before_snapshot" in results[0].output
	assert not (tmp_path / "b.txt").exists()


@pytest.mark.asyncio
async def test_query_engine_before_overlaps_stream(tmp_path, monkeypatch) -> None:
	"""submit_message 不在首轮 stream 前 await Before。"""
	from engine.query_engine import QueryEngine

	set_permission_mode("never")
	snap_started = asyncio.Event()
	stream_seen_during_snap = asyncio.Event()
	stream_started = asyncio.Event()

	def _slow_snap(cwd: str, session_id: str, phase: str) -> str:
		if phase == "Before":
			snap_started.set()
			# 在线程里等 stream 真正开始，证明与 Before 重叠（最多 2s）
			deadline = time.monotonic() + 2.0
			while time.monotonic() < deadline:
				if stream_started.is_set():
					stream_seen_during_snap.set()
					break
				time.sleep(0.01)
			return "commit-before"
		return "commit-after"

	monkeypatch.setattr(
		"engine.query_engine._rewind_take_snapshot",
		_slow_snap,
	)

	class _M:
		async def stream(self, messages, tools, abort):
			stream_started.set()
			await asyncio.sleep(0.05)
			yield ModelChunk(kind="text_delta", text="ok")

	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(EchoTool())
	eng = QueryEngine(
		{
			"cwd": str(tmp_path),
			"tools": reg,
			"model_client": _M(),
			"rewind_enabled": True,
			"max_turns": 2,
		}
	)
	texts: list[str] = []
	async for ev in eng.submit_message("hi"):
		if getattr(ev, "type", None) == "assistant_delta":
			texts.append(getattr(ev, "text", "") or "")
	assert "".join(texts) == "ok"
	assert snap_started.is_set()
	assert stream_started.is_set()
	assert stream_seen_during_snap.is_set()
