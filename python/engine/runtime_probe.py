"""Fresh runtime facts without synchronous filesystem work on the event loop."""
import asyncio


async def probe(cwd, *, runtime="local", container_id=""):
    from engine.runtime_capabilities import probe_runtime_capabilities
    return await asyncio.to_thread(probe_runtime_capabilities, cwd,
                                   runtime=runtime, container_id=container_id)
