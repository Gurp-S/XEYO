"""Join an agent without confusing worker cancellation with caller cancellation."""
import asyncio

from engine.agent_io import wait_owned


async def wait_for_agent(run, *, foreground):
    try:
        await asyncio.shield(run.started.wait())
        if foreground:
            return await asyncio.shield(run.task)
    except asyncio.CancelledError:
        if run.task.cancelled() and not asyncio.current_task().cancelling():
            from engine.agent_runtime import result
            i = run.identity
            return result({"agent_id": i.agent_id, "attempt_id": i.attempt_id,
                           "state": "cancelled"}, error=True)
        run.abort.abort("parent_cancelled")
        async def cancel_owned():
            await run.started.wait()
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        await wait_owned(asyncio.create_task(cancel_owned()))
        raise
