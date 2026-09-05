from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock as ThreadLock, Thread, current_thread
from typing import Iterator


class LeaseError(RuntimeError):
    """Raised when a workspace lease is invalid or expired."""


class LeaseBusyError(LeaseError):
    """Raised when another request currently owns the lease."""


@dataclass(frozen=True)
class Lease:
    lease_id: str
    owner: str
    acquired_at: float
    expires_at: float


class WorkspaceLock:
    """Cross-process workspace lease with atomic acquisition and heartbeats.

    The canonical lock file is created with ``O_EXCL`` and is never replaced by
    a contender.  Heartbeats use a lease-specific sidecar file so an old owner
    cannot renew a newer owner's canonical lock after stale-lock reclamation.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        owner: str,
        ttl_seconds: float = 30.0,
        heartbeat_interval: float | None = None,
    ) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"workspace root is not a directory: {self.root}")
        self.owner = str(owner or "").strip()
        if not self.owner:
            raise ValueError("owner is required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.heartbeat_interval = float(
            heartbeat_interval
            if heartbeat_interval is not None
            else min(max(self.ttl_seconds / 3.0, 0.1), 5.0)
        )
        if self.heartbeat_interval <= 0 or self.heartbeat_interval >= self.ttl_seconds:
            raise ValueError("heartbeat_interval must be positive and less than ttl_seconds")

        self.shadow_dir = self.root / ".xy-shadow-git"
        self.shadow_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.shadow_dir / "workspace.lock"
        self._current_lease: Lease | None = None
        self._state_guard = ThreadLock()
        self._heartbeat_stop: Event | None = None
        self._heartbeat_thread: Thread | None = None
        self._heartbeat_error: LeaseError | None = None

    def _heartbeat_path(self, lease_id: str) -> Path:
        return self.shadow_dir / f"workspace.lock.{lease_id}.heartbeat"

    def _read_lease(self) -> Lease | None:
        try:
            data = json.loads(self.lock_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LeaseError("workspace lock is corrupt") from exc

        try:
            lease_id = str(data["lease_id"])
            owner = str(data["owner"])
            acquired_at = float(data["acquired_at"])
            if not lease_id or not owner:
                raise ValueError("empty lease identity")
        except (KeyError, TypeError, ValueError) as exc:
            raise LeaseError("workspace lock has an invalid payload") from exc

        heartbeat = self._heartbeat_path(lease_id)
        try:
            heartbeat_mtime = heartbeat.stat().st_mtime
        except FileNotFoundError as exc:
            raise LeaseError("workspace lock heartbeat is missing") from exc
        except OSError as exc:
            raise LeaseError("workspace lock heartbeat cannot be read") from exc

        # 过期时间由心跳推导，而不是来自可变的规范
        # 载荷。这防止旧持有者覆盖新持有者的锁。
        return Lease(
            lease_id=lease_id,
            owner=owner,
            acquired_at=acquired_at,
            expires_at=heartbeat_mtime + self.ttl_seconds,
        )

    def _lock_file_is_stale(self) -> bool:
        try:
            return (time.time() - self.lock_file.stat().st_mtime) >= self.ttl_seconds
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def _reclaim_stale(self, lease: Lease | None) -> bool:
        if lease is not None and time.time() < lease.expires_at:
            return False
        # lease 为 None 说明锁文件已损坏（解析失败）。
        # 此时依据文件 mtime 判断是否足够陈旧、可以回收。
        if lease is None and not self._lock_file_is_stale():
            return False

        heartbeat = self._heartbeat_path(lease.lease_id) if lease is not None else None
        try:
            self.lock_file.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if heartbeat is not None:
            try:
                heartbeat.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        return True

    def _create_lease(self, lease: Lease) -> None:
        heartbeat = self._heartbeat_path(lease.lease_id)
        heartbeat_fd: int | None = None
        lock_fd: int | None = None
        created_lock = False
        created_heartbeat = False
        try:
            heartbeat_fd = os.open(
                str(heartbeat), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            created_heartbeat = True
            with os.fdopen(heartbeat_fd, "wb") as handle:
                heartbeat_fd = None
                handle.write(b"heartbeat\n")
                handle.flush()
                os.fsync(handle.fileno())

            payload = json.dumps(
                {
                    "lease_id": lease.lease_id,
                    "owner": lease.owner,
                    "acquired_at": lease.acquired_at,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            lock_fd = os.open(
                str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            created_lock = True
            with os.fdopen(lock_fd, "wb") as handle:
                lock_fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if heartbeat_fd is not None:
                os.close(heartbeat_fd)
            if lock_fd is not None:
                os.close(lock_fd)
            if created_lock:
                try:
                    self.lock_file.unlink()
                except FileNotFoundError:
                    pass
            if created_heartbeat:
                try:
                    heartbeat.unlink()
                except FileNotFoundError:
                    pass
            raise

    def _start_heartbeat(self) -> None:
        stop = Event()
        self._heartbeat_stop = stop
        self._heartbeat_error = None
        thread = Thread(target=self._heartbeat_loop, args=(stop,), daemon=True)
        self._heartbeat_thread = thread
        thread.start()

    def _heartbeat_loop(self, stop: Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            try:
                self.renew()
            except LeaseError as exc:
                with self._state_guard:
                    self._heartbeat_error = exc
                return

    def reclaim_stale_if_expired(self) -> bool:
        """Remove an expired workspace lock left by a crashed owner."""
        try:
            existing = self._read_lease()
        except LeaseError:
            return self._reclaim_stale(None)
        return self._reclaim_stale(existing)

    def acquire(self, *, blocking: bool = False, timeout: float = 0.0) -> Lease:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        with self._state_guard:
            if self._current_lease is not None:
                raise LeaseError("workspace lock is already held by this instance")

        deadline = time.monotonic() + timeout
        while True:
            lease: Lease | None = None
            try:
                existing = self._read_lease()
            except LeaseError:
                if self._reclaim_stale(None):
                    continue
                if not blocking or time.monotonic() >= deadline:
                    raise LeaseBusyError("workspace lock is corrupt or unavailable")
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                continue

            if existing is not None:
                if self._reclaim_stale(existing):
                    continue
                if not blocking or time.monotonic() >= deadline:
                    raise LeaseBusyError(f"workspace is busy, owned by {existing.owner}")
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                continue

            now = time.time()
            lease = Lease(
                lease_id=f"lease_{uuid.uuid4().hex}",
                owner=self.owner,
                acquired_at=now,
                expires_at=now + self.ttl_seconds,
            )
            try:
                self._create_lease(lease)
            except FileExistsError:
                if not blocking or time.monotonic() >= deadline:
                    raise LeaseBusyError("workspace became busy during acquisition")
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                continue

            with self._state_guard:
                self._current_lease = lease
                self._start_heartbeat()
            return lease

    def renew(self) -> Lease:
        with self._state_guard:
            lease = self._current_lease
        if lease is None:
            raise LeaseError("workspace lock is not held by this instance")

        current = self._read_lease()
        if current is None or current.lease_id != lease.lease_id or current.owner != lease.owner:
            raise LeaseError("workspace lock ownership was lost")
        heartbeat = self._heartbeat_path(lease.lease_id)
        try:
            os.utime(heartbeat, None)
        except OSError as exc:
            raise LeaseError("workspace lock heartbeat renewal failed") from exc
        renewed = replace(lease, expires_at=time.time() + self.ttl_seconds)
        with self._state_guard:
            if self._current_lease is None or self._current_lease.lease_id != lease.lease_id:
                raise LeaseError("workspace lock ownership was lost")
            self._current_lease = renewed
        return renewed

    def release(self) -> None:
        with self._state_guard:
            lease = self._current_lease
            stop = self._heartbeat_stop
            thread = self._heartbeat_thread
            self._current_lease = None
            self._heartbeat_stop = None
            self._heartbeat_thread = None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(self.heartbeat_interval, 0.1))
        if lease is None:
            return

        try:
            current = self._read_lease()
        except LeaseError:
            current = None
        if current is not None and current.lease_id == lease.lease_id and current.owner == lease.owner:
            try:
                self.lock_file.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        try:
            self._heartbeat_path(lease.lease_id).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    @contextmanager
    def hold(self, *, blocking: bool = False, timeout: float = 0.0) -> Iterator[Lease]:
        lease = self.acquire(blocking=blocking, timeout=timeout)
        try:
            yield lease
        finally:
            self.release()
