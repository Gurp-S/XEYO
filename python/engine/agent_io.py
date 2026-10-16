"""Wait for in-flight blocking operations before releasing their ownership."""
import asyncio


async def owned_io(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    value, cancelled = await wait_owned(task)
    if cancelled:
        raise asyncio.CancelledError
    return value


async def wait_owned(task):
    """Drain an owned task even under repeated cancellation; report cancellation."""
    cancelled = False
    while True:
        try:
            value = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled = True
            if task.done():
                value = task.result()
                break
    return value, cancelled
