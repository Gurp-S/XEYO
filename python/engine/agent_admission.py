"""Admission ownership spans blocking setup and joins the service shutdown barrier."""
import asyncio
from contextlib import contextmanager

from engine.agent_io import wait_owned

_pending: set[asyncio.Task] = set()
_stopping = 0


async def dispatch(function, *args):
    if _stopping:
        from engine.agent_runtime import result
        return result({"error": "agent_runtime_stopping"}, error=True)
    task = asyncio.create_task(function(*args), name="agent-admission")
    _pending.add(task)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.cancel()
        try:
            await wait_owned(task)
        except asyncio.CancelledError:
            pass
        raise
    finally:
        _pending.discard(task)


@contextmanager
def stopping():
    global _stopping
    _stopping += 1
    try:
        yield
    finally:
        _stopping -= 1


async def drain():
    tasks = tuple(_pending)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
