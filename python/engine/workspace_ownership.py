"""An OS handle fences workspace writers; heartbeat files remain inspection metadata.

Old lease files without an ownership marker retain their TTL migration behavior.
Marked files are reclaimable as soon as their OS handle is obtainable.
"""
import time

from engine.agent_identity import AgentBusy, AgentLease


class WorkspaceOwnership:
    def _owner_handle(self):
        return AgentLease(self.shadow_dir / "owner-locks", "workspace", "mutation")

    def acquire(self, *, blocking=False, timeout=0.0):
        from engine.workspace_lock import LeaseError, LeaseBusyError
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        with self._state_guard:
            if self._process_owner is not None or self._owner_acquiring:
                raise LeaseError("workspace lock is already held by this instance")
            self._owner_acquiring = True
        deadline = time.monotonic() + timeout
        handle = self._owner_handle()
        try:
            while True:
                try:
                    handle.acquire()
                    break
                except AgentBusy as exc:
                    if not blocking or time.monotonic() >= deadline:
                        raise LeaseBusyError("workspace owner is active") from exc
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
            self._process_owner = handle
            return self._acquire_lease(blocking=blocking, timeout=max(0, deadline - time.monotonic()))
        except BaseException:
            self._process_owner = None
            handle.release()
            raise
        finally:
            with self._state_guard:
                self._owner_acquiring = False

    def _reclaim_stale(self, lease):
        if self._process_owner is not None:
            if self._current_lease is not None:
                return False
            return self._reclaim_stale_owned(lease)
        handle = self._owner_handle()
        try:
            handle.acquire()
        except AgentBusy:
            return False
        try:
            return self._reclaim_stale_owned(lease)
        finally:
            handle.release()

    def release(self):
        try:
            self._release_lease()
        finally:
            handle, self._process_owner = self._process_owner, None
            if handle is not None:
                handle.release()
