"""Product adapters for tool ports; state remains in existing registries/pools."""
from __future__ import annotations
from typing import Any


def product_job_registry():
    """Resolution is delayed until an operation; it does not create another store."""
    from server.job_registry import get_job_registry
    return get_job_registry()


class ProductSessionActivity:
    def __init__(self, pool: Any = None) -> None:
        self._pool = pool

    def is_busy(self, session_id: str) -> bool:
        pool = self._pool
        if pool is None:
            from server.deps import _pool
            pool = _pool
        return pool.is_busy(session_id)
