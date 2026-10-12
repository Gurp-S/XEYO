"""Keep a caller-owned pool lease alive during an asynchronous operation."""
import asyncio
from contextlib import asynccontextmanager, suppress


@asynccontextmanager
async def keep_lease(pool, session_id, lease_id):
    def guard():
        if not pool.touch_busy(session_id, lease_id=lease_id):
            raise ValueError("session_ownership_lost")

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            # A stolen lease is reported by the next guarded execution boundary.
            if not pool.touch_busy(session_id, lease_id=lease_id):
                return

    guard()
    task = asyncio.create_task(heartbeat())
    try:
        yield guard
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
