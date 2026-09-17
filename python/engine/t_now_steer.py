"""管道 1：运行中用户消息的边界注入（steer）。

语义（对齐 Codex 的 ``turn/steer``，不照抄其 Rust 结构）：

1. **运行中输入** → :func:`push`：先落 transcript（WAL，按 message id 幂等），
   再入内存队列；
2. **到边界**（工具批次完成后 / 下一次采样前）→ :func:`deliver`：追加进
   MessageStore（真 user 消息），此后它就是普通历史：可被引用、可被压缩；
3. **至少一次**：投递失败的项回队等下一边界；已进 store 的同 id 项跳过
   （幂等），因此"重投"不会产生重复消息。

可靠性口径：
- **WAL**：消息一入队就写 transcript ⇒ 进程重启后 hydrate 会把它当普通 user
  消息装载，不会被静默丢掉（代价：UI 可能比"助手看到它"更早看到它——这正是
  用户预期）。
- **不静默淘汰**：LRU 只淘汰**队列为空**的会话；全满时宁可超出会话硬顶也不
  丢排队的消息。
- fail-open 只作用于"入队失败"（返回 False，服务端回落既有排队路径），
  绝不作用于"已入队的消息"。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from msgtypes.message import Message, user_message

_log = logging.getLogger(__name__)

#: 单会话排队硬顶（防误挂/脚本灌爆内存；超限拒绝新条目并返回 False）
MAX_QUEUED_PER_SESSION = 16
#: 会话数硬顶（LRU 只淘汰空队列会话；全非空时允许超出，绝不丢消息）
MAX_SESSIONS = 64


@dataclass
class SteerItem:
	"""一条运行中用户消息（内存态；磁盘态由 transcript 承担 = WAL）。"""

	text: str
	images: list[str] = field(default_factory=list)
	message_id: str = ""
	queued_at: float = field(default_factory=time.time)


_LOCK = threading.Lock()
_QUEUES: dict[str, deque[SteerItem]] = {}


def _message_for(item: SteerItem) -> Message:
	if not item.message_id:
		# ID 必须属于队列项本身：WAL、deliver、重投都复用同一身份。
		item.message_id = uuid.uuid4().hex
	return user_message(
		item.text,
		images=item.images or None,
		message_id=item.message_id or None,
	)


def push(
	session_id: str,
	text: str,
	*,
	images: list[str] | None = None,
	message_id: str = "",
) -> bool:
	"""把运行中用户消息排进队列；返回是否入队（入队失败 → 调用方回落排队）。"""
	sid = (session_id or "").strip()
	body = (text or "").strip()
	if not sid or not body:
		return False
	item = SteerItem(
		text=body,
		images=[str(i) for i in (images or []) if i],
		message_id=(message_id or "").strip() or uuid.uuid4().hex,
	)
	try:
		with _LOCK:
			q = _QUEUES.get(sid)
			if q is None:
				_evict_if_needed()
				q = deque()
				_QUEUES[sid] = q
			else:
				_QUEUES.pop(sid, None)
				_QUEUES[sid] = q  # LRU：触碰置尾
			if len(q) >= MAX_QUEUED_PER_SESSION:
				_log.warning("steer queue full: %s（拒绝新条目）", sid)
				return False
			q.append(item)
	except Exception:  # noqa: BLE001
		_log.debug("steer push failed", exc_info=True)
		return False
	# WAL：入队即落 transcript（按 message id 幂等）——重启后 hydrate 即装载
	_write_wal(sid, item)
	return True


def deliver(session_id: str, store: Any) -> list[Message]:
	"""边界投递：把队列里的运行中用户消息追加进历史（真 user 消息）。

	- 幂等：同 ``message_id`` 已在 store 里 → 跳过（不会重复追加）
	- 至少一次：append 失败的项**回队**，下一边界重投
	- 返回**本次真正追加**的消息（空列表 = 本轮无投递），调用方据此发回执
	"""
	sid = (session_id or "").strip()
	if not sid:
		return []
	try:
		with _LOCK:
			q = _QUEUES.get(sid)
			if not q:
				return []
			items = list(q)
			q.clear()
			_QUEUES.pop(sid, None)
	except Exception:  # noqa: BLE001
		return []
	try:
		existing = {
			str(getattr(m, "id", "") or "") for m in getattr(store, "items", [])
		}
	except Exception:  # noqa: BLE001
		existing = set()
	added: list[Message] = []
	failed: list[SteerItem] = []
	for it in items:
		if it.message_id and it.message_id in existing:
			continue  # 幂等：这条已经在历史里
		try:
			msg = _message_for(it)
			store.append(msg)
			added.append(msg)
		except Exception:  # noqa: BLE001
			_log.debug("steer append failed", exc_info=True)
			failed.append(it)
	if failed:
		_requeue(sid, failed)
	if added:
		try:
			from session.record_transcript import record_transcript_sync

			record_transcript_sync(added, session_id=sid)
		except Exception:  # noqa: BLE001
			_log.debug("steer transcript write failed", exc_info=True)
	return added


def drain(session_id: str) -> list[Message]:
	"""取走该会话全部排队消息并转成 Message（取走即清；供测试/简单调用方）。

	生产路径用 :func:`deliver`（带回队与幂等）。"""
	sid = (session_id or "").strip()
	if not sid:
		return []
	try:
		with _LOCK:
			q = _QUEUES.pop(sid, None) or deque()
			items = list(q)
	except Exception:  # noqa: BLE001
		return []
	out: list[Message] = []
	for it in items:
		try:
			out.append(_message_for(it))
		except Exception:  # noqa: BLE001
			_log.debug("steer item build failed", exc_info=True)
	return out


def pending_count(session_id: str) -> int:
	with _LOCK:
		return len(_QUEUES.get((session_id or "").strip(), ()))


def clear(session_id: str = "") -> None:
	"""清队列（会话销毁 / 回溯 / 测试用）；空串清全部。"""
	sid = (session_id or "").strip()
	with _LOCK:
		if sid:
			_QUEUES.pop(sid, None)
		else:
			_QUEUES.clear()


def _requeue(session_id: str, items: list[SteerItem]) -> None:
	"""投递失败的项回队首（保持原序），等下一边界重投。"""
	if not items:
		return
	try:
		with _LOCK:
			q = _QUEUES.get(session_id)
			if q is None:
				q = deque()
				_QUEUES[session_id] = q
			for it in reversed(items):
				q.appendleft(it)
	except Exception:  # noqa: BLE001
		_log.debug("steer requeue failed", exc_info=True)


def _write_wal(session_id: str, item: SteerItem) -> None:
	"""入队即落 transcript（幂等）：进程重启后这条消息不会凭空消失。"""
	try:
		from session.record_transcript import record_transcript_sync

		record_transcript_sync([_message_for(item)], session_id=session_id)
	except Exception:  # noqa: BLE001 — WAL 失败不影响内存投递
		_log.debug("steer WAL write failed", exc_info=True)


def _evict_if_needed() -> None:
	"""会话数超顶时淘汰**空队列**会话；全非空则允许超出（绝不丢排队消息）。"""
	empty = [sid for sid, q in _QUEUES.items() if not q]
	if len(_QUEUES) < MAX_SESSIONS or not empty:
		return
	for sid in empty[: max(1, len(_QUEUES) - MAX_SESSIONS + 1)]:
		_QUEUES.pop(sid, None)


__all__ = [
	"MAX_QUEUED_PER_SESSION",
	"SteerItem",
	"clear",
	"deliver",
	"drain",
	"pending_count",
	"push",
]
