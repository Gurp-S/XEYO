"""Product adapters for the engine's narrow runtime-service ports.

Registry ownership stays in the product layer. Late resolution preserves the
existing registry lifecycle and reset hooks without importing HTTP into core.
"""
from __future__ import annotations

from typing import Any
from engine.runtime_services import RuntimeServices
from tools.host_services import ToolHostServices
from server.tool_services import product_job_registry, ProductSessionActivity


class ProductJobs:
    def snapshot_list(self, session_id: str) -> list[dict[str, Any]]:
        return product_job_registry().snapshot_list(session_id)


class ProductInbox:
    def consume_for_boundary(self, session_id: str) -> list[Any]:
        from server.inbox_registry import get_inbox_registry
        return get_inbox_registry().consume_for_boundary(session_id)

    def restore_front(self, session_id: str, items: list[Any]) -> None:
        from server.inbox_registry import get_inbox_registry
        get_inbox_registry().restore_front(session_id, items)

    def _finish_delivering(self, session_id: str, items: list[Any]) -> None:
        from server.inbox_registry import get_inbox_registry
        get_inbox_registry()._finish_delivering(session_id, items)


def product_runtime_services(*, pool: Any = None) -> RuntimeServices:
    jobs = ProductJobs()
    return RuntimeServices(jobs=jobs, inbox=ProductInbox(),
                           tools=ToolHostServices(jobs=product_job_registry, sessions=ProductSessionActivity(pool)))
