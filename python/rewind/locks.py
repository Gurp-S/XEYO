from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager


class LeaseError(RuntimeError):
    """Raised when a session/workspace lease is invalid or expired."""


class LeaseBusyError(LeaseError):
    """Raised when another request currently owns the lease."""


@dataclass(frozen=True)
class Lease:
    lease_id: str
    resource: str
    owner: str
    acquired_at: float
    expires_at: float


@dataclass
class _LeaseState:
    lock: threading.RLock
    lease: Lease | None = None


_STATES: dict[str, _LeaseState] = {}
_STATES_GUARD = threading.Lock()


def _state_for(resource: str) -> _LeaseState:
    with _STATES_GUARD:
        state = _STATES.get(resource)
        if state is None:
            state = _LeaseState(lock=threading.RLock())
            _STATES[resource] = state
        return state


class ResourceLease:
    """A short-lived process-local lease for one logical resource."""

    def __init__(self, state: _LeaseState, lease: Lease) -> None:
        self._state = state
        self.lease = lease
        self._released = False

    def validate(self) -> Lease:
        if self._released:
            raise LeaseError("lease has already been released")
        if time.time() >= self.lease.expires_at:
            raise LeaseError("lease has expired")
        current = self._state.lease
        if current is None or current.lease_id != self.lease.lease_id:
            raise LeaseError("lease is no longer current")
        return self.lease

    def release(self) -> None:
        if self._released:
            return
        with self._state.lock:
            current = self._state.lease
            if current is not None and current.lease_id == self.lease.lease_id:
                self._state.lease = None
                try:
                    self._state.lock.release()
                except RuntimeError:
                    # Defensive: a failed acquisition or process shutdown must
                    # not turn cleanup into a second failure.
                    pass
        self._released = True

    def __enter__(self) -> "ResourceLease":
        self.validate()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class ResourceLeaseManager:
    """Non-reentrant lease manager with bounded TTL and token validation."""

    def __init__(self, resource: str, *, owner: str, ttl_seconds: float = 300.0) -> None:
        normalized = str(resource or "").strip()
        if not normalized:
            raise ValueError("resource is required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.resource = normalized
        self.owner = str(owner or "system")
        self.ttl_seconds = float(ttl_seconds)
        self._state = _state_for(normalized)

    def acquire(self, *, blocking: bool = False, timeout: float = 0.0) -> ResourceLease:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        if blocking and timeout > 0:
            acquired = self._state.lock.acquire(timeout=timeout)
        else:
            acquired = self._state.lock.acquire(blocking=blocking)
        if not acquired:
            raise LeaseBusyError(f"resource is busy: {self.resource}")
        now = time.time()
        lease = Lease(
            lease_id=f"lease_{uuid.uuid4().hex}",
            resource=self.resource,
            owner=self.owner,
            acquired_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._state.lease = lease
        return ResourceLease(self._state, lease)

    @contextmanager
    def hold(self, *, blocking: bool = False, timeout: float = 0.0) -> Iterator[ResourceLease]:
        lease = self.acquire(blocking=blocking, timeout=timeout)
        try:
            yield lease
        finally:
            lease.release()


class ProcessWorkspaceLock(ResourceLeaseManager):
    """进程内工作区租约（threading.RLock，仅本进程有效）。

    命名注意（T39 去混淆）：跨进程文件锁是
    ``engine.workspace_lock.WorkspaceLock``，两者不可混用。
    rewind 热路径的实际互斥由 SessionPool busy-lease 409 提供，
    本类仅供显式长操作（如 rewind GC）使用。
    """

    def __init__(self, workspace_root: str | Path, *, owner: str, ttl_seconds: float = 300.0) -> None:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"workspace root is not a directory: {root}")
        super().__init__(str(root), owner=owner, ttl_seconds=ttl_seconds)
        self.root = root


# 兼容别名（T39：跨进程版是 engine.workspace_lock.WorkspaceLock）
WorkspaceLock = ProcessWorkspaceLock


class SessionLock(ResourceLeaseManager):
    """Session-scoped lease independent from the chat busy lease."""


__all__ = [
    "Lease",
    "LeaseBusyError",
    "LeaseError",
    "ProcessWorkspaceLock",
    "ResourceLease",
    "ResourceLeaseManager",
    "SessionLock",
    "WorkspaceLock",
]
