"""Only a bounded leading read batch may run ahead of the model stream."""
import asyncio

from tools.base_tool import tool_flag
from tools.orchestration import _max_concurrency


class EarlyReadExecutor:
    def __init__(self, registry):
        self.registry = registry
        self._prefix_open = True
        self._slots = asyncio.Semaphore(_max_concurrency())

    def admit(self, use) -> bool:
        tool = self.registry.get(use.name)
        if not (tool_flag(tool, "is_read_only", default=False)
                and tool_flag(tool, "is_concurrency_safe", default=False)):
            self._prefix_open = False
        return self._prefix_open

    async def run_one(self, runner, use, abort, **kwargs):
        async with self._slots:
            abort.raise_if_aborted()
            return await runner.run_one(use, abort, **kwargs)

    async def run_late(self, runner, uses, early, abort, **kwargs):
        # The prefix and the ordinary partitioned executor share one order.
        if early:
            await asyncio.gather(*early.values())
        abort.raise_if_aborted()
        return await runner.run_batch(uses, abort, **kwargs)
