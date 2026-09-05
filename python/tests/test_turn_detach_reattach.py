"""Turn detach / reattach / resume cue / TurnSnapshot."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.turn_snapshot import (
	TurnSnapshot,
	flush,
	hydrate,
	list_recoverable,
	mark_crashed_as_recovery,
)
from engine.turn_runner import TurnRunner
from server.routers.chat import (
	ChatMessage,
	_build_enriched_resume_prompt,
	_is_multi_agent_resume_cue,
	_previous_user_goal,
)


def test_resume_cue_helpers():
	assert _is_multi_agent_resume_cue("继续")
	assert _is_multi_agent_resume_cue("continue")
	assert not _is_multi_agent_resume_cue("继续把侧边栏改掉")
	msgs = [
		ChatMessage(role="user", content="实现断点续跑"),
		ChatMessage(role="assistant", content="好的"),
		ChatMessage(role="user", content="继续"),
	]
	assert _previous_user_goal(msgs) == "实现断点续跑"
	prompt = _build_enriched_resume_prompt(
		user_cue="继续",
		goal="实现断点续跑",
		todos=[{"content": "写 TurnRunner", "status": "in_progress"}],
		stop_reason="user_stop",
	)
	assert "[Resume]" in prompt
	assert "实现断点续跑" in prompt
	assert "写 TurnRunner" in prompt


def test_turn_snapshot_roundtrip(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	snap = TurnSnapshot(
		session_id="sess_test",
		turn_id="abc",
		status="running",
		goal_text="do thing",
		last_event_id=7,
	)
	flush(snap)
	loaded = hydrate("sess_test")
	assert loaded is not None
	assert loaded.turn_id == "abc"
	assert loaded.status == "running"
	assert loaded.last_event_id == 7
	crashed = mark_crashed_as_recovery(loaded)
	assert crashed.status == "recovery_required"
	rows = list_recoverable()
	assert any(r.session_id == "sess_test" for r in rows)


@pytest.mark.asyncio
async def test_turn_runner_detach_subscribe():
	class _FakePool:
		def __init__(self) -> None:
			self.ended: list[tuple[str, int]] = []

		def end(self, session_id: str, lease_id: int | None = None) -> None:
			self.ended.append((session_id, int(lease_id or 0)))

	pool = _FakePool()
	runner = TurnRunner(pool)

	async def producer():
		yield (1, b'data: {"n":1}\n\n', "delta")
		await asyncio.sleep(0.05)
		yield (2, b'data: {"n":2}\n\n', "delta")
		yield (3, b"data: [DONE]\n\n", "done")

	await runner.start(
		session_id="s1",
		lease_id=42,
		model="m",
		goal_text="g",
		user_message_id="u1",
		producer=producer,
		turn_id="t1",
	)
	assert runner.is_running("s1")
	runner.note_client_disconnect("s1", "t1")  # must NOT stop turn
	frames: list[bytes] = []
	async for fr in runner.subscribe("s1", cursor=0):
		frames.append(fr)
	assert len(frames) >= 2
	await runner.wait_done("s1", timeout=2.0)
	assert not runner.is_running("s1")
	assert pool.ended == [("s1", 42)]
	pub = runner.get_public("s1")
	assert pub is not None
	assert pub.status in {"succeeded", "failed", "stopped"}


@pytest.mark.asyncio
async def test_turn_runner_cursor_skips_replayed():
	class _Pool:
		def end(self, session_id: str, lease_id: int | None = None) -> None:
			pass

	runner = TurnRunner(_Pool())

	async def producer():
		for i in range(1, 4):
			yield (i, f"data: {i}\n\n".encode(), "delta")
		yield (4, b"data: [DONE]\n\n", "done")

	await runner.start(
		session_id="s2",
		lease_id=1,
		model="m",
		goal_text="g",
		user_message_id="",
		producer=producer,
		turn_id="t2",
	)
	await runner.wait_done("s2", timeout=2.0)
	got: list[bytes] = []
	async for fr in runner.subscribe("s2", cursor=2):
		got.append(fr)
	assert all(b"data: 1" not in fr and b"data: 2" not in fr for fr in got)
	assert any(b"data: 3" in fr or b"[DONE]" in fr for fr in got)


@pytest.mark.asyncio
async def test_dead_slow_subscriber_terminates_with_end_sentinel():
	"""慢订阅者挤爆订阅队列（QueueFull 标死）后必须及时收到 _END 收流。

	修复前：标死队列被移除但不补 _END，subscribe() 只能等心跳兜底（拖满一个
	tick）甚至永久悬死；修复后 pump 腾格补发 _END，消费方立即收到流结束。
	"""
	import time as _time

	import engine.turn_runner as _tr

	class _Pool:
		def end(self, session_id: str, lease_id: int | None = None) -> None:
			pass

	runner = TurnRunner(_Pool())
	total = 2000
	started = asyncio.Event()

	async def producer():
		await started.wait()  # 等订阅挂好再产帧，保证全部帧走 live 队列
		for i in range(1, total + 1):
			await asyncio.sleep(0)
			yield (i, f"data: {i}\n\n".encode(), "delta")
		yield (total + 1, b"data: [DONE]\n\n", "done")

	await runner.start(
		session_id="s3",
		lease_id=7,
		model="m",
		goal_text="",
		user_message_id="",
		producer=producer,
		turn_id="t3",
	)

	old_tick = _tr._SUBSCRIBE_TICK_S
	_tr._SUBSCRIBE_TICK_S = 1.0
	try:
		agen = runner.subscribe("s3", cursor=0)
		first_task = asyncio.ensure_future(agen.__anext__())
		await asyncio.sleep(0.01)  # 让 subscribe 完成挂载并进入 q.get 等待
		assert runner._turns["s3"].subscribers, "订阅尚未挂载"
		started.set()

		got = 0
		t0 = _time.monotonic()
		first = await asyncio.wait_for(first_task, timeout=2.0)
		assert isinstance(first, bytes)
		await asyncio.sleep(0.1)  # 慢消费者停顿：q 被填满 → QueueFull 标死
		async for _fr in agen:
			got += 1
		elapsed = _time.monotonic() - t0

		assert got < total, "溢出标死后应丢帧收流"
		assert elapsed < 0.8, (
			f"标死订阅者收流耗时 {elapsed:.2f}s：疑似未补发 _END，退化为等心跳兜底"
		)
		await runner.wait_done("s3", timeout=2.0)
	finally:
		_tr._SUBSCRIBE_TICK_S = old_tick
