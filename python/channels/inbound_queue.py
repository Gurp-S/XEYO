"""微信入站排队：session 忙时暂存，完成后顺序处理。

T39：本队列所有方法为同步、无锁——仅限事件循环线程内调用
（push/pop/pop_idle/clear 由 loop 上的单一消费者访问）。原 __init__
中的 asyncio.Lock 从未被使用（同步方法里也无法使用），已删除。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class QueuedInbound:
	text: str
	images: list[str] = field(default_factory=list)
	peer: str = ""
	ctx: str = ""
	session_id: str = ""


class InboundQueue:
	def __init__(self) -> None:
		self._pending: deque[QueuedInbound] = deque()

	def push(
		self,
		text: str,
		*,
		images: list[str] | None = None,
		peer: str = "",
		ctx: str = "",
		session_id: str = "",
	) -> int:
		t = (text or "").strip()
		imgs = [u for u in (images or []) if u]
		if not t and not imgs:
			return len(self._pending)
		self._pending.append(
			QueuedInbound(
				text=t or "[图片]",
				images=imgs,
				peer=(peer or "").strip(),
				ctx=(ctx or "").strip(),
				session_id=(session_id or "").strip(),
			)
		)
		return len(self._pending)

	def pop(self) -> str | None:
		item = self.pop_item()
		return None if item is None else item.text

	def pop_item(self) -> QueuedInbound | None:
		if not self._pending:
			return None
		return self._pending.popleft()

	def pop_idle(self, is_busy: Callable[[str], bool]) -> QueuedInbound | None:
		"""弹出第一条所属 session 当前不 busy 的消息；busy 的条目留在队列里。"""
		if not self._pending:
			return None
		skipped: deque[QueuedInbound] = deque()
		found: QueuedInbound | None = None
		while self._pending:
			item = self._pending.popleft()
			if found is None and not is_busy(item.session_id or ""):
				found = item
				break
			skipped.append(item)
		skipped.extend(self._pending)
		self._pending = skipped
		return found

	def clear(self) -> None:
		self._pending.clear()

	def __len__(self) -> int:
		return len(self._pending)
