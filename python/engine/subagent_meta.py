"""子 agent meta 的跨树写锁（F7）。

meta 文件是「读整表 → 改 → 写整表」的读写环：server 路由（投递/删除）与
engine 消费点（follow-up 退休）都要改它。锁实例必须全仓唯一——两边各持一把
等于没锁。放 engine 层而不是 server 层：server 可以 import engine，反向不允许。
"""

from __future__ import annotations

import threading


class KeyedLocks:
	"""按 key 取的全局锁表：同一资源的读-改-写串行，不同资源不互斥。"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._keys: dict[str, threading.Lock] = {}

	def acquire(self, key: str) -> threading.Lock:
		with self._lock:
			handle = self._keys.get(key)
			if handle is None:
				handle = threading.Lock()
				self._keys[key] = handle
			return handle


META_LOCKS = KeyedLocks()


def meta_lock_key(main_session_id: str, agent_id: str) -> str:
	"""meta 读写环的锁键：一个 (会话, agent) 一把。"""
	return f"{main_session_id}\x00{agent_id}"
