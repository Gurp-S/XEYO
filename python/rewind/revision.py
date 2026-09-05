"""Session revision persistence and compare-friendly branch operations."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable

from rewind import is_rewind_enabled
from rewind.models import SessionRevision
from session.persistence import default_sessions_dir, safe_session_filename


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if key not in _LOCKS:
            _LOCKS[key] = threading.RLock()
        return _LOCKS[key]


def _session_dir(session_id: str, sessions_dir: Path | None = None) -> Path:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    return (sessions_dir or default_sessions_dir()) / safe_session_filename(sid)


def _append_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock_for(path):
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with _lock_for(path):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        rows.append(value)
        except OSError:
            return []
    return rows


def _latest(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("revision_id") or "")
        if key:
            latest[key] = row
    return list(latest.values())


class RevisionStore:
    """Append-only revision store with explicit feature gating."""

    def __init__(
        self,
        session_id: str,
        *,
        sessions_dir: Path | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.session_id = str(session_id or "").strip()
        if not self.session_id:
            raise ValueError("session_id is required")
        self.sessions_dir = sessions_dir
        self.enabled = is_rewind_enabled() if enabled is None else bool(enabled)

    @property
    def path(self) -> Path:
        return _session_dir(self.session_id, self.sessions_dir) / "revisions.jsonl"

    def append(self, revision: SessionRevision) -> SessionRevision | None:
        if revision.session_id != self.session_id:
            raise ValueError("revision session_id mismatch")
        if not self.enabled:
            return None
        _append_json(self.path, revision.to_dict())
        return revision

    def list(self, *, latest_only: bool = True) -> list[SessionRevision]:
        rows = _read_jsonl(self.path)
        if latest_only:
            rows = _latest(rows)
        revisions = [SessionRevision.from_dict(row) for row in rows]
        return sorted(revisions, key=lambda item: (item.created_at, item.revision_id))

    def get(self, revision_id: str) -> SessionRevision | None:
        for revision in reversed(self.list(latest_only=True)):
            if revision.revision_id == revision_id:
                return revision
        return None

    def head(self) -> SessionRevision | None:
        revisions = [item for item in self.list() if item.status not in {"superseded", "abandoned"}]
        return revisions[-1] if revisions else None

    def create(
        self,
        *,
        parent_revision_id: str | None = None,
        head_turn_id: str | None = None,
        turn_ids: Iterable[str] = (),
        message_ids: Iterable[str] = (),
        status: str = "committed",
        transcript_hash: str | None = None,
        workspace_root: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionRevision | None:
        if parent_revision_id is None:
            parent = self.head()
            parent_revision_id = parent.revision_id if parent else None
        revision = SessionRevision(
            session_id=self.session_id,
            parent_revision_id=parent_revision_id,
            head_turn_id=head_turn_id,
            turn_ids=tuple(str(value) for value in turn_ids),
            message_ids=tuple(str(value) for value in message_ids),
            status=status,
            transcript_hash=transcript_hash,
            workspace_root=workspace_root,
            metadata=dict(metadata or {}),
        )
        return self.append(revision)

    def commit_turn(
        self,
        turn_id: str,
        *,
        message_ids: Iterable[str] = (),
        parent_revision_id: str | None = None,
        transcript_hash: str | None = None,
        workspace_root: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionRevision | None:
        parent = self.get(parent_revision_id) if parent_revision_id else self.head()
        turn_ids = list(parent.turn_ids) if parent else []
        message_list = list(parent.message_ids) if parent else []
        if turn_id not in turn_ids:
            turn_ids.append(turn_id)
        for message_id in message_ids:
            if message_id not in message_list:
                message_list.append(message_id)
        return self.create(
            parent_revision_id=parent.revision_id if parent else None,
            head_turn_id=turn_id,
            turn_ids=turn_ids,
            message_ids=message_list,
            transcript_hash=transcript_hash,
            workspace_root=workspace_root,
            metadata=metadata,
        )

    def truncate_to(
        self,
        target_revision_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SessionRevision:
        """Create a new head containing exactly the selected target revision.

        Existing records are never deleted.  The new revision is a branch from
        the target and carries a reason in metadata, which makes a later
        rollback auditable and permits recovery if execution fails.
        """

        target = self.get(target_revision_id)
        if target is None:
            raise KeyError(f"revision not found: {target_revision_id}")
        revision = SessionRevision(
            session_id=self.session_id,
            parent_revision_id=target.revision_id,
            head_turn_id=target.head_turn_id,
            turn_ids=target.turn_ids,
            message_ids=target.message_ids,
            status="committed",
            transcript_hash=target.transcript_hash,
            workspace_root=target.workspace_root,
            metadata={
                "operation": "truncate",
                "source_revision_id": target.revision_id,
                **dict(metadata or {}),
            },
        )
        result = self.append(revision)
        if result is None:
            raise RuntimeError("rewind is disabled; cannot create a revision")
        return result


__all__ = ["RevisionStore"]
