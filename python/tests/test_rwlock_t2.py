"""T2 回归：asyncio 读写锁（写优先）+ 工具取消的确定性结果。"""

from __future__ import annotations

import asyncio

import pytest

from common.rwlock import RWLock
from msgtypes.message import ToolUse
from tools.orchestration import _run_one_tool


# ---------- RWLock ----------


@pytest.mark.asyncio
async def test_rwlock_allows_concurrent_readers():
	lock = RWLock()
	active = 0
	peak = 0

	async def _reader() -> None:
		nonlocal active, peak
		async with lock.read_lock():
			active += 1
			peak = max(peak, active)
			await asyncio.sleep(0.01)
			active -= 1

	await asyncio.gather(*[_reader() for _ in range(8)])
	assert peak >= 2  # 读者确实并发
	assert active == 0


@pytest.mark.asyncio
async def test_rwlock_write_excludes_readers():
	lock = RWLock()
	in_write = False
	violations = 0

	async def _reader() -> None:
		nonlocal violations
		async with lock.read_lock():
			if in_write:
				violations += 1
			await asyncio.sleep(0.01)

	async def _writer() -> None:
		nonlocal in_write
		async with lock.write_lock():
			in_write = True
			await asyncio.sleep(0.01)
			in_write = False

	await asyncio.gather(_writer(), *[_reader() for _ in range(6)])
	assert violations == 0


@pytest.mark.asyncio
async def test_rwlock_write_priority_starves_new_readers():
	"""写者排队时新读者必须等待（写优先，防写者饿死）。"""
	lock = RWLock()
	order: list[str] = []
	reader_holding = asyncio.Event()

	async def _holder() -> None:
		async with lock.read_lock():
			reader_holding.set()
			await asyncio.sleep(0.05)
			order.append("holder_done")

	async def _writer() -> None:
		await reader_holding.wait()
		await asyncio.sleep(0.01)  # 确保写者先排队
		await lock.acquire_write()
		order.append("writer")
		await lock.release_write()

	async def _late_reader() -> None:
		await reader_holding.wait()
		await asyncio.sleep(0.02)  # 写者已排队后来
		await lock.acquire_read()
		order.append("late_reader")
		await lock.release_read()

	await asyncio.gather(_holder(), _writer(), _late_reader())
	assert order.index("writer") < order.index("late_reader")


@pytest.mark.asyncio
async def test_rwlock_reentrant_sequential_batches():
	"""连续的读批/写批不互相泄漏（orchestration 每批独立加锁）。"""
	lock = RWLock()
	async with lock.read_lock():
		pass
	async with lock.write_lock():
		pass
	async with lock.read_lock():
		pass  # 写释放后读者立即可进


# ---------- 工具取消 → 确定性结果 ----------


class _HangingRegistry:
	class _Tool:
		@staticmethod
		def is_concurrency_safe() -> bool:
			return True

	def get(self, _name: str):  # noqa: ANN201
		return self._Tool()

	async def run(self, tu, abort, *, coordinator=None):  # noqa: ANN001, ANN202
		await asyncio.sleep(60)


@pytest.mark.asyncio
async def test_cancelled_tool_yields_deterministic_non_error_result():
	from engine.abort import AbortController

	result_q: asyncio.Queue = asyncio.Queue()
	tu = ToolUse(id="t2c", name="Sleep", input={})
	task = asyncio.create_task(
		_run_one_tool(
			_HangingRegistry(), tu, AbortController(), None, None, result_q
		)
	)
	await asyncio.sleep(0.05)
	task.cancel()
	res = await task
	assert res.is_error is False
	assert res.content.startswith("aborted by user after ")
	assert res.content.endswith("s")
	assert res.metadata.get("cancelled") is True
	got_tu, got_res = result_q.get_nowait()
	assert got_tu.id == "t2c" and got_res.content == res.content


@pytest.mark.asyncio
async def test_cancelled_tool_under_write_lock_releases():
	"""取消发生在写锁内：锁释放，后续写者不饿死。"""
	from engine.abort import AbortController

	class _UnsafeRegistry(_HangingRegistry):
		class _Tool:
			@staticmethod
			def is_concurrency_safe() -> bool:
				return False

		def get(self, _name: str):  # noqa: ANN201
			return self._Tool()

	lock = RWLock()
	result_q: asyncio.Queue = asyncio.Queue()
	tu = ToolUse(id="t2w", name="Bash", input={})
	task = asyncio.create_task(
		_run_one_tool(
			_UnsafeRegistry(), tu, AbortController(), None, None, result_q,
			lock=lock,
		)
	)
	await asyncio.sleep(0.05)
	task.cancel()
	res = await task
	assert res.is_error is False
	# 写锁已释放：随后能立刻取得写锁。
	await asyncio.wait_for(lock.acquire_write(), timeout=1.0)
	await lock.release_write()


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
