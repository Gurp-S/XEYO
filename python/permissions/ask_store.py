"""挂起用户提问请求存储（M3 扩展，复用权限骨架）。

与 PendingPermissionStore 同构，但 resume 载荷是用户答案字符串：
- create：保存提问（问题 + 可选选项 / 默认值）与唤醒信号。
- wait：等待用户作答（超时视为未回答）。
- resolve_answer：外部（前端对话框/微信）提交用户答案。
同一 request_id 只能被处理一次。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from permissions.pending_ttl import PENDING_PANEL_TTL_SECONDS


@dataclass
class PendingAsk:
	request_id: str
	session_id: str
	turn_id: str
	question: str
	options: list[str] = field(default_factory=list)
	default: str | None = None
	expires_at: float = 0.0
	created_at: float = 0.0
	resolved: bool = False
	answer: str | None = None
	actor: str = ""


class PendingAskStore:
	"""进程内、按 request_id 索引的挂起提问存储。"""

	def __init__(self, ttl_seconds: float = PENDING_PANEL_TTL_SECONDS) -> None:
		self._ttl = ttl_seconds
		self._items: dict[str, PendingAsk] = {}
		self._events: dict[str, asyncio.Event] = {}

	def create(
		self,
		*,
		session_id: str,
		turn_id: str,
		question: str,
		options: list[str] | None = None,
		default: str | None = None,
		request_id: str | None = None,
	) -> PendingAsk:
		self._prune()
		rid = request_id or uuid.uuid4().hex
		now = time.time()
		item = PendingAsk(
			request_id=rid,
			session_id=session_id,
			turn_id=turn_id,
			question=question,
			options=options or [],
			default=default,
			expires_at=now + self._ttl,
			created_at=now,
		)
		self._items[rid] = item
		self._events[rid] = asyncio.Event()
		return item

	def get(self, request_id: str) -> PendingAsk | None:
		return self._items.get(request_id)

	def pending_for_session(self, session_id: str) -> PendingAsk | None:
		"""返回该会话尚未处理的挂起提问（每会话通常至多一个在途）。"""
		for item in self._items.values():
			if item.session_id == session_id and not item.resolved:
				return item
		return None

	def resolve_answer(self, request_id: str, answer: str, actor: str = "") -> bool:
		item = self._items.get(request_id)
		if item is None or item.resolved:
			return False
		item.resolved = True
		item.answer = answer
		item.actor = actor
		ev = self._events.get(request_id)
		if ev is not None:
			ev.set()
		return True

	def cancel_pending_for_session(
		self, session_id: str, actor: str = "abort"
	) -> int:
		"""把该会话所有未决提问按"已取消"处理并唤醒等待者（interrupt 路径）。"""
		count = 0
		for item in list(self._items.values()):
			if item.session_id != session_id or item.resolved:
				continue
			if self.resolve_answer(item.request_id, answer="", actor=actor):
				count += 1
		return count

	async def wait(
		self, request_id: str, timeout: float | None = None
	) -> PendingAsk | None:
		item = self._items.get(request_id)
		if item is None:
			return None
		if timeout is None:
			timeout = max(0.0, item.expires_at - time.time())
		ev = self._events.get(request_id)
		if ev is not None and not ev.is_set():
			try:
				await asyncio.wait_for(ev.wait(), timeout=timeout)
			except asyncio.TimeoutError:
				pass
		return self._items.get(request_id)

	def _prune(self) -> None:
		now = time.time()
		for rid in (
			r
			for r, it in self._items.items()
			if it.expires_at < now and not it.resolved
		):
			self._items.pop(rid, None)
			self._events.pop(rid, None)


_default_ask_store: PendingAskStore | None = None


def default_ask_store() -> PendingAskStore:
	"""进程级共享挂起提问存储，供所有引擎与 resolve 端点使用。"""
	global _default_ask_store
	if _default_ask_store is None:
		_default_ask_store = PendingAskStore()
	return _default_ask_store
