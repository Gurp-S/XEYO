"""Host lifetime adapters; short-lived CLI processes own their background work."""
import asyncio

from engine.agent_io import wait_owned


async def attempt_snapshot(session_id):
    from engine.agent_runtime import enabled
    from engine.agent_run_store import AgentRunStore
    if not enabled():
        return set()
    rows = await asyncio.to_thread(lambda: AgentRunStore().list(session_id))
    return {row["attempt"] for row in rows}


async def finish_session(session_id, previous):
    from engine.agent_runtime import _running, cancel_session, enabled
    from engine.agent_run_store import AgentRunStore
    if not enabled():
        return True
    tasks = [run.task for run in tuple(_running.values()) if run.identity.session_id == session_id and run.task]
    if tasks:
        drain = asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.shield(drain)
        except asyncio.CancelledError:
            cancel_session(session_id)
            await wait_owned(drain)
            raise
    rows = await asyncio.to_thread(lambda: AgentRunStore().list(session_id))
    return all(row["state"] == "completed" for row in rows if row["attempt"] not in previous)
