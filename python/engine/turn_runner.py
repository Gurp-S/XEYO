"""Detached turn runner — SSE 是订阅者，不是执行租约。

GUI 刷新只断投影流；显式 Stop / interrupt 才杀 turn。
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from contextlib import aclosing
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from collections import deque
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from engine.turn_snapshot import TurnSnapshot, flush as flush_turn, hydrate as hydrate_turn
from engine.turn_event_state import apply_event
from engine.turn_checkpoint import write_checkpoint

_log = logging.getLogger("xeyo.turn_runner")

# 内存 ring：足够刷新后追赶；过大则截断最旧（reattach 仍可从 transcript hydrate）。
_MAX_BUFFERED_FRAMES = 4000
# frames 另设字节上限：tool_result 帧（fence 后）可达数十 KB，按条数截断
# 不足以约束内存（曾有单 turn 缓冲涨到数十 MB 的案例）。
_MAX_BUFFERED_BYTES = 8 * 1024 * 1024
# 终态 turn 的保留上限（按会话数）：超出时最旧的终态 turn 被丢弃——
# 快照已落盘（turn_snapshot），新 turn 启动时也会覆盖。
_MAX_TERMINAL_TURNS = 32

ProducerFn = Callable[[], AsyncIterator[tuple[int, bytes, str]]]
# 产出 (event_id, sse_bytes, kind) 三元组

# 41 号：turn 终态回调槽（settlement）。server 启动时经 set_turn_settlement_listener
# 注册（engine 不 import server，反向注入）；签名 async fn(session_id, final_status,
# stop_reason)，实现必须自包含异常隔离、绝不抛、绝不阻塞 teardown。
_SettlementListener = Optional[Callable[[str, str, str], Awaitable[None]]]
_settlement_listener: _SettlementListener = None
_settled_user_message_id: ContextVar[str] = ContextVar(
	"xeyo_settled_user_message_id", default=""
)


def settled_user_message_id() -> str:
	"""Return the message id attached to this settlement callback context."""
	return _settled_user_message_id.get()


def set_turn_settlement_listener(fn: _SettlementListener) -> None:
	"""注册 turn 终态监听（server lifespan 调用；多次调用覆盖）。"""
	global _settlement_listener
	_settlement_listener = fn


#: 在途 settlement 任务的强引用集合。事件循环对 Task 只持**弱**引用，而
#: 未取回的异常在产品里等于没发生（本仓从不配置 logging handler，
#: "exception was never retrieved" 连 warning 都不会出现）。
_SETTLEMENT_TASKS: set["asyncio.Task[None]"] = set()


def _reap_settlement(task: "asyncio.Task[None]") -> None:
	_SETTLEMENT_TASKS.discard(task)
	if task.cancelled():
		return
	exc = task.exception()
	if exc is not None:
		# 契约是"listener 自隔离异常、绝不抛"。违约必须有声：settlement 承担
		# busy/租约归还等收尾，静默失败会表现成为人看不懂的"会话一直忙"。
		_log.warning(
			"turn settlement listener failed: %s: %s",
			type(exc).__name__,
			exc,
		)


def _spawn_settlement(coro: Awaitable[None]) -> None:
	"""后台跑终态回调：绝不阻塞 teardown，但留强引用并取回异常。"""
	task = asyncio.ensure_future(coro)
	_SETTLEMENT_TASKS.add(task)
	task.add_done_callback(_reap_settlement)


#: 每连接发送缓冲。此前是 512：泵逐帧扇出时"活着但读得慢"的订阅者一满就被摘除标死，
#: 尾部帧和 `[DONE]` 一起消失 ⇒ 界面把截断当完整，或弹"连接中断请重试"要用户重付一枪。
#: 取 4096 是为了让"整段长回复排得下"（环形缓冲本身才 4000 帧），不是性能调参；
#: 真超过它才走记洞丢帧那一支，而洞只属于这一条连接。
_SUBSCRIBER_QUEUE_MAX = 4096


class _SubscriberQueue(asyncio.Queue):
	"""一条连接的有界队列 + 这条连接自己被挤掉的最大事件号。

	洞按连接记：同一回合里别的订阅者可能全帧收过，用 turn 级计数会把它们一起
	判成缺段（虚假 stream_gap ⇒ 白拉一次 transcript、诊断层多一条假证据）。
	"""

	def __init__(self) -> None:
		super().__init__(maxsize=_SUBSCRIBER_QUEUE_MAX)
		self.dropped_through_id = 0


def _fanout(q: _SubscriberQueue, item: Any) -> None:
	"""把一帧（或 ``_END`` 哨兵）塞进这条连接：满了丢自己的队首，绝不摘除订阅者。"""
	while True:
		try:
			q.put_nowait(item)
			return
		except asyncio.QueueFull:
			pass
		try:
			dropped = q.get_nowait()
		except asyncio.QueueEmpty:  # pragma: no cover - 满队列不可能空
			return
		if isinstance(dropped, tuple):
			q.dropped_through_id = max(q.dropped_through_id, int(dropped[0]))


def _stream_gap_frame(
	*, dropped_through_event_id: int, first_available_event_id: int
) -> bytes:
	"""重放侧与扇出侧共用一个 ``stream_gap`` 形状（GUI 的 onStreamGap 只认这一种）。"""
	gap = json.dumps(
		{
			"xy": {
				"type": "stream_gap",
				"dropped_through_event_id": int(dropped_through_event_id),
				"first_available_event_id": int(first_available_event_id),
			}
		},
		ensure_ascii=False,
	)
	return f"data: {gap}\n\n".encode("utf-8")


@dataclass
class TurnPublic:
	session_id: str
	turn_id: str
	status: str
	last_event_id: int
	stop_reason: str = ""
	goal_text: str = ""
	model: str = ""
	waiting_permission: bool = False
	revision: int = 0


@dataclass
class _DetachedTurn:
	session_id: str
	turn_id: str
	lease_id: int
	model: str
	goal_text: str
	user_message_id: str
	status: str = "running"
	stop_reason: str = ""
	waiting_permission: bool = False
	revision: int = 0
	last_event_id: int = 0
	frames: deque[tuple[int, bytes, str]] = field(default_factory=deque)
	outcome: str = ""
	outcome_reason: str = ""
	last_checkpoint_at: float = 0.0
	subscribers: list[_SubscriberQueue] = field(default_factory=list)
	task: asyncio.Task[None] | None = None
	done: asyncio.Event = field(default_factory=asyncio.Event)
	finalizing: bool = False
	started_at: float = field(default_factory=time.monotonic)
	incomplete_tools: list[str] = field(default_factory=list)
	active_agents: list[str] = field(default_factory=list)
	frames_bytes: int = 0
	# 已被环形缓冲挤掉的最大事件号（0 = 没挤过）。重放只能给还留着的帧，
	# 客户端必须知道中间有洞——否则缺段会被当成完整内容提交。
	dropped_through_id: int = 0


def _record_stream_gap(turn: _DetachedTurn, dropped: int, first_available: int) -> None:
	try:
		from audit.log import default_audit_log
		default_audit_log().record(
			"stream.gap", session_id=turn.session_id, turn_id=turn.turn_id,
			dropped_through_event_id=int(dropped), first_available_event_id=first_available,
		)
	except Exception:  # Observability must not interrupt replay.
		_log.debug("stream.gap audit failed", exc_info=True)


_END = object()
# 订阅心跳：live 队列静默多久后向调用方 yield None（调用方发 SSE ping）。
# 必须远小于 FE idle watchdog（60s）。
_SUBSCRIBE_TICK_S = 12.0


class TurnRunner:
	"""进程内 per-session 至多一个活跃 detached turn。"""

	def __init__(self, pool: Any) -> None:
		self._pool = pool
		self._turns: dict[str, _DetachedTurn] = {}
		# T39：跨线程读防护。sync 路由（slash/interrupt）在 threadpool 读
		# _turns，loop 侧写——字典成员增删与字段写入用短临界区线程锁串起，
		# 保证 is_running/get_public 读到一致快照（临界区内绝不 await）。
		self._tlock = threading.Lock()

	def _turn_locked(self, session_id: str) -> _DetachedTurn | None:
		"""调用方必须已持有 _tlock（或接受无锁读的弱一致时用 _turns.get）。"""
		return self._turns.get(session_id)

	def get_public(self, session_id: str) -> TurnPublic | None:
		with self._tlock:
			t = self._turn_locked(session_id)
			if t is not None:
				return TurnPublic(
					session_id=t.session_id,
					turn_id=t.turn_id,
					status=t.status,
					last_event_id=t.last_event_id,
					stop_reason=t.stop_reason,
					goal_text=t.goal_text,
					model=t.model,
					waiting_permission=t.waiting_permission,
					revision=t.revision,
				)
		if t is None:
			snap = hydrate_turn(session_id)
			if snap is None:
				return None
			return TurnPublic(
				session_id=snap.session_id,
				turn_id=snap.turn_id,
				status=snap.status,
				last_event_id=snap.last_event_id,
				stop_reason=snap.stop_reason,
				goal_text=snap.goal_text,
				model=snap.model,
				waiting_permission=snap.waiting_permission,
				revision=snap.revision,
			)


	def is_running(self, session_id: str) -> bool:
		with self._tlock:
			t = self._turn_locked(session_id)
			return t is not None and not t.done.is_set()

	async def start(
		self,
		*,
		session_id: str,
		lease_id: int,
		model: str,
		goal_text: str,
		user_message_id: str,
		producer: ProducerFn,
		turn_id: str | None = None,
	) -> str:
		"""启动 detached turn。若已有活跃 turn 则抛 RuntimeError。"""
		# 临界区（含 threading 锁）内无 await——start 的成员操作对
		# threadpool 读侧原子可见。
		with self._tlock:
			existing = self._turn_locked(session_id)
			if existing is not None and not existing.done.is_set():
				raise RuntimeError(f"turn already running for session {session_id}")
			tid = (turn_id or uuid.uuid4().hex[:12]).strip()
			det = _DetachedTurn(
				session_id=session_id,
				turn_id=tid,
				lease_id=lease_id,
				model=model,
				goal_text=(goal_text or "")[:4000],
				user_message_id=user_message_id or "",
				status="running",
			)
			self._turns[session_id] = det
			self._evict_terminal_turns_locked()
		try:
			await write_checkpoint(self._persist, det, begin=True, force_durable=True)
			det.last_checkpoint_at = time.monotonic()
		except BaseException:
			with self._tlock:
				if self._turns.get(session_id) is det:
					del self._turns[session_id]
			raise
		_log.info(
			"turn_start session=%s turn_id=%s reason=submit",
			session_id,
			tid,
		)
		det.task = asyncio.create_task(
			self._run_producer(det, producer),
			name=f"xeyo-turn-{session_id}-{tid}",
		)
		return tid

	def _evict_terminal_turns_locked(self) -> None:
		"""调用方必须持有 _tlock。终态 turn 只保留最近 N 个会话的，控内存。

		frames 只用于 reattach 重放；快照已落盘，丢弃旧终态不影响恢复。
		"""
		terminal = [
			(sid, t) for sid, t in self._turns.items() if t.done.is_set()
		]
		if len(terminal) <= _MAX_TERMINAL_TURNS:
			return
		terminal.sort(key=lambda st: st[1].started_at)
		for sid, _t in terminal[: len(terminal) - _MAX_TERMINAL_TURNS]:
			self._turns.pop(sid, None)

	def _publish(self, det: _DetachedTurn, item: tuple[int, bytes, str]) -> None:
		event_id, frame, _kind = item
		det.last_event_id = max(det.last_event_id, event_id)
		det.frames.append(item)
		det.frames_bytes += len(frame)
		while det.frames and (len(det.frames) > _MAX_BUFFERED_FRAMES or det.frames_bytes > _MAX_BUFFERED_BYTES):
			ev_id, ev_frame, _ = det.frames.popleft()
			det.frames_bytes -= len(ev_frame)
			det.dropped_through_id = max(det.dropped_through_id, ev_id)
		for queue in list(det.subscribers):
			_fanout(queue, item)

	async def _run_producer(self, det: _DetachedTurn, producer: ProducerFn) -> None:
		final_status, stop_reason = "succeeded", ""
		last_touch = 0.0
		pending_done = None
		failure_frame = None
		try:
			async with aclosing(producer()) as events:
				async for event_id, frame, kind in events:
					if kind == "done":
						# Completion acknowledges producer cleanup and the terminal checkpoint.
						pending_done = (int(event_id), frame, kind)
						continue
					with self._tlock:
						changed = apply_event(det, kind, frame)
						det.revision += 1
					self._publish(det, (int(event_id), frame, kind))
					now = time.monotonic()
					if now - last_touch >= 30.0:
						last_touch = now
						try:
							self._pool.touch_busy(det.session_id)
						except Exception:
							pass
					# Recovery facts are durable at their transition. Text cursors need only
					# the existing half-second recovery window, regardless of chunk size.
					if changed or now - det.last_checkpoint_at >= 0.5:
						await write_checkpoint(self._persist, det, force_durable=changed)
						det.last_checkpoint_at = time.monotonic()
		except asyncio.CancelledError:
			final_status, stop_reason = "stopped", "cancelled"
			raise
		except Exception as exc:
			final_status, stop_reason = "failed", type(exc).__name__
			failure_frame = {"error": {"message": str(exc), "type": stop_reason}}
			_log.warning("turn producer failed session=%s turn=%s", det.session_id, det.turn_id, exc_info=True)
		else:
			if det.outcome:
				final_status, stop_reason = det.outcome, det.outcome_reason
			elif det.status == "stopping":
				final_status, stop_reason = "stopped", det.stop_reason or "user_stop"
		finally:
			with self._tlock:
				det.finalizing = True
				det.revision += 1
				if pending_done is not None:
					# Persist the same cursor that clients will observe after completion.
					det.last_event_id = max(pending_done[0], det.last_event_id + 1)
			try:
				await write_checkpoint(self._persist, det, status=final_status, stop_reason=stop_reason, force_durable=True)
			except Exception:
				final_status, stop_reason = "failed", "snapshot_persist_failed"
				failure_frame = {"error": {"message": "Turn recovery state could not be persisted", "type": stop_reason}}
				_log.warning("terminal checkpoint failed session=%s turn=%s", det.session_id, det.turn_id, exc_info=True)
			with self._tlock:
				det.status, det.stop_reason = final_status, stop_reason
				det.waiting_permission = False
			if failure_frame is not None:
				frame = ("data: " + json.dumps(failure_frame) + "\n\n").encode()
				self._publish(det, (det.last_event_id + 1, frame, "error"))
			if pending_done is not None:
				self._publish(det, (det.last_event_id + (1 if failure_frame is not None else 0), pending_done[1], "done"))
			for queue in list(det.subscribers):
				_fanout(queue, _END)
			det.subscribers.clear()
			try:
				self._pool.end(det.session_id, det.lease_id)
			except Exception:
				_log.warning("pool.end failed session=%s turn=%s", det.session_id, det.turn_id, exc_info=True)
			with self._tlock:
				det.done.set()
			listener = _settlement_listener
			if listener is not None:
				try:
					token = _settled_user_message_id.set(det.user_message_id)
					try:
						coro = listener(det.session_id, final_status, stop_reason)
						if coro is not None:
							_spawn_settlement(coro)
					finally:
						_settled_user_message_id.reset(token)
				except Exception:
					_log.warning("turn settlement dispatch failed session=%s", det.session_id, exc_info=True)

	def _persist(self, det: _DetachedTurn, *, begin: bool = False, status: str | None = None,
		stop_reason: str | None = None, force_durable: bool = False) -> bool:
		with self._tlock:
			if self._turns.get(det.session_id) is not det:
				return False
			if det.finalizing and status is None:
				return False
			snap = TurnSnapshot(
				session_id=det.session_id, turn_id=det.turn_id,
				status=status or det.status, goal_text=det.goal_text,
				last_user_message_id=det.user_message_id, revision=det.revision,
				last_event_id=det.last_event_id, incomplete_tool_uses=list(det.incomplete_tools),
				active_agent_ids=list(det.active_agents),
				stop_reason=det.stop_reason if stop_reason is None else stop_reason,
				waiting_permission=det.waiting_permission if status is None else False, model=det.model,
			)
		return flush_turn(snap, expected_turn_id=None if begin else det.turn_id,
			strict=True, force_durable=force_durable)

	def note_client_disconnect(self, session_id: str, turn_id: str = "") -> None:
		"""SSE 断开：只记日志，不 interrupt。"""
		with self._tlock:
			t = self._turn_locked(session_id)
		tid = turn_id or (t.turn_id if t else "")
		_log.warning(
			"client_disconnect session=%s turn_id=%s reason=client_disconnect "
			"(turn continues detached)",
			session_id,
			tid,
		)

	def mark_stopping(self, session_id: str, reason: str = "user_stop") -> None:
		with self._tlock:
			t = self._turn_locked(session_id)
			if t is None or t.done.is_set() or t.finalizing:
				return
			t.status = "stopping"
			t.stop_reason = reason
			t.revision += 1
		self._persist(t, force_durable=True)
		_log.info(
			"turn_stopping session=%s turn_id=%s reason=%s",
			session_id,
			t.turn_id,
			reason,
		)

	async def subscribe(
		self,
		session_id: str,
		*,
		cursor: int = 0,
		expected_turn_id: str | None = None,
	) -> AsyncIterator[bytes | None]:
		"""从 cursor（不含）之后重放缓冲帧，再跟 live，直到 turn 结束。

		超时无新帧时 yield ``None``（心跳 tick），调用方应发 SSE ping。
		超时只 cancel ``q.get()``（可安全重启、不丢帧），**绝不**在调用方
		``wait_for(__anext__)``：那会把 CancelledError 注入本生成器并拆毁它，
		下一次 ``__anext__`` 直接 StopAsyncIteration，SSE 在无 [DONE] 下提前 EOF。
		"""
		with self._tlock:
			t = self._turn_locked(session_id)
		from engine.turn_subscription import rejection, rejection_frame
		reason = rejection(expected_turn_id, t if t is not None else self.get_public(session_id))
		if reason:
			yield rejection_frame(reason)
			return
		if t is None:
			# A completed durable snapshot may outlive its in-memory replay buffer.
			pub = self.get_public(session_id) if expected_turn_id else None
			if pub is not None and pub.last_event_id > cursor:
				yield _stream_gap_frame(dropped_through_event_id=pub.last_event_id, first_available_event_id=0)
				yield b"data: [DONE]\n\n"
			return
		# event_id 每 turn 从 1 重新编号（chat.py 每请求 new EventIdGenerator），而 GUI
		# 把游标存在会话级 sessionStorage 里 ⇒ 上一轮的大游标会把本轮重放全部滤空，
		# 端点再补 [DONE] ⇒ 回复"整条消失且显示已完成"。游标超出本轮最大事件号即判定
		# "来自更早的 turn"，归零重放本轮全部帧。
		if cursor > t.last_event_id:
			cursor = 0
		q = _SubscriberQueue()
		# 先挂订阅再重放，避免窗口丢帧；用 cursor 去重。
		t.subscribers.append(q)
		try:
			if t.dropped_through_id and cursor < t.dropped_through_id:
				# 客户端要的起点已被环形缓冲挤掉：只重放"还留着的那一段"是不完整的，
				# 必须把洞告诉它，由它去拉全量 transcript 对账（否则缺段会被当完整提交）。
				first_available = int(t.frames[0][0]) if t.frames else 0
				yield _stream_gap_frame(
					dropped_through_event_id=t.dropped_through_id,
					first_available_event_id=first_available,
				)
				_record_stream_gap(t, t.dropped_through_id, first_available)
			for event_id, frame, _kind in list(t.frames):
				if event_id > cursor:
					yield frame
					cursor = event_id
			if t.done.is_set():
				return
			while True:
				try:
					item = await asyncio.wait_for(q.get(), timeout=_SUBSCRIBE_TICK_S)
				except asyncio.TimeoutError:
					if q not in t.subscribers:
						# pump 已因溢出把本队列摘除（QueueFull 标死）：
						# 永远等不到帧/END，无限 ping 只会吊死连接，直接收流。
						return
					yield None
					continue
				# Even the end sentinel can evict an unread event from a full queue.
				# Report the gap before forwarding DONE, where clients stop reading.
				if q.dropped_through_id > cursor:
					yield _stream_gap_frame(
						dropped_through_event_id=q.dropped_through_id,
						first_available_event_id=0 if item is _END else int(item[0]),
					)
					_record_stream_gap(t, q.dropped_through_id, 0 if item is _END else int(item[0]))
					cursor = q.dropped_through_id
				if item is _END:
					break
				event_id, frame, _kind = item
				if event_id > cursor:
					yield frame
					cursor = event_id
		finally:
			try:
				t.subscribers.remove(q)
			except ValueError:
				pass

	async def wait_done(self, session_id: str, timeout: float | None = None) -> bool:
		with self._tlock:
			t = self._turn_locked(session_id)
		if t is None:
			return True
		try:
			if timeout is None:
				await t.done.wait()
			else:
				await asyncio.wait_for(t.done.wait(), timeout=timeout)
			return True
		except asyncio.TimeoutError:
			return False


# 模块单例：由 deps / app 注入 pool 后绑定
_runner: TurnRunner | None = None


def get_turn_runner() -> TurnRunner:
	if _runner is None:
		raise RuntimeError("TurnRunner is not bound; call bind_turn_runner(pool)")
	return _runner


def bind_turn_runner(pool: Any) -> TurnRunner:
	global _runner
	_runner = TurnRunner(pool)
	return _runner
