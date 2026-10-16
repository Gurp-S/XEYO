"""Execution identity and OS-owned leases for delegated agents.

An agent survives attempts. A lease belongs to one attempt and is never stolen
on a timer: a slow process is still an owner. Process death releases the OS lock.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path


@dataclass(frozen=True)
class AgentIdentity:
    session_id: str
    agent_id: str
    attempt_id: str
    created_at: float = 0


current_agent: ContextVar[AgentIdentity | None] = ContextVar("agent_identity", default=None)


class AgentBusy(RuntimeError):
    pass


class AgentLease:
    def __init__(self, directory: Path, session_id: str, agent_id: str):
        key = hashlib.sha256((session_id + "\0" + agent_id).encode()).hexdigest()
        self.path = directory / (key + ".lock")
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise AgentBusy("agent_busy") from exc
        self.handle = handle
        return self

    def release(self):
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


@contextmanager
def child_execution_context(workspace_root, session_id, agent_id):
    """Private mutable facts; shared budget has its own explicit ContextVar."""
    import copy
    from engine.workspace_context import ExecutionContext, bind_workspace_context, get_execution_context
    parent = get_execution_context()
    ctx = copy.deepcopy(parent) if parent is not None else ExecutionContext(session_id, str(workspace_root))
    ctx.session_id = session_id
    ctx.cwd = str(Path(workspace_root).resolve())
    # Worktree access is bounded by this worker's root and its write_scope.
    ctx.allowed_paths = [ctx.cwd]
    ctx.workspace_id = hashlib.sha256(ctx.cwd.encode()).hexdigest()[:20]
    ctx.model_request_id = ""
    ctx.projection_id = ""
    identity = current_agent.get()
    ctx.trace_id = identity.attempt_id if identity else agent_id
    with bind_workspace_context(ctx):
        yield ctx
