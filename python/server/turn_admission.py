"""The response owns startup until the detached producer has been installed."""
import anyio


async def start_detached_turn(runner, **request):
    # Starlette cancels the response body's AnyIO scope when the subscriber
    # disconnects. Durable admission contains awaits; cancellation there would
    # leave a busy lease and possibly a running snapshot without a producer.
    with anyio.CancelScope(shield=True):
        return await runner.start(**request)
