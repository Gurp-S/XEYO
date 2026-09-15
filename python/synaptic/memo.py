"""有界记忆化（确定性加速层）。

为什么需要它：WSC 每次压缩都要对**同一批历史消息**重算「关键词集」「token 长度」
这类纯函数。会话越长、压缩次数越多，重复计算越多——200 回合标准会话的 profile 里
``keywords`` 一项占总耗时约 37%，而它的输入在相邻两轮之间**只多了最后几条消息**。

为什么它是安全的：这些函数都是 ``text -> 值`` 的纯函数，结果只取决于输入。
因此记忆化只改变**速度**，不改变任何数值、顺序或输出字节，确定性口径不受影响
（``tests/wsc/test_invariants.py`` 的逐字节复跑断言仍然成立）。

容量只影响速度：``Memo`` 达到上限后按插入顺序淘汰最老的条目（FIFO），
因此内存有界、行为可预测。缓存**不跨进程、不落盘**，不参与任何报告数字。
"""

from __future__ import annotations

from typing import Any, Callable, Hashable

DEFAULT_CAP = 200_000


class Memo:
	"""定容 FIFO 记忆表。``get_or(key, make)`` 是唯一入口。"""

	__slots__ = ("_cap", "_d", "hits", "misses")

	def __init__(self, cap: int = DEFAULT_CAP) -> None:
		self._cap = max(1, int(cap))
		self._d: dict[Hashable, Any] = {}
		self.hits = 0
		self.misses = 0

	def get_or(self, key: Hashable, make: Callable[[], Any]) -> Any:
		d = self._d
		if key in d:
			self.hits += 1
			return d[key]
		self.misses += 1
		val = make()
		if len(d) >= self._cap:
			# FIFO：dict 保序，弹出最早插入的键（批量淘汰 1/8，摊薄 O(n) 消耗）
			for k in list(d)[: max(1, self._cap // 8)]:
				d.pop(k, None)
		d[key] = val
		return val

	def __len__(self) -> int:
		return len(self._d)

	def clear(self) -> None:
		self._d.clear()
		self.hits = 0
		self.misses = 0
