"""Shared workspace lease for tool mutations that can overlap rewind restore."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


class WorkspaceMutationBusy(RuntimeError):
    """The shared workspace lease could not be acquired for a tool mutation."""


@contextmanager
def hold_workspace_mutation(
    workspace_root: str | Path,
    *,
    owner: str,
    timeout: float = 0.0,
) -> Iterator[None]:
    from engine.workspace_lock import LeaseError, WorkspaceLock

    lock = WorkspaceLock(workspace_root, owner=owner)
    try:
        lock.acquire(blocking=timeout > 0, timeout=timeout)
    except LeaseError as exc:
        raise WorkspaceMutationBusy("workspace lock is unavailable") from exc

    try:
        yield
    finally:
        lock.release()


__all__ = ["WorkspaceMutationBusy", "hold_workspace_mutation"]
