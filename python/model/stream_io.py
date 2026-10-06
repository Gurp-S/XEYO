"""Cancellation of request-owned I/O, without cancelling the shared client or caller."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import socket

from engine.abort import Aborted


async def abortable(operation, abort):
    loop = asyncio.get_running_loop()
    stopped = loop.create_future()
    work = asyncio.ensure_future(operation)

    def signal(reason):
        def wake():
            if not stopped.done():
                stopped.set_result(reason)
        loop.call_soon_threadsafe(wake)

    remove_listener = abort.on_abort(signal)
    try:
        abort.raise_if_aborted()
        done, _ = await asyncio.wait((work, stopped), return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return work.result()
        raise Aborted(abort.reason)
    except Exception:
        if abort.aborted:
            raise Aborted(abort.reason) from None
        raise
    finally:
        remove_listener()
        stopped.cancel()
        if not work.done():
            work.cancel()
        await asyncio.gather(work, return_exceptions=True)


async def abortable_lines(lines, abort):
    iterator = lines.__aiter__()
    while True:
        try:
            line = await abortable(iterator.__anext__(), abort)
        except StopAsyncIteration:
            return
        yield line


@asynccontextmanager
async def abortable_stream(context, abort):
    response = await abortable(context.__aenter__(), abort)
    try:
        abort.raise_if_aborted()
        yield response
    finally:
        await context.__aexit__(None, None, None)


@contextmanager
def close_response_on_abort(response, abort):
    def close(reason):
        # urllib's buffered read may hold its lock. Shutdown wakes that read
        # before close takes the same lock; the socket belongs to this response.
        raw = getattr(getattr(response, "fp", None), "raw", None)
        connection = getattr(raw, "_sock", None)
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            response.close()
        except (OSError, ValueError):
            pass

    remove_listener = abort.on_abort(close)
    try:
        abort.raise_if_aborted()
        yield response
    finally:
        remove_listener()


def post_to_loop(loop, callback, *args):
    # A stopped stdlib worker may finish after its caller's loop has closed.
    try:
        loop.call_soon_threadsafe(callback, *args)
    except RuntimeError:
        if not loop.is_closed():
            raise
