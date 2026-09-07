"""Ambient rewind context propagated through one async agent turn."""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from rewind.journal import OperationJournal
from rewind.models import OperationRecord, SnapshotManifest
from rewind.snapshot import SnapshotStore


_CURRENT: contextvars.ContextVar["RewindExecutionContext | None"] = contextvars.ContextVar(
    "xeyo_rewind_context", default=None
)


@dataclass
class RewindExecutionContext:
    """Turn-scoped state used by mutating tools.

    The object is intentionally small and can be propagated to concurrently
    executed tool tasks through ``contextvars``.  Operation IDs are collected
    in call-completion order; the journal itself remains the source of truth.
    """

    session_id: str
    turn_id: str
    revision_id: str | None
    journal: OperationJournal
    snapshots: SnapshotStore
    operation_ids: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.journal.enabled and self.snapshots.enabled

    def record_file_mutation(
        self,
        *,
        tool_name: str,
        operation_type: str,
        path: str,
        old_content: str,
        new_content: str,
        existed_before: bool,
        metadata: dict[str, Any] | None = None,
    ) -> OperationRecord | None:
        """Persist hashes/snapshot references for one successful file mutation."""

        if not self.enabled:
            return None
        before_manifest: SnapshotManifest | None = None
        if existed_before:
            before_manifest = self.snapshots.put_text(
                old_content,
                source_path=path,
                metadata={"role": "before", **dict(metadata or {})},
            )
        after_manifest = self.snapshots.put_text(
            new_content,
            source_path=path,
            metadata={"role": "after", **dict(metadata or {})},
        )
        if after_manifest is None or (existed_before and before_manifest is None):
            raise RuntimeError("rewind snapshot persistence failed")

        record = self.journal.start_operation(
            turn_id=self.turn_id,
            revision_id=self.revision_id,
            tool_name=tool_name,
            operation_type=operation_type,
            path=os.path.abspath(path),
            before_hash=before_manifest.content_hash if before_manifest else None,
            after_hash=after_manifest.content_hash,
            inverse_kind="restore_snapshot" if existed_before else "delete_file",
            inverse_payload={
                "file_existed_before": existed_before,
                "before_snapshot_id": before_manifest.snapshot_id if before_manifest else None,
                "before_content_hash": before_manifest.content_hash if before_manifest else None,
                "after_snapshot_id": after_manifest.snapshot_id,
                "after_content_hash": after_manifest.content_hash,
            },
            metadata=dict(metadata or {}),
        )
        if record is None:
            raise RuntimeError("rewind operation journal is disabled")
        completed = self.journal.transition_operation(record.operation_id, "completed")
        if completed is None:
            raise RuntimeError("rewind operation transition was not persisted")
        self.operation_ids.append(completed.operation_id)
        return completed


@contextmanager
def bind_context(context: RewindExecutionContext | None) -> Iterator[None]:
    token = _CURRENT.set(context)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_context() -> RewindExecutionContext | None:
    return _CURRENT.get()


__all__ = ["RewindExecutionContext", "bind_context", "current_context"]
