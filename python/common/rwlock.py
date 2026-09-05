"""asyncio 读写锁（T2）：读共享、写独占、写优先。

- 读者并发持有读锁；写者独占。
- **写优先**：有写者在排队时，新到达的读者等待，避免写者饿死。
- 无内部线程；仅限同一事件循环内使用（工具编排为纯 asyncio 场景）。
"""

from __future__ import annotations

import asyncio


class _Release:
	__slots__ = ("_lock", "_write")

	def __init__(self, lock: "RWLock", write: bool) -> None:
		self._lock = lock
		self._write = write

	async def __aenter__(self) -> None:
		if self._write:
			await self._lock.acquire_write()
		else:
			await self._lock.acquire_read()

	async def __aexit__(self, *_exc: object) -> None:
		if self._write:
			await self._lock.release_write()
		else:
			await self._lock.release_read()


class RWLock:
	"""asyncio 读写锁；``read_lock()`` / ``write_lock()`` 返回异步上下文管理器。"""

	def __init__(self) -> None:
		self._cond = asyncio.Condition()
		self._readers = 0
		self._writing = False
		self._waiting_writers = 0

	async def acquire_read(self) -> None:
		async with self._cond:
			await self._cond.wait_for(
				lambda: not self._writing and self._waiting_writers == 0
			)
			self._readers += 1

	async def release_read(self) -> None:
		async with self._cond:
			self._readers = max(0, self._readers - 1)
			self._cond.notify_all()

	async def acquire_write(self) -> None:
		async with self._cond:
			self._waiting_writers += 1
			try:
				await self._cond.wait_for(
					lambda: not self._writing and self._readers == 0
				)
			finally:
				self._waiting_writers -= 1
			self._writing = True

	async def release_write(self) -> None:
		async with self._cond:
			self._writing = False
			self._cond.notify_all()

	def read_lock(self) -> _Release:
		return _Release(self, write=False)

	def write_lock(self) -> _Release:
		return _Release(self, write=True)
