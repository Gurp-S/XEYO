"""进程内 Plan 模式挂起存储。

Plan 模式由 ExitPlanMode 工具触发：query_loop 创建 pending plan，前端通过
``POST /v1/plan/{turn_id}/approve`` 批准或拒绝，然后由同一事件流恢复执行。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from permissions.pending_ttl import PENDING_PANEL_TTL_SECONDS


@dataclass
class PendingPlan:
	request_id: str
	session_id: str
	turn_id: str
	plan: str
	expires_at: float = 0.0
	created_at: float = 0.0
	resolved: bool = False
	approved: bool | None = None
	actor: str = ""


class PlanEngine:
	"""进程内、按 turn_id 索引的 Plan 确认存储。"""

	def __init__(self, ttl_seconds: float = PENDING_PANEL_TTL_SECONDS) -> None:
		self._ttl = ttl_seconds
		self._items: dict[str, PendingPlan] = {}
		self._events: dict[str, asyncio.Event] = {}

	def create(
		self,
		*,
		session_id: str,
		turn_id: str,
		plan: str,
		request_id: str | None = None,
	) -> PendingPlan:
		self._prune()
		rid = request_id or turn_id or uuid.uuid4().hex
		now = time.time()
		item = PendingPlan(
			request_id=rid,
			session_id=session_id,
			turn_id=turn_id,
			plan=plan,
			expires_at=now + self._ttl,
			created_at=now,
		)
		self._items[rid] = item
		self._events[rid] = asyncio.Event()
		return item

	def get(self, request_id: str) -> PendingPlan | None:
		return self._items.get(request_id)

	def resolve(self, request_id: str, approved: bool, actor: str = "") -> bool:
		item = self._items.get(request_id)
		if item is None or item.resolved:
			return False
		item.resolved = True
		item.approved = approved
		item.actor = actor
		ev = self._events.get(request_id)
		if ev is not None:
			ev.set()
		return True

	def cancel_pending_for_session(self, session_id: str) -> int:
		"""把该会话所有未决 Plan 请求按拒绝处理并唤醒等待者（interrupt 路径）。

		与 permission/ask 同源：wait 挂在 asyncio.Event 上，abort 无法唤醒，
		不取消则回合挂死到面板 TTL。
		"""
		count = 0
		for item in list(self._items.values()):
			if item.session_id != session_id or item.resolved:
				continue
			if self.resolve(item.request_id, approved=False, actor="abort"):
				count += 1
		return count

	async def wait(
		self, request_id: str, timeout: float | None = None
	) -> PendingPlan | None:
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


_default_plan_engine: PlanEngine | None = None


def default_plan_engine() -> PlanEngine:
	"""进程级共享 Plan 存储，供 query_loop 与 API 端点使用。"""
	global _default_plan_engine
	if _default_plan_engine is None:
		_default_plan_engine = PlanEngine()
	return _default_plan_engine
