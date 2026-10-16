"""Explicit per-registry host capabilities; no product lookup or global binding."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol


class WorkspaceGit(Protocol):
    def read_git_status(self, cwd: str) -> dict[str, Any]: ...
    def read_git_log(self, cwd: str, limit: int = 20) -> dict[str, Any]: ...
    def read_git_branches(self, cwd: str) -> dict[str, Any]: ...
    def read_file_diff(self, cwd: str, rel: str) -> dict[str, Any]: ...
    def read_changed_hunks(self, cwd: str) -> dict[str, Any]: ...


class BackgroundJobs(Protocol):
    def start_bash(self, **kwargs: Any) -> tuple[str | None, str]: ...
    def adopt_bash(self, **kwargs: Any) -> tuple[str | None, str]: ...
    def snapshot_list(self, session_id: str) -> list[dict[str, Any]]: ...
    def change_token(self, job_id: str, caller_session_id: str) -> int | None: ...
    def read(self, job_id: str, caller_session_id: str) -> tuple[str, int, str, bool] | None: ...
    async def wait_for_change(self, job_id: str, caller_session_id: str, token: int, *, timeout_s: float) -> int | None: ...
    def kill(self, job_id: str, caller_session_id: str, reason: str = "") -> str: ...


class SessionActivity(Protocol):
    def is_busy(self, session_id: str) -> bool: ...


def _local_git() -> WorkspaceGit:
    from common import workspace_git
    return workspace_git


@dataclass(frozen=True)
class ToolHostServices:
    """Standalone tools retain local Git; jobs and live sessions require a host."""
    git: WorkspaceGit = field(default_factory=_local_git)
    jobs: Callable[[], BackgroundJobs] | None = None
    sessions: SessionActivity | None = None

    def job_registry(self) -> BackgroundJobs | None:
        """Resolve once per operation so an in-flight cursor stays with its owner."""
        return self.jobs() if self.jobs is not None else None


class HostBoundTool:
    """Registry injection also applies to tools registered after construction."""
    def __init__(self, *, host_services: ToolHostServices | None = None) -> None:
        self._host_services = host_services if host_services is not None else ToolHostServices()

    def set_host_services(self, services: ToolHostServices) -> None:
        self._host_services = services
