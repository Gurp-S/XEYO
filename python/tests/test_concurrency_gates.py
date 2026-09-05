"""T39 并发闸回归测试：引擎内互斥、TurnRunner 双闸/线程安全读、命名去混淆。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from engine.query_engine import QueryEngine
from engine.turn_runner import TurnRunner
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


class _DummyModel:
	"""不会被真正调用的模型桩（submit 在首个事件后即被 close）。"""

	async def stream(self, messages: list[dict], tools: list[dict], abort: Any) -> AsyncIterator[Any]:  # noqa: ANN001
		raise AssertionError("model should not be reached in these tests")
		yield  # pragma: no cover — make this an async generator


def _make_engine() -> QueryEngine:
	reg = ToolRegistry()
	reg.register(EchoTool())
	return QueryEngine(
		{
			"cwd": ".",
			"tools": reg,
			"model_client": _DummyModel(),  # type: ignore[typeddict-item]
			"max_turns": 4,
		}
	)


# ---------- QueryEngine 引擎内互斥（T39 防御纵深） ----------


@pytest.mark.asyncio
async def test_query_engine_rejects_concurrent_submit() -> None:
	eng = _make_engine()
	eng._turn_active = True
	agen = eng.submit("hi")
	with pytest.raises(RuntimeError, match="busy"):
		await agen.__anext__()
	await agen.aclose()


@pytest.mark.asyncio
async def test_query_engine_close_clears_flag() -> None:
	eng = _make_engine()
	agen = eng.submit("hi")
	try:
		first = await agen.__anext__()
		assert first is not None  # 首个事件（TaskStateEvent）后挂起
	finally:
		await agen.aclose()
	assert eng._turn_active is False


# ---------- TurnRunner：双闸 + 线程锁快照 ----------


class _StubPool:
	def try_begin(self, session_id: str) -> int | None:
		return 1

	def end(self, session_id: str, lease_id: int | None = None) -> None:
		return None

	def touch_busy(self, session_id: str) -> None:
		return None


async def _producer() -> AsyncIterator[tuple[int, bytes, str]]:
	yield (1, b"{}", "state")
	await asyncio.sleep(0.08)
	yield (2, b"{}", "state")


@pytest.mark.asyncio
async def test_turn_runner_double_start_rejected(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	runner = TurnRunner(_StubPool())
	tid = await runner.start(
		session_id="s1",
		lease_id=1,
		model="m",
		goal_text="",
		user_message_id="u1",
		producer=_producer,
	)
	assert tid
	assert runner.is_running("s1")
	with pytest.raises(RuntimeError, match="already running"):
		await runner.start(
			session_id="s1",
			lease_id=2,
			model="m",
			goal_text="",
			user_message_id="u2",
			producer=_producer,
		)
	assert await runner.wait_done("s1", timeout=5)
	assert not runner.is_running("s1")
	# 终态后可再次启动
	tid2 = await runner.start(
		session_id="s1",
		lease_id=3,
		model="m",
		goal_text="",
		user_message_id="u3",
		producer=_producer,
	)
	assert tid2
	await runner.wait_done("s1", timeout=5)


@pytest.mark.asyncio
async def test_turn_runner_terminal_state_visible(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	runner = TurnRunner(_StubPool())
	await runner.start(
		session_id="s2",
		lease_id=1,
		model="m",
		goal_text="",
		user_message_id="u1",
		producer=_producer,
	)
	await runner.wait_done("s2", timeout=5)
	pub = runner.get_public("s2")
	assert pub is not None
	assert pub.status in {"succeeded", "failed", "stopped"}
	assert not runner.is_running("s2")


# ---------- 命名去混淆 + InboundQueue 无锁化 ----------


def test_rewind_process_lock_alias_disambiguation() -> None:
	from engine.workspace_lock import WorkspaceLock as EngineWorkspaceLock
	from rewind.locks import ProcessWorkspaceLock, WorkspaceLock as RewindAlias

	assert RewindAlias is ProcessWorkspaceLock
	# 同名但不同物：rewind 版是进程内锁，engine 版是跨进程文件锁。
	assert EngineWorkspaceLock is not ProcessWorkspaceLock


def test_inbound_queue_is_lockfree() -> None:
	from channels.filehelper.inbound_queue import InboundQueue

	q = InboundQueue()
	assert not hasattr(q, "_lock")  # T39：未使用过的锁已删除
	assert q.push("a") == 1
	assert q.pop() == "a"
	assert q.pop() is None
