"""Turn detach / reattach / resume cue / TurnSnapshot."""

from __future__ import annotations

import asyncio
import json
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
	ChatCompletionRequest,
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
	assert "Resume state" in prompt
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
async def test_subscribe_clamps_cursor_belonging_to_earlier_turn():
	"""event_id 每 turn 从 1 重排，GUI 游标却是会话级 ⇒ 越界游标必须归零重放。

	不钳制时重放为空、端点再补 [DONE] ⇒ 刷新后回复"整条消失且显示已完成"。
	"""

	class _FakePool:
		def end(self, session_id: str, lease_id: int | None = None) -> None:
			_ = (session_id, lease_id)

	runner = TurnRunner(_FakePool())

	async def producer():
		yield (1, b'data: {"n":1}\n\n', "delta")
		yield (2, b'data: {"n":2}\n\n', "delta")
		yield (3, b"data: [DONE]\n\n", "done")

	await runner.start(
		session_id="s2",
		lease_id=1,
		model="m",
		goal_text="g",
		user_message_id="u1",
		producer=producer,
		turn_id="t2",
	)
	await runner.wait_done("s2", timeout=2.0)

	stale: list[bytes] = []
	async for fr in runner.subscribe("s2", cursor=9_000):
		stale.append(fr)
	assert len(stale) == 3, f"越界游标应重放本轮全部帧，实得 {stale}"

	tail: list[bytes] = []
	async for fr in runner.subscribe("s2", cursor=2):
		tail.append(fr)
	assert tail == [b"data: [DONE]\n\n"], "轮内游标仍应精确去重"


def test_chat_request_accepts_anthropic_provider():
	"""GUI 把 anthropic 当一等 provider（settingsStore ProviderId），
	请求体 Literal 少它 ⇒ 每轮 422，handler 都进不去。"""
	req = ChatCompletionRequest(model="claude", provider="anthropic")
	assert req.provider == "anthropic"


@pytest.fixture()
def tmp_audit(tmp_path):
	"""把默认审计单例钉到 tmp：缺口帧必须同时留下可回读的证据行。"""
	import audit.log as audit_mod
	from audit.log import AuditLog, reset_default_audit_log

	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log
	yield log
	reset_default_audit_log()


@pytest.mark.asyncio
async def test_subscribe_announces_gap_when_ring_evicted_frames(monkeypatch, tmp_audit):
	"""环形缓冲挤掉旧帧后，重放段是不完整的：必须先发 stream_gap，
	否则前端会把缺段当完整内容提交（正文中间少一截且无人知道）。"""
	from engine import turn_runner as tr

	monkeypatch.setattr(tr, "_MAX_BUFFERED_FRAMES", 1)

	class _FakePool:
		def end(self, session_id: str, lease_id: int | None = None) -> None:
			_ = (session_id, lease_id)

	runner = TurnRunner(_FakePool())

	async def producer():
		for n in range(1, 4):
			yield (n, f'data: {{"n":{n}}}\n\n'.encode(), "delta")
		yield (4, b"data: [DONE]\n\n", "done")

	await runner.start(
		session_id="s3",
		lease_id=1,
		model="m",
		goal_text="g",
		user_message_id="u1",
		producer=producer,
		turn_id="t3",
	)
	await runner.wait_done("s3", timeout=2.0)

	frames: list[bytes] = []
	async for fr in runner.subscribe("s3", cursor=0):
		frames.append(fr)

	gap = next(
		(f for f in frames if b"stream_gap" in f),
		None,
	)
	assert gap is not None, f"丢过程序却没人告知：{frames}"
	payload = json.loads(gap.decode().removeprefix("data: ").strip())["xy"]
	assert payload["type"] == "stream_gap"
	assert payload["dropped_through_event_id"] >= 1
	assert payload["first_available_event_id"] >= payload["dropped_through_event_id"] + 1

	# 帧只活在这次连接里：诊断层要按轮次回读"界面缺过一段"，必须另有一条审计行。
	# 没有它，wire_gap 的 sse_gui 分支在生产里永远不命中（曾经读的是一个从未被写的字段）。
	rows = [r for r in tmp_audit.read_all() if str(r.get("kind")) == "stream.gap"]
	assert rows, "缺口帧发出去了却没留证据行"
	gap_row = rows[0]
	assert gap_row.get("session_id") == "s3"
	assert gap_row.get("turn_id") == "t3"
	assert int(gap_row.get("dropped_through_event_id") or 0) >= 1
	assert int(gap_row.get("first_available_event_id") or 0) > int(gap_row.get("dropped_through_event_id") or 0)


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
	"""慢订阅者不被摘除：溢出只丢它自己的队首，并且必须带着 stream_gap + _END 及时收流。

	两代缺陷都在这里钉住：
	① 旧写法 QueueFull 即把订阅者标死移除 ⇒ 尾部帧与 [DONE] 永远到不了，
	   实测一枪 700 帧只收到 639 帧就无终止标记断流；
	② 就算补发 _END，"活着但慢"的连接被掐死本身就是把截断当完整提交。
	现在每连接额度 4096（环形缓冲才 4000 帧），真溢出丢队首并给这条连接
	发 stream_gap，由界面改用服务端 transcript 收尾。
	"""
	import time as _time

	import engine.turn_runner as _tr

	class _Pool:
		def end(self, session_id: str, lease_id: int | None = None) -> None:
			pass

	runner = TurnRunner(_Pool())
	total = 5000
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
		# 等泵跑完再开始读：溢出丢帧那一支要确定性走到，不靠调度时序。
		await asyncio.wait_for(runner._turns["s3"].done.wait(), timeout=20.0)
		await asyncio.sleep(0.05)  # 让 pump 把 gap 与 _END 塞完
		frames = [f async for f in agen if f is not None]
		got = len(frames)
		elapsed = _time.monotonic() - t0

		assert got > 4000, (
			f"只收到 {got} 帧：慢订阅者又被在旧额度上掐死了"
		)
		assert got < total + 2, "溢出必须真的发生（否则这档没走到丢帧支）"
		assert any(b"[DONE]" in f for f in frames), "尾部终止帧必须到达"
		assert any(b"stream_gap" in f for f in frames), (
			"丢了帧就要把洞交给这条连接，否则缺段会被当完整内容提交"
		)
		assert elapsed < 1.5, (
			f"收流耗时 {elapsed:.2f}s：疑似没补发 _END，退化为等心跳兜底"
		)
		await runner.wait_done("s3", timeout=2.0)
	finally:
		_tr._SUBSCRIBE_TICK_S = old_tick
