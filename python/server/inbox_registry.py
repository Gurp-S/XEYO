"""主会话 Mid-Turn Inbox 注册表（P1）：把「回合进行中再发消息」从 409 变成排队投递。

mid-turn inbox 语义：
- **两条投递声道**：
  (a) **边界投递（默认，2026-09-20 起）**：``engine.t_now_inbox`` 在每个采样前的
      T_now 边界把排队消息取走、作为**真 user 消息**追加进历史（与 steer 共用
      队列/WAL/幂等/回队），工具批次不被打断、模型下一个采样前就看到；
  (b) **settle 排水（兜底）**：``on_turn_settled``（turn_runner `finally` 之后的
      settlement 检查点）把**仍留在队里**的消息合成一轮投递。长回合不 settle ⇒
      曾经只有 (b) ⇒ 用户消息整轮进不了模型输入（2026-09-20 事故）。
  两条声道共用同一队列：谁先取走谁投，取走即离开队列 ⇒ 不会重复投递。
- **不打断回合**：边界投递只发生在工具批次完成、下一次采样之前。
- **park 而非注入**：只入 FIFO，不打断当前 turn，不改 MessageStore / JSONL（不碰 T_now）。
- **投递与结果分离**：投递即 ``submit_synthetic(surface="inbox")``（复用 41/42 自调用通道），
  结果待下一轮 settlement 后另行排水。
- **KV 前缀零破坏**：投递轮请求 =「用户此刻手发一条消息」的逐字节等价——
  ``submit_synthetic`` 只回传一条 user 消息，engine warm 时 ``get_or_create`` 复用
  ``mutable_messages``，前缀（system + history）逐字节同构；T_now 仍只锚最新 user（见
  pre_llm_inject / turn_context，本模块零插入）。

**批投（省钱主杠杆）**：``XEYO_INBOX_COALESCE=1``（缺省）时 settlement 把队列里**此刻全部**
消息合并为一个合成轮（``\\n\\n`` 分隔）——节省 N-1 个「满上下文输入 + 输出」，且 N-1 个回合
不计入 ``turns_since_c2``，压制 C2 压缩（压缩=全前缀重建=成本尖峰+KV 破坏）。

**接线**：``server/app.py`` lifespan 调 ``register_inbox_listener()`` 把 ``on_turn_settled``
注册进 ``turn_settlement_hub``（**排第一**租户，inbox → goal → jobs；inbox 先提交则 goal 的
``_precheck`` 见 ``_turn_running`` 为真自动跳过，实现「用户消息优先于 goal 自动续跑」且不改
goal driver）。teardown 调 ``shutdown()``。

队列状态原子写入会话数据目录旁的私有 sidecar；人类入队只有在状态写盘成功后才返回 202。
settlement bookkeeping 失败仍不会阻断 turn，重启时可用 transcript message id 恢复投递状态。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from server.inbox_persistence import (
	InboxStateReadError,
	delete_inbox_state,
	load_inbox_state,
	save_inbox_state,
	transcript_message_ids,
)

_logger = logging.getLogger("xeyo.inbox")

# 队列上限（每会话）；超限仅对新 enqueue 拒绝（不影响已在队列的）。
_DEFAULT_MAX_QUEUED = 8
# 单条文本上限（沿用 chat 域上限，防超长打爆载荷）。
_MAX_CHARS = 2000
# 投递被拒（submit_synthetic False）后的最大尝试次数；≥ 此值置 stuck（GUI 可重试）。
_DEFAULT_MAX_ATTEMPTS = 3
# 批投开关：1 = settle 时合并队列消息为一个合成轮；0 = 逐条投递。
def _coalesce() -> bool:
	raw = os.environ.get("XEYO_INBOX_COALESCE", "1").strip().lower()
	return raw not in ("0", "false", "no", "off")


def _autorun() -> bool:
	raw = os.environ.get("XEYO_INBOX_AUTORUN", "1").strip().lower()
	return raw not in ("0", "false", "no", "off")


def _max_queued() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_INBOX_MAX_QUEUED", "") or _DEFAULT_MAX_QUEUED))
	except (TypeError, ValueError):
		return _DEFAULT_MAX_QUEUED


def _max_attempts() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_INBOX_MAX_ATTEMPTS", "") or _DEFAULT_MAX_ATTEMPTS))
	except (TypeError, ValueError):
		return _DEFAULT_MAX_ATTEMPTS


@dataclass
class InboxItem:
	"""一条排队中的用户消息及其可恢复投递状态。"""

	queue_id: str
	text: str
	media_refs: list[str] = field(default_factory=list)
	message_id: str | None = None
	queued_at: float = field(default_factory=time.time)
	attempts: int = 0
	state: str = "queued"  # queued | delivering | delivered | stuck
	sequence: int = 0
	delivery_id: str | None = None

	def to_dict(self, *, position: int = 0) -> dict[str, Any]:
		return {
			"queue_id": self.queue_id,
			# The snapshot feeds an editable GUI row. Truncating here silently
			# turns a refresh followed by edit into a destructive rewrite.
			"text": self.text,
			"media_refs": list(self.media_refs),
			"message_id": self.message_id,
			"queued_at": int(self.queued_at * 1000),
			"attempts": self.attempts,
			"state": self.state,
			"position": position,
			"delivery_id": self.delivery_id,
		}


class InboxRegistry:
	"""per-session 主会话消息队列 + settlement 排水租户。

	与 ``engine.live_agents`` 的 agent follow-up inbox 是两套生命周期模型：
	本队列面向用户消息，带 queue_id / attempts / 可重试队列状态与完成回执；agent inbox 面向
	子 Agent 的追加指令，无重试状态，仅落 ``meta.pending_followups`` 等待 settle/retry。
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		# FIFO 结构：key = session_id；value = deque[InboxItem]。
		self._queues: dict[str, list[InboxItem]] = {}
		# Popped messages stay visible until the synthetic chat settles. Completed
		# items remain visible until the GUI confirms its transcript backfill.
		self._inflight: dict[str, dict[str, InboxItem]] = {}
		self._completed: dict[str, dict[str, InboxItem]] = {}
		self._loaded_sessions: set[str] = set()
		self._reconcile_pending: set[str] = set()
		self._next_sequence = 0
		# 在途排水任务（per-session），防重复 spawn。
		self._drain_tasks: dict[str, asyncio.Task] = {}
		# P3 观测：累计投递批次 / 条目 / 估算 token（合并轮 chars/4）。
		self._batches_delivered = 0
		self._items_delivered = 0
		self._tokens_est = 0
		# 测试注入点。
		self._submit: Any = None

	def _submit_fn(self) -> Any:
		if self._submit is not None:
			return self._submit
		from server.synthetic_round import submit_synthetic

		return submit_synthetic

	@staticmethod
	def _stored_item(item: InboxItem) -> dict[str, Any]:
		return {
			"queue_id": item.queue_id,
			"text": item.text,
			"media_refs": list(item.media_refs),
			"message_id": item.message_id,
			"queued_at": item.queued_at,
			"attempts": item.attempts,
			"state": item.state,
			"sequence": item.sequence,
			"delivery_id": item.delivery_id,
		}

	def _persist_session_locked(self, session_id: str) -> bool:
		items = [
			*self._queues.get(session_id, []),
			*self._inflight.get(session_id, {}).values(),
			*self._completed.get(session_id, {}).values(),
		]
		items.sort(key=lambda item: item.sequence)
		return save_inbox_state(session_id, [self._stored_item(item) for item in items])

	def _capture_session_locked(self, session_id: str) -> tuple[Any, Any, Any]:
		return (
			copy.deepcopy(self._queues.get(session_id)),
			copy.deepcopy(self._inflight.get(session_id)),
			copy.deepcopy(self._completed.get(session_id)),
		)

	def _restore_session_locked(
		self, session_id: str, snapshot: tuple[Any, Any, Any]
	) -> None:
		queue, inflight, completed = snapshot
		for target, value in (
			(self._queues, queue),
			(self._inflight, inflight),
			(self._completed, completed),
		):
			if value is None:
				target.pop(session_id, None)
			else:
				target[session_id] = value

	def _persist_or_restore_locked(
		self, session_id: str, snapshot: tuple[Any, Any, Any]
	) -> None:
		if not self._persist_session_locked(session_id):
			self._restore_session_locked(session_id, snapshot)
			raise InboxPersistenceError(session_id)

	def _ensure_loaded_locked(self, session_id: str) -> None:
		if session_id in self._reconcile_pending:
			if not self._persist_session_locked(session_id):
				raise InboxPersistenceError(session_id)
			self._reconcile_pending.discard(session_id)
		if session_id in self._loaded_sessions:
			return
		try:
			stored = load_inbox_state(session_id)
		except InboxStateReadError as exc:
			raise InboxPersistenceError(session_id) from exc
		if not stored:
			self._loaded_sessions.add(session_id)
			return
		needs_reconcile = any(item.get("state") == "delivering" for item in stored)
		delivery_targets = {
			str(item["delivery_id"])
			for item in stored
			if item.get("state") == "delivering" and item.get("delivery_id")
		}
		transcript_ids = (
			transcript_message_ids(session_id, delivery_targets)
			if delivery_targets
			else set()
		)
		queue: list[InboxItem] = []
		completed: dict[str, InboxItem] = {}
		seen: set[str] = set()
		for raw in stored:
			queue_id = str(raw.get("queue_id") or "").strip()
			text = str(raw.get("text") or "").strip()
			if not queue_id or not text or queue_id in seen:
				continue
			state = str(raw.get("state") or "queued")
			if state not in {"queued", "stuck", "delivering", "delivered"}:
				state = "queued"
			try:
				sequence = max(0, int(raw.get("sequence") or 0))
				attempts = max(0, int(raw.get("attempts") or 0))
				queued_at = max(0.0, float(raw.get("queued_at") or time.time()))
			except (TypeError, ValueError):
				sequence, attempts, queued_at = 0, 0, time.time()
			item = InboxItem(
				queue_id=queue_id,
				text=text,
				media_refs=[
					str(ref)
					for ref in (
						raw.get("media_refs")
						if isinstance(raw.get("media_refs"), list)
						else []
					)
					if ref
				],
				message_id=(str(raw["message_id"]) if raw.get("message_id") else None),
				queued_at=queued_at,
				attempts=attempts,
				state=state,
				sequence=sequence,
				delivery_id=(str(raw["delivery_id"]) if raw.get("delivery_id") else None),
			)
			seen.add(queue_id)
			self._next_sequence = max(self._next_sequence, sequence)
			if state == "delivering":
				if item.delivery_id and item.delivery_id in transcript_ids:
					item.state = "delivered"
					completed[queue_id] = item
				else:
					# No persisted transcript row means the accepted turn never committed.
					item.state = "queued"
					item.delivery_id = None
					queue.append(item)
			elif state == "delivered":
				completed[queue_id] = item
			else:
				queue.append(item)
		if queue:
			self._queues[session_id] = sorted(queue, key=lambda item: item.sequence)
		if completed:
			self._completed[session_id] = completed
		self._loaded_sessions.add(session_id)
		if needs_reconcile:
			if not self._persist_session_locked(session_id):
				self._reconcile_pending.add(session_id)
				raise InboxPersistenceError(session_id)

	def _session_idle(self, session_id: str) -> bool:
		"""会话空闲（无 busy 租约 + 无活 turn）才可排水。"""
		try:
			from engine.turn_runner import get_turn_runner

			if get_turn_runner().is_running(session_id):
				return False
		except Exception:  # noqa: BLE001
			pass
		try:
			from server.deps import _pool

			if _pool.is_busy(session_id):
				return False
		except Exception:  # noqa: BLE001
			return True  # pool 不可用时不挡排水（保守不误伤）
		return True

	# ------------------------------------------------------------------
	# 队列操作
	# ------------------------------------------------------------------
	def enqueue(
		self,
		session_id: str,
		text: str,
		*,
		media_refs: list[str] | None = None,
		message_id: str | None = None,
	) -> InboxItem:
		"""入队一条消息；超限抛 ``InboxQueueFull``，超长抛 ``InboxTextTooLong``。"""
		t = (text or "").strip()
		sid = (session_id or "").strip()
		if not sid:
			raise ValueError("session_id is required")
		if not t:
			raise ValueError("empty inbox text")
		if len(t) > _MAX_CHARS:
			# 2026-09-05 修正：不再静默截断（丢用户内容），改显式报错由调用方映射 413。
			raise InboxTextTooLong(sid, len(t), _MAX_CHARS)
		queue_id = uuid.uuid4().hex[:12]
		item = InboxItem(
			queue_id=queue_id,
			text=t,
			media_refs=list(media_refs or []),
			message_id=message_id or uuid.uuid4().hex,
		)
		with self._lock:
			self._ensure_loaded_locked(sid)
			self._next_sequence += 1
			item.sequence = self._next_sequence
			q = self._queues.setdefault(sid, [])
			if len(q) >= _max_queued():
				raise InboxQueueFull(sid, _max_queued())
			q.append(item)
			try:
				if not self._persist_session_locked(sid):
					q.pop()
					if not q:
						self._queues.pop(sid, None)
					raise InboxPersistenceError(sid)
			except Exception:
				if item in self._queues.get(sid, []):
					self._queues[sid].remove(item)
					if not self._queues[sid]:
						self._queues.pop(sid, None)
				raise
		_logger.debug("inbox enqueue session=%s qid=%s pending=%s", sid, queue_id, len(q))
		return item

	def snapshot(self, session_id: str) -> dict[str, Any]:
		sid = (session_id or "").strip()
		with self._lock:
			self._ensure_loaded_locked(sid)
			q = list(self._queues.get(sid, []))
			inflight = list(self._inflight.get(sid, {}).values())
			completed = list(self._completed.get(sid, {}).values())
		items = sorted((*q, *inflight, *completed), key=lambda item: item.sequence)
		if _autorun() and any(item.state == "queued" for item in q):
			self._maybe_schedule(sid)
		return {
			"autorun": _autorun(),
			"coalesce": _coalesce(),
			"items": [it.to_dict(position=i + 1) for i, it in enumerate(items)],
		}

	def prepare_snapshot(self, session_id: str) -> None:
		"""Load/reconcile disk state separately from an async HTTP event loop."""
		with self._lock:
			self._ensure_loaded_locked((session_id or "").strip())

	def peek(self, session_id: str) -> InboxItem | None:
		with self._lock:
			self._ensure_loaded_locked(session_id)
			q = self._queues.get(session_id)
			return q[0] if q else None

	def pop_all(self, session_id: str) -> list[InboxItem]:
		"""原子取空该会话队列（仅批投模式使用）。"""
		with self._lock:
			self._ensure_loaded_locked(session_id)
			before = self._capture_session_locked(session_id)
			items = self._queues.pop(session_id, [])
			self._persist_or_restore_locked(session_id, before)
			return items

	def pop_active(self, session_id: str) -> list[InboxItem]:
		"""取走全部**非 stuck** 项并标记 delivering（批投模式；stuck 项留在队内）。

		2026-09-05 修正：旧 ``pop_all`` 连 stuck 项一起取走重投，stuck 语义在
		批投模式下失效（毒丸项每次 settle 都被重试，永久性失败会堵死整批）。
		"""
		with self._lock:
			self._ensure_loaded_locked(session_id)
			q = self._queues.get(session_id)
			if not q:
				return []
			before = self._capture_session_locked(session_id)
			active = [it for it in q if it.state == "queued"]
			stuck = [it for it in q if it.state != "queued"]
			if not active:
				return []
			if stuck:
				self._queues[session_id] = stuck
			else:
				self._queues.pop(session_id, None)
			inflight = self._inflight.setdefault(session_id, {})
			delivery_id = next((it.message_id for it in active if it.message_id), None)
			delivery_id = delivery_id or uuid.uuid4().hex
			for it in active:
				it.state = "delivering"
				it.delivery_id = delivery_id
				inflight[it.queue_id] = it
			self._persist_or_restore_locked(session_id, before)
			return active

	def consume_for_boundary(self, session_id: str) -> list[InboxItem]:
		"""取走全部 queued 项（边界投递用；stuck 项留在队内）。

		条目在快照中保持 ``delivering``，同时改由 ``engine.t_now_steer`` 承担
		「至少一次 + 幂等 + WAL」；失败时用 :meth:`restore_front` 原样放回，不计
		attempts（不算本队列的投递失败）。
		"""
		sid = (session_id or "").strip()
		if not sid:
			return []
		with self._lock:
			self._ensure_loaded_locked(sid)
			q = self._queues.get(sid)
			if not q:
				return []
			active = [it for it in q if it.state == "queued"]
			if not active:
				return []
			before = self._capture_session_locked(sid)
			stuck = [it for it in q if it.state != "queued"]
			if stuck:
				self._queues[sid] = stuck
			else:
				self._queues.pop(sid, None)
			inflight = self._inflight.setdefault(sid, {})
			for it in active:
				it.state = "delivering"
				it.message_id = it.message_id or uuid.uuid4().hex
				it.delivery_id = it.message_id
				inflight[it.queue_id] = it
			self._persist_or_restore_locked(sid, before)
			return active

	def restore_front(self, session_id: str, items: list[InboxItem]) -> None:
		"""把 :meth:`consume_for_boundary` 取走的条目原样放回队首（不计 attempts）。"""
		sid = (session_id or "").strip()
		if not sid or not items:
			return
		with self._lock:
			self._ensure_loaded_locked(sid)
			inflight = self._inflight.get(sid)
			if inflight:
				for it in items:
					inflight.pop(it.queue_id, None)
				if not inflight:
					self._inflight.pop(sid, None)
			q = self._queues.setdefault(sid, [])
			for it in reversed(items):
				it.state = "queued"
				q.insert(0, it)
			if not self._persist_session_locked(sid):
				# Preserve a live retry path. The durable snapshot still says
				# delivering and startup reconciliation will recover it by id.
				_logger.warning("inbox restore persistence failed sid=%s", sid)

	def _pop_first_active(self, session_id: str) -> InboxItem | None:
		"""取走首条**非 stuck** 项并标记 delivering（逐条模式）。

		2026-09-05 修正：旧 ``peek`` 不跳 stuck，stuck 项卡队首会阻塞其后所有消息。
		"""
		with self._lock:
			self._ensure_loaded_locked(session_id)
			q = self._queues.get(session_id)
			if not q:
				return None
			for i, it in enumerate(q):
				if it.state == "queued":
					before = self._capture_session_locked(session_id)
					del q[i]
					if not q:
						self._queues.pop(session_id, None)
					it.state = "delivering"
					it.delivery_id = it.message_id or uuid.uuid4().hex
					it.message_id = it.delivery_id
					self._inflight.setdefault(session_id, {})[it.queue_id] = it
					self._persist_or_restore_locked(session_id, before)
					return it
			return None

	def pop_front(self, session_id: str) -> InboxItem | None:
		"""取出一条（逐条模式使用）；取空则移除队列键。"""
		with self._lock:
			self._ensure_loaded_locked(session_id)
			q = self._queues.get(session_id)
			if not q:
				return None
			before = self._capture_session_locked(session_id)
			it = q.pop(0)
			if not q:
				self._queues.pop(session_id, None)
			self._persist_or_restore_locked(session_id, before)
			return it

	def _finish_delivering(self, session_id: str, items: list[InboxItem]) -> None:
		"""Forget items already appended at a live T_now boundary."""
		with self._lock:
			self._ensure_loaded_locked(session_id)
			inflight = self._inflight.get(session_id)
			if not inflight:
				return
			for it in items:
				inflight.pop(it.queue_id, None)
			if not inflight:
				self._inflight.pop(session_id, None)
			if not self._persist_session_locked(session_id):
				# The durable row still says delivering. On restart the transcript
				# anchor reconciles it to a delivered receipt without redelivery.
				_logger.warning("inbox boundary completion persistence failed sid=%s", session_id)

	def _finish_settled_delivery(self, session_id: str, message_id: str) -> None:
		"""Move the matching synthetic delivery to GUI transcript acknowledgement."""
		mid = (message_id or "").strip()
		if not mid:
			return
		with self._lock:
			self._ensure_loaded_locked(session_id)
			inflight = self._inflight.get(session_id)
			if not inflight:
				return
			matching = [item for item in inflight.values() if item.delivery_id == mid]
			if not matching:
				return
			completed = self._completed.setdefault(session_id, {})
			for item in matching:
				inflight.pop(item.queue_id, None)
				item.state = "delivered"
				completed[item.queue_id] = item
			if not inflight:
				self._inflight.pop(session_id, None)
			# An inactive GUI may not acknowledge immediately. Bound recent receipts.
			while len(completed) > 64:
				oldest = min(completed.values(), key=lambda item: item.sequence)
				completed.pop(oldest.queue_id, None)
			if not self._persist_session_locked(session_id):
				# Keep the in-memory receipt visible. A stale durable delivering row
				# is recoverable from its transcript message id after restart.
				_logger.warning("inbox settlement persistence failed sid=%s", session_id)

	def acknowledge_delivered(self, session_id: str, queue_ids: list[str]) -> int:
		"""Drop receipt rows after the GUI has loaded the server transcript."""
		sid = (session_id or "").strip()
		ids = {str(queue_id or "").strip() for queue_id in queue_ids}
		ids.discard("")
		if not sid or not ids:
			return 0
		with self._lock:
			self._ensure_loaded_locked(sid)
			completed = self._completed.get(sid)
			if not completed:
				return 0
			before = self._capture_session_locked(sid)
			removed = sum(
				1 for queue_id in ids if completed.pop(queue_id, None) is not None
			)
			if not completed:
				self._completed.pop(sid, None)
			if removed:
				self._persist_or_restore_locked(sid, before)
			return removed

	def remove(self, session_id: str, queue_id: str) -> bool:
		"""取消仍在队列中的消息；投递中与完成回执均不可取消。"""
		sid = (session_id or "").strip()
		qid = (queue_id or "").strip()
		with self._lock:
			self._ensure_loaded_locked(sid)
			q = self._queues.get(sid)
			if not q:
				return False
			for i, it in enumerate(q):
				if it.queue_id == qid:
					if it.state == "delivering":
						return False
					before = self._capture_session_locked(sid)
					del q[i]
					if not q:
						self._queues.pop(sid, None)
					self._persist_or_restore_locked(sid, before)
					return True
		return False

	def edit(self, session_id: str, queue_id: str, text: str) -> InboxItem | None:
		"""改写单条排队消息文本；not found / delivering 态返回 None（与 remove 同口径）。

		超长抛 ``InboxTextTooLong``（调用方映射 413）；空文本视为无效返回 None。
		只改 text——queue_id / 队内位置 / attempts / queued_at 全保留（编辑不重排队）。
		"""
		sid = (session_id or "").strip()
		qid = (queue_id or "").strip()
		t = (text or "").strip()
		if not sid or not qid or not t:
			return None
		if len(t) > _MAX_CHARS:
			raise InboxTextTooLong(sid, len(t), _MAX_CHARS)
		with self._lock:
			self._ensure_loaded_locked(sid)
			q = self._queues.get(sid)
			if not q:
				return None
			for it in q:
				if it.queue_id == qid:
					if it.state == "delivering":
						return None
					before = self._capture_session_locked(sid)
					it.text = t
					self._persist_or_restore_locked(sid, before)
					return it
		return None

	def resume(
		self, session_id: str, queue_id: str | None = None
	) -> dict[str, Any] | None:
		"""重试 stuck 项并重新 arm；指定 queue_id 时只重试对应项。"""
		sid = (session_id or "").strip()
		qid = (queue_id or "").strip()
		found = False
		with self._lock:
			self._ensure_loaded_locked(sid)
			q = self._queues.get(sid)
			if q:
				before = self._capture_session_locked(sid)
				for it in q:
					if it.state != "stuck" or (qid and it.queue_id != qid):
						continue
					found = True
					it.state = "queued"
					# 重试不无限烧：清零 attempts，但靠下次拒绝再计数。
					it.attempts = 0
				if found:
					self._persist_or_restore_locked(sid, before)
		if qid and not found:
			return None
		self._maybe_schedule(sid)
		return self.snapshot(sid)

	def drop_session(self, session_id: str) -> None:
		"""FE 删除 session 时清队列 + 作废在途排水。"""
		sid = (session_id or "").strip()
		with self._lock:
			task = self._drain_tasks.pop(sid, None)
			if not delete_inbox_state(sid):
				if task is not None:
					self._drain_tasks[sid] = task
				raise InboxPersistenceError(sid)
			self._queues.pop(sid, None)
			self._inflight.pop(sid, None)
			self._completed.pop(sid, None)
			self._loaded_sessions.discard(sid)
			self._reconcile_pending.discard(sid)
		if task is not None and not task.done():
			task.cancel()

	def __len__(self) -> int:
		with self._lock:
			return sum(len(q) for q in self._queues.values()) + sum(
				len(items) for items in self._inflight.values()
			) + sum(len(items) for items in self._completed.values())

	def counts(self) -> dict[str, Any]:
		"""P3 /health 聚合：每会话 pending + stuck + 累计投递观测。"""
		with self._lock:
			pending = sum(len(q) for q in self._queues.values()) + sum(
				len(items) for items in self._inflight.values()
			) + sum(len(items) for items in self._completed.values())
			stuck = sum(
				1
				for q in self._queues.values()
				for it in q
				if it.state == "stuck"
			)
			return {
				"pending": pending,
				"stuck": stuck,
				"sessions": len(
					set(self._queues) | set(self._inflight) | set(self._completed)
				),
				"batches_delivered": self._batches_delivered,
				"items_delivered": self._items_delivered,
				"tokens_est": self._tokens_est,
			}

	# ------------------------------------------------------------------
	# settlement 检查点（hub 租户 · 排第一）
	# ------------------------------------------------------------------
	async def on_turn_settled(
		self,
		session_id: str,
		final_status: str,
		stop_reason: str,
		user_message_id: str = "",
	) -> None:
		"""turn 终态：succeeded/failed → 空闲则排水；stopped/cancelled → hold。

		异常全隔离——本协程绝不向调度方抛（turn_runner create_task 不等待它）。
		"""
		try:
			self._finish_settled_delivery(session_id, user_message_id)
			if final_status in ("stopped", "cancelled"):
				# 用户停 / HTTP 取消：moss 已投递消息已被消费，剩余队列 hold；
				# 下一条由下一次人类消息 settle 或 resume 触发（「interrupt
				# 只停当前回合，停靠消息保留」）。
				return
			if final_status not in ("succeeded", "failed"):
				return
			if not _autorun():
				return  # 只排队不自动跑，靠 resume 手动投递
			self._maybe_schedule(session_id)
		except Exception:  # noqa: BLE001
			_logger.debug("inbox settlement skipped sid=%s", session_id, exc_info=True)

	def _maybe_schedule(self, session_id: str) -> None:
		"""预约一次排水（仅 async 上下文调用；已在途则跳过）。"""
		try:
			loop = asyncio.get_running_loop()
		except RuntimeError:
			# 无运行循环（如同步端点误调）：放弃预约，等下一次 settlement。
			# 提前 return 可避免创建协程后未 await 的 RuntimeWarning。
			return
		try:
			cur = asyncio.current_task()
		except RuntimeError:  # pragma: no cover
			cur = None
		with self._lock:
			existing = self._drain_tasks.get(session_id)
			if existing is not None and existing is not cur and not existing.done():
				return
			if existing is not None and existing.done():
				self._drain_tasks.pop(session_id, None)
			task = loop.create_task(
				self._drain(session_id), name=f"xeyo-inbox-drain-{session_id}"
			)
			self._drain_tasks[session_id] = task

	async def _drain(self, session_id: str) -> None:
		"""防御：会话不空闲则等下一次 settle；否则按批投/逐条投递。"""
		drain_succeeded = True
		try:
			if not self._session_idle(session_id):
				with self._lock:
					self._drain_tasks.pop(session_id, None)
				return
			if _coalesce():
				drain_succeeded = await self._drain_batch(session_id)
			else:
				drain_succeeded = await self._drain_one(session_id)
		except Exception:  # noqa: BLE001
			drain_succeeded = False
			_logger.debug("inbox drain failed sid=%s", session_id, exc_info=True)
		finally:
			with self._lock:
				t = self._drain_tasks.get(session_id)
				if t is asyncio.current_task():
					self._drain_tasks.pop(session_id, None)
			# 批投/逐条期间若有新消息到货（还留在队列）→ 继续排水，保 FIFO 且不丢。
			# 只对「仍有 queued 项」续排，避免 stuck 项陷入 submit 拒绝的忙循环。
			try:
				if (
					drain_succeeded
					and _autorun()
					and self._has_queued(session_id)
					and self._session_idle(session_id)
				):
					self._maybe_schedule(session_id)
			except Exception:  # noqa: BLE001
				_logger.debug("inbox reschedule skipped sid=%s", session_id, exc_info=True)

	def _has_queued(self, session_id: str) -> bool:
		with self._lock:
			self._ensure_loaded_locked(session_id)
			q = self._queues.get(session_id)
			return bool(q) and any(it.state == "queued" for it in q)

	async def _drain_batch(self, session_id: str) -> bool:
		"""批投：取走全部非 stuck 项合并为一个合成轮（N->1，省钱 + 减压缩计数）。"""
		items = self.pop_active(session_id)
		if not items:
			return True
		joined = "\n\n".join(it.text for it in items)
		media_refs = [r for it in items for r in it.media_refs]
		delivery_id = items[0].delivery_id or items[0].message_id or uuid.uuid4().hex
		try:
			started = await self._submit_fn()(
				session_id,
				joined,
				surface="inbox",
				media_refs=media_refs,
				message_id=delivery_id,
			)
		except Exception:  # noqa: BLE001 — unexpected submit failures must restore the inbox
			_logger.warning("inbox batch submit raised sid=%s", session_id, exc_info=True)
			started = False
		if started:
			_logger.info(
				"inbox batch delivered sid=%s count=%s chars=%s",
				session_id,
				len(items),
				len(joined),
			)
			with self._lock:
				self._batches_delivered += 1
				self._items_delivered += len(items)
				self._tokens_est += max(1, len(joined) // 4)
			return True
		# 未被引擎接受（但已被 pop_active）→ 放回 + 计数（attempts）。
		self._requeue_failed(session_id, items)
		return False

	async def _drain_one(self, session_id: str) -> bool:
		"""逐条投递：一次取一条（跳过 stuck）；成功消费，剩余下次 settle。"""
		it = self._pop_first_active(session_id)
		if it is None:
			return True
		try:
			started = await self._submit_fn()(
				session_id,
				it.text,
				surface="inbox",
				media_refs=it.media_refs,
				message_id=it.delivery_id,
							)
		except Exception:  # noqa: BLE001 — unexpected submit failures must restore the inbox
			_logger.warning(
				"inbox submit raised sid=%s qid=%s",
				session_id,
				it.queue_id,
				exc_info=True,
			)
			started = False
		if started:
			with self._lock:
				self._batches_delivered += 1
				self._items_delivered += 1
				self._tokens_est += max(1, len(it.text) // 4)
			return True
		self._requeue_failed(session_id, [it])
		return False

	def _requeue_failed(self, session_id: str, items: list[InboxItem]) -> None:
		"""投递失败：把 items 放回队首（保持顺序）并递增 attempts。

		2026-09-05 修正：回填时恢复 state（delivering → queued/stuck）；超过队列
		上限时**保数据不丢**（回队优先于限流）并告警——失败回放不该静默丢消息。
		"""
		with self._lock:
			inflight = self._inflight.get(session_id)
			if inflight:
				for it in items:
					inflight.pop(it.queue_id, None)
				if not inflight:
					self._inflight.pop(session_id, None)
			q = self._queues.setdefault(session_id, [])
			for it in items:
				it.attempts += 1
				it.state = "stuck" if it.attempts >= _max_attempts() else "queued"
				# Reuse the same user identity on an explicit retry. A rejected
				# synthetic request has no transcript row, so this remains idempotent.
				if it.delivery_id and not it.message_id:
					it.message_id = it.delivery_id
				it.delivery_id = None
			q[:0] = items
			if len(q) > _max_queued():
				_logger.warning(
					"inbox requeue over limit sid=%s len=%s limit=%s",
					session_id,
					len(q),
					_max_queued(),
				)
			if not self._persist_session_locked(session_id):
				_logger.warning("inbox failed-delivery persistence failed sid=%s", session_id)
		_logger.warning(
			"inbox submit rejected sid=%s count=%s", session_id, len(items)
		)

	def shutdown(self) -> None:
		"""app lifespan teardown：作废在途排水并释放内存，保留磁盘队列供重启恢复。"""
		with self._lock:
			tasks = list(self._drain_tasks.values())
			self._drain_tasks.clear()
			self._queues.clear()
			self._inflight.clear()
			self._completed.clear()
			self._loaded_sessions.clear()
			self._reconcile_pending.clear()
		for t in tasks:
			if not t.done():
				t.cancel()


class InboxQueueFull(ValueError):
	def __init__(self, session_id: str, limit: int) -> None:
		self.session_id = session_id
		self.limit = limit
		super().__init__(f"inbox queue full for session {session_id} (limit {limit})")


class InboxTextTooLong(ValueError):
	def __init__(self, session_id: str, length: int, limit: int) -> None:
		self.session_id = session_id
		self.length = length
		self.limit = limit
		super().__init__(
			f"inbox text too long for session {session_id} "
			f"({length} > {limit} chars)"
		)


class InboxPersistenceError(RuntimeError):
	"""Durable inbox state could not be read or updated."""

	def __init__(self, session_id: str) -> None:
		self.session_id = session_id
		super().__init__(f"inbox state unavailable for session {session_id}")


# 模块单例（照 get_goal_round_driver 范式）。
_registry: InboxRegistry | None = None


def get_inbox_registry() -> InboxRegistry:
	global _registry
	if _registry is None:
		_registry = InboxRegistry()
	return _registry


__all__ = [
	"InboxItem",
	"InboxQueueFull",
	"InboxPersistenceError",
	"InboxTextTooLong",
	"get_inbox_registry",
]
