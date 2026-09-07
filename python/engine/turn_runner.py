"""Detached turn runner — SSE 是订阅者，不是执行租约。

GUI 刷新只断投影流；显式 Stop / interrupt 才杀 turn。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from engine.turn_snapshot import TurnSnapshot, flush as flush_turn, hydrate as hydrate_turn

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


def set_turn_settlement_listener(fn: _SettlementListener) -> None:
	"""注册 turn 终态监听（server lifespan 调用；多次调用覆盖）。"""
	global _settlement_listener
	_settlement_listener = fn


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
	frames: list[tuple[int, bytes, str]] = field(default_factory=list)
	subscribers: list[asyncio.Queue[Any]] = field(default_factory=list)
	task: asyncio.Task[None] | None = None
	done: asyncio.Event = field(default_factory=asyncio.Event)
	started_at: float = field(default_factory=time.monotonic)
	incomplete_tools: list[str] = field(default_factory=list)
	active_agents: list[str] = field(default_factory=list)
	frames_bytes: int = 0


_END = object()
# 订阅心跳：live 队列静默多久后向调用方 yield None（调用方发 SSE ping）。
# 必须远小于 FE idle watchdog（60s）。
_SUBSCRIBE_TICK_S = 12.0


class TurnRunner:
	"""进程内 per-session 至多一个活跃 detached turn。"""

	def __init__(self, pool: Any) -> None:
		self._pool = pool
		self._turns: dict[str, _DetachedTurn] = {}
		self._lock = asyncio.Lock()
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

	def is_running(self, session_id: str) -> bool:
		with self._tlock:
			t = self._turn_locked(session_id)
			return t is not None and not t.done.is_set() and t.status in {
				"running",
				"waiting_permission",
				"stopping",
				"queued",
			}

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
		async with self._lock:
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
				self._persist(det)
				self._evict_terminal_turns_locked()
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

	async def _run_producer(
		self, det: _DetachedTurn, producer: ProducerFn
	) -> None:
		final_status = "succeeded"
		stop_reason = ""
		last_touch = 0.0
		try:
			async for event_id, frame, kind in producer():
				det.last_event_id = max(det.last_event_id, int(event_id))
				det.frames.append((int(event_id), frame, kind))
				det.frames_bytes += len(frame)
				if (
					len(det.frames) > _MAX_BUFFERED_FRAMES
					or det.frames_bytes > _MAX_BUFFERED_BYTES
				):
					while det.frames and (
						len(det.frames) > _MAX_BUFFERED_FRAMES
						or det.frames_bytes > _MAX_BUFFERED_BYTES
					):
						_ev_id, ev_frame, _k = det.frames.pop(0)
						det.frames_bytes -= len(ev_frame)
				# busy 租约心跳：每 ≥30s 刷一次，防止长回合被 stale 回收。
				# 逐帧节流，避免每 delta 都抢 pool 锁。
				now = time.monotonic()
				if now - last_touch >= 30.0:
					last_touch = now
					try:
						self._pool.touch_busy(det.session_id)
					except Exception:
						pass
				if kind == "permission_pending":
					det.waiting_permission = True
					det.status = "waiting_permission"
				elif kind == "permission_resolved":
					det.waiting_permission = False
					if det.status == "waiting_permission":
						det.status = "running"
				elif kind == "tool_call":
					# 恢复数据：记录已发起未返回的工具（崩溃后续跑提示用）
					try:
						import json as _json

						xy = _json.loads(frame).get("xy") or {}
						tuid = str(xy.get("tool_use_id") or "")
						if tuid and tuid not in det.incomplete_tools:
							det.incomplete_tools.append(tuid)
							if len(det.incomplete_tools) > 64:
								del det.incomplete_tools[:32]
					except Exception:  # noqa: BLE001
						pass
				elif kind == "tool_result":
					try:
						import json as _json

						xy = _json.loads(frame).get("xy") or {}
						tuid = str(xy.get("tool_use_id") or "")
						if tuid and tuid in det.incomplete_tools:
							det.incomplete_tools.remove(tuid)
					except Exception:  # noqa: BLE001
						pass
				elif kind in ("multi_agent_task", "multi_agent_progress"):
					# 恢复数据：本 turn 出现过的子 agent id
					try:
						import json as _json

						xy = _json.loads(frame).get("xy") or {}
						aid = str(xy.get("agent_id") or "")
						if aid and aid not in det.active_agents:
							det.active_agents.append(aid)
							if len(det.active_agents) > 32:
								del det.active_agents[:16]
					except Exception:  # noqa: BLE001
						pass
				# 扇出
				dead: list[asyncio.Queue[Any]] = []
				for q in list(det.subscribers):
					try:
						q.put_nowait((int(event_id), frame, kind))
					except asyncio.QueueFull:
						dead.append(q)
					except Exception:  # noqa: BLE001
						dead.append(q)
				for q in dead:
					try:
						det.subscribers.remove(q)
					except ValueError:
						pass
					try:
						# 标死的慢订阅者必须收到终止哨兵，否则其 subscribe() 循环
						# 永远等不到帧/END（悬死连接，只能靠心跳兜底收流）。
						# 队列已满（QueueFull 才会标死）：先腾一格再入队。
						if q.full():
							q.get_nowait()
						q.put_nowait(_END)
					except Exception:  # noqa: BLE001
						pass
				if det.revision % 8 == 0:
					self._persist(det)
				det.revision += 1
		except asyncio.CancelledError:
			final_status = "stopped"
			stop_reason = "cancelled"
			_log.info(
				"turn_end session=%s turn_id=%s reason=cancelled",
				det.session_id,
				det.turn_id,
			)
			raise
		except Exception as exc:  # noqa: BLE001
			final_status = "failed"
			stop_reason = type(exc).__name__
			_log.warning(
				"turn_end session=%s turn_id=%s reason=error err=%s",
				det.session_id,
				det.turn_id,
				exc,
				exc_info=True,
			)
			# 通知订阅者错误帧由 producer 内部 yield；此处兜底
		else:
			if det.status == "stopping":
				final_status = "stopped"
				stop_reason = det.stop_reason or "user_stop"
			else:
				final_status = "succeeded"
				stop_reason = ""
			_log.info(
				"turn_end session=%s turn_id=%s reason=%s",
				det.session_id,
				det.turn_id,
				final_status if final_status != "succeeded" else "complete",
			)
		finally:
			# 终态写入 + done 置位对读侧原子可见（临界区内无 await）。
			with self._tlock:
				det.status = final_status
				det.stop_reason = stop_reason
				det.waiting_permission = False
				det.done.set()
			self._persist(det)
			for q in list(det.subscribers):
				try:
					q.put_nowait(_END)
				except Exception:  # noqa: BLE001
					pass
			det.subscribers.clear()
			det.done.set()
			try:
				self._pool.end(det.session_id, det.lease_id)
			except Exception:  # noqa: BLE001
				_log.debug("pool.end failed", exc_info=True)
			# 41 号：turn 终态广播（settlement 检查点）。此刻转录已落盘、租约已放
			# （等价 flush 义务）；listener 内部自隔离异常，这里再兜一层，
			# create_task 调度绝不阻塞 teardown、绝不影响 turn 终态。
			listener = _settlement_listener
			if listener is not None:
				try:
					_coro = listener(det.session_id, final_status, stop_reason)
					if _coro is not None:
						asyncio.create_task(_coro)
				except Exception:  # noqa: BLE001
					_log.debug("turn settlement dispatch failed", exc_info=True)
			# 终态保留一小段时间供 reattach 读 done；稍后可被新 turn 覆盖
			await asyncio.sleep(0)
			# 若已成功/失败，清 active 标记但保留 snapshot 供查询
			if final_status in {"succeeded", "failed", "stopped"}:
				# 保留 frames 直到被新 turn 替换或 GC
				pass

	def _persist(self, det: _DetachedTurn) -> None:
		snap = TurnSnapshot(
			session_id=det.session_id,
			turn_id=det.turn_id,
			status=det.status,  # type: ignore[arg-type]
			goal_text=det.goal_text,
			last_user_message_id=det.user_message_id,
			revision=det.revision,
			last_event_id=det.last_event_id,
			incomplete_tool_uses=list(det.incomplete_tools),
			active_agent_ids=list(det.active_agents),
			stop_reason=det.stop_reason,
			waiting_permission=det.waiting_permission,
			model=det.model,
		)
		flush_turn(snap)

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
			if t is None or t.done.is_set():
				return
			t.status = "stopping"
			t.stop_reason = reason
		self._persist(t)
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
	) -> AsyncIterator[bytes | None]:
		"""从 cursor（不含）之后重放缓冲帧，再跟 live，直到 turn 结束。

		超时无新帧时 yield ``None``（心跳 tick），调用方应发 SSE ping。
		超时只 cancel ``q.get()``（可安全重启、不丢帧），**绝不**在调用方
		``wait_for(__anext__)``：那会把 CancelledError 注入本生成器并拆毁它，
		下一次 ``__anext__`` 直接 StopAsyncIteration，SSE 在无 [DONE] 下提前 EOF。
		"""
		with self._tlock:
			t = self._turn_locked(session_id)
		if t is None:
			return
		q: asyncio.Queue[Any] = asyncio.Queue(maxsize=512)
		# 先挂订阅再重放，避免窗口丢帧；用 cursor 去重。
		t.subscribers.append(q)
		try:
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
	global _runner
	if _runner is None:
		from server.deps import _pool

		_runner = TurnRunner(_pool)
	return _runner


def bind_turn_runner(pool: Any) -> TurnRunner:
	global _runner
	_runner = TurnRunner(pool)
	return _runner
