"""Ordered off-thread writes: cancellation cannot leave a writer behind."""
import asyncio
from functools import partial


async def write_checkpoint(write, *args, **kwargs):
	work = asyncio.create_task(asyncio.to_thread(partial(write, *args, **kwargs)))
	try:
		return await asyncio.shield(work)
	except asyncio.CancelledError:
		# A file write cannot be cancelled. Join it before releasing this turn.
		while not work.done():
			try:
				await asyncio.shield(work)
			except asyncio.CancelledError:
				pass  # Repeated stop requests cannot detach the worker either.
			except Exception:
				break
		if not work.cancelled():
			work.exception()  # Retrieve any write failure while preserving cancellation.
		raise
