"""Cooperative script cancellation and owned child settlement."""
import asyncio
import sys


def run_checked(function, prepared, runtime):
    runtime._script_filename = prepared.code.co_filename
    return checked_call(function, runtime, prepared, runtime)


def checked_call(function, runtime, *args):
    previous = sys.gettrace()
    filename = getattr(runtime, "_script_filename", "")
    def check(frame, event, arg):
        if frame.f_code.co_filename == filename:
            runtime._check_abort()
        return check
    sys.settrace(check)
    try:
        return function(*args)
    finally:
        sys.settrace(previous)


async def run_owned(function, prepared, runtime, timeout):
    task = asyncio.create_task(asyncio.to_thread(run_checked, function, prepared, runtime))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    finally:
        runtime._abort.abort("workflow_finished")
        # The worker observes abort while waiting on agents and at script lines.
        # Its child coroutines finish cancellation before this tool releases scope.
        from engine.agent_io import wait_owned
        await wait_owned(asyncio.gather(task, return_exceptions=True))
        await wait_owned(asyncio.gather(*tuple(runtime._tasks), return_exceptions=True))
