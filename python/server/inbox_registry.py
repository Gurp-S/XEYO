"""主会话 Mid-Turn Inbox 注册表（P1）：把「回合进行中再发消息」从 409 变成排队投递。

mid-turn inbox 语义：
- **消息只在回合边界投递**：``on_turn_settled``（turn_runner `finally` 之后的 settlement
  检查点）是唯一投递点；绝不改道已在进行的回合。
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

全路径 try/except 降级：本模块任何异常只记日志，绝不影响 turn 与人类请求（照 hub 现有租户惯例）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

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
	"""一条排队中的用户消息（仅内存；服务重启即丢，与 ``_pending_interrupt`` 同口径）。"""

	queue_id: str
	text: str
	media_refs: list[str] = field(default_factory=list)
	message_id: str | None = None
	queued_at: float = field(default_factory=time.time)
	attempts: int = 0
	state: str = "queued"  # queued | delivering | stuck

	def to_dict(self, *, position: int = 0) -> dict[str, Any]:
		return {
			"queue_id": self.queue_id,
			"text": self.text[:160] if len(self.text) > 160 else self.text,
			"media_refs": list(self.media_refs),
			"message_id": self.message_id,
			"queued_at": int(self.queued_at * 1000),
			"attempts": self.attempts,
			"state": self.state,
			"position": position,
		}


class InboxRegistry:
	"""per-session 主会话消息队列 + settlement 排水租户。

	与 ``engine.live_agents`` 的 agent follow-up inbox 是两套生命周期模型：
	本队列面向用户消息，带 queue_id / attempts / 三态重投；agent inbox 面向
	子 Agent 的追加指令，无重试状态，仅落 ``meta.pending_followups`` 等待 settle/retry。
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		# FIFO 结构：key = session_id；value = deque[InboxItem]。
		self._queues: dict[str, list[InboxItem]] = {}
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
			message_id=message_id,
		)
		with self._lock:
			q = self._queues.setdefault(sid, [])
			if len(q) >= _max_queued():
				raise InboxQueueFull(sid, _max_queued())
			q.append(item)
		_logger.debug("inbox enqueue session=%s qid=%s pending=%s", sid, queue_id, len(q))
		return item

	def snapshot(self, session_id: str) -> dict[str, Any]:
		sid = (session_id or "").strip()
		with self._lock:
			q = list(self._queues.get(sid, []))
		return {
			"autorun": _autorun(),
			"coalesce": _coalesce(),
			"items": [it.to_dict(position=i + 1) for i, it in enumerate(q)],
		}

	def peek(self, session_id: str) -> InboxItem | None:
		with self._lock:
			q = self._queues.get(session_id)
			return q[0] if q else None

	def pop_all(self, session_id: str) -> list[InboxItem]:
		"""原子取空该会话队列（仅批投模式使用）。"""
		with self._lock:
			return self._queues.pop(session_id, [])

	def pop_active(self, session_id: str) -> list[InboxItem]:
		"""取走全部**非 stuck** 项并标记 delivering（批投模式；stuck 项留在队内）。

		2026-09-05 修正：旧 ``pop_all`` 连 stuck 项一起取走重投，stuck 语义在
		批投模式下失效（毒丸项每次 settle 都被重试，永久性失败会堵死整批）。
		"""
		with self._lock:
			q = self._queues.get(session_id)
			if not q:
				return []
			active = [it for it in q if it.state != "stuck"]
			stuck = [it for it in q if it.state == "stuck"]
			if not active:
				return []
			if stuck:
				self._queues[session_id] = stuck
			else:
				self._queues.pop(session_id, None)
			for it in active:
				it.state = "delivering"
			return active

	def _pop_first_active(self, session_id: str) -> InboxItem | None:
		"""取走首条**非 stuck** 项并标记 delivering（逐条模式）。

		2026-09-05 修正：旧 ``peek`` 不跳 stuck，stuck 项卡队首会阻塞其后所有消息。
		"""
		with self._lock:
			q = self._queues.get(session_id)
			if not q:
				return None
			for i, it in enumerate(q):
				if it.state != "stuck":
					del q[i]
					if not q:
						self._queues.pop(session_id, None)
					it.state = "delivering"
					return it
			return None

	def pop_front(self, session_id: str) -> InboxItem | None:
		"""取出一条（逐条模式使用）；取空则移除队列键。"""
		with self._lock:
			q = self._queues.get(session_id)
			if not q:
				return None
			it = q.pop(0)
			if not q:
				self._queues.pop(session_id, None)
			return it

	def remove(self, session_id: str, queue_id: str) -> bool:
		"""取消单条排队消息；已在投递中（delivering）返回 False。"""
		sid = (session_id or "").strip()
		qid = (queue_id or "").strip()
		with self._lock:
			q = self._queues.get(sid)
			if not q:
				return False
			for i, it in enumerate(q):
				if it.queue_id == qid:
					if it.state == "delivering":
						return False
					del q[i]
					if not q:
						self._queues.pop(sid, None)
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
			q = self._queues.get(sid)
			if not q:
				return None
			for it in q:
				if it.queue_id == qid:
					if it.state == "delivering":
						return None
					it.text = t
					return it
		return None

	def resume(self, session_id: str) -> dict[str, Any]:
		"""清 stuck 计数并重新 arm（会话空闲则立即排水）。"""
		sid = (session_id or "").strip()
		with self._lock:
			q = self._queues.get(sid)
			if q:
				for it in q:
					it.state = "queued"
					# 重试不无限烧：清零 attempts，但靠下次拒绝再计数。
					it.attempts = 0
		self._maybe_schedule(sid)
		return self.snapshot(sid)

	def drop_session(self, session_id: str) -> None:
		"""FE 删除 session 时清队列 + 作废在途排水。"""
		sid = (session_id or "").strip()
		with self._lock:
			self._queues.pop(sid, None)
			task = self._drain_tasks.pop(sid, None)
		if task is not None and not task.done():
			task.cancel()

	def __len__(self) -> int:
		with self._lock:
			return sum(len(q) for q in self._queues.values())

	def counts(self) -> dict[str, Any]:
		"""P3 /health 聚合：每会话 pending + stuck + 累计投递观测。"""
		with self._lock:
			pending = 0
			stuck = 0
			for sid, q in self._queues.items():
				pending += len(q)
				stuck += sum(1 for it in q if it.state == "stuck")
			return {
				"pending": pending,
				"stuck": stuck,
				"sessions": len(self._queues),
				"batches_delivered": self._batches_delivered,
				"items_delivered": self._items_delivered,
				"tokens_est": self._tokens_est,
			}

	# ------------------------------------------------------------------
	# settlement 检查点（hub 租户 · 排第一）
	# ------------------------------------------------------------------
	async def on_turn_settled(
		self, session_id: str, final_status: str, stop_reason: str
	) -> None:
		"""turn 终态：succeeded/failed → 空闲则排水；stopped/cancelled → hold。

		异常全隔离——本协程绝不向调度方抛（turn_runner create_task 不等待它）。
		"""
		try:
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
		try:
			if not self._session_idle(session_id):
				with self._lock:
					self._drain_tasks.pop(session_id, None)
				return
			if _coalesce():
				await self._drain_batch(session_id)
			else:
				await self._drain_one(session_id)
		except Exception:  # noqa: BLE001
			_logger.debug("inbox drain failed sid=%s", session_id, exc_info=True)
		finally:
			with self._lock:
				t = self._drain_tasks.get(session_id)
				if t is asyncio.current_task():
					self._drain_tasks.pop(session_id, None)
			# 批投/逐条期间若有新消息到货（还留在队列）→ 继续排水，保 FIFO 且不丢。
			# 只对「仍有 queued 项」续排，避免 stuck 项陷入 submit 拒绝的忙循环。
			if (
				_autorun()
				and self._has_queued(session_id)
				and self._session_idle(session_id)
			):
				self._maybe_schedule(session_id)

	def _has_queued(self, session_id: str) -> bool:
		with self._lock:
			q = self._queues.get(session_id)
			return bool(q) and any(it.state != "stuck" for it in q)

	async def _drain_batch(self, session_id: str) -> None:
		"""批投：取走全部非 stuck 项合并为一个合成轮（N->1，省钱 + 减压缩计数）。"""
		items = self.pop_active(session_id)
		if not items:
			return
		joined = "\n\n".join(it.text for it in items)
		media_refs = [r for it in items for r in it.media_refs]
		first_id = next((it.message_id for it in items if it.message_id), None)
		started = await self._submit_fn()(
			session_id,
			joined,
			surface="inbox",
			media_refs=media_refs,
			message_id=first_id,
		)
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
			return
		# 未被引擎接受（但已被 pop_active）→ 放回 + 计数（attempts）。
		self._requeue_failed(session_id, items)

	async def _drain_one(self, session_id: str) -> None:
		"""逐条投递：一次取一条（跳过 stuck）；成功消费，剩余下次 settle。"""
		it = self._pop_first_active(session_id)
		if it is None:
			return
		started = await self._submit_fn()(
			session_id,
			it.text,
			surface="inbox",
			media_refs=it.media_refs,
			message_id=it.message_id,
		)
		if started:
			with self._lock:
				self._batches_delivered += 1
				self._items_delivered += 1
				self._tokens_est += max(1, len(it.text) // 4)
			return
		self._requeue_failed(session_id, [it])

	def _requeue_failed(self, session_id: str, items: list[InboxItem]) -> None:
		"""投递失败：把 items 放回队首（保持顺序）并递增 attempts。

		2026-09-05 修正：回填时恢复 state（delivering → queued/stuck）；超过队列
		上限时**保数据不丢**（回队优先于限流）并告警——失败回放不该静默丢消息。
		"""
		with self._lock:
			q = self._queues.setdefault(session_id, [])
			for it in items:
				it.attempts += 1
				it.state = "stuck" if it.attempts >= _max_attempts() else "queued"
			q[:0] = items
			if len(q) > _max_queued():
				_logger.warning(
					"inbox requeue over limit sid=%s len=%s limit=%s",
					session_id,
					len(q),
					_max_queued(),
				)
		_logger.warning(
			"inbox submit rejected sid=%s count=%s", session_id, len(items)
		)

	def shutdown(self) -> None:
		"""app lifespan teardown：作废全部在途排水 + 清队列（仅内存）。"""
		with self._lock:
			tasks = list(self._drain_tasks.values())
			self._drain_tasks.clear()
			self._queues.clear()
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
	"InboxTextTooLong",
	"get_inbox_registry",
]
