"""Host-owned services injected into one engine; no transport or global lookup."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from tools.host_services import ToolHostServices


class JobSnapshots(Protocol):
    def snapshot_list(self, session_id: str) -> list[dict[str, Any]]: ...


class BoundaryInbox(Protocol):
    def consume_for_boundary(self, session_id: str) -> list[Any]: ...
    def restore_front(self, session_id: str, items: list[Any]) -> None: ...
    def _finish_delivering(self, session_id: str, items: list[Any]) -> None: ...


@dataclass(frozen=True)
class RuntimeServices:
    """An unconfigured embedded engine has no host jobs or queued input.

    Service errors propagate to the existing call-site recovery boundaries.
    Instances are explicit per-engine dependencies, never a process registry.
    """
    jobs: JobSnapshots | None = None
    inbox: BoundaryInbox | None = None
    tools: ToolHostServices = field(default_factory=ToolHostServices)

    def job_snapshots(self, session_id: str) -> list[dict[str, Any]]:
        return self.jobs.snapshot_list(session_id) if self.jobs is not None else []
