"""Durable data contracts for enterprise rewind.

These models deliberately contain metadata and content-addressed references,
not raw file bodies.  File bodies belong to a snapshot store introduced by the
operation-integration phase.  Keeping the contracts as dataclasses makes them
compatible with XEYO's existing JSONL persistence style without coupling the
backend to Pydantic or the GUI.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping, TypeVar


T = TypeVar("T", bound="JsonModel")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> float:
    return time.time()


def _as_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None)
    return ()


class JsonModel:
    """Small common protocol for JSONL-backed dataclasses."""

    _tuple_fields: ClassVar[frozenset[str]] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import fields

        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, JsonModel):
                value = value.to_dict()
            elif isinstance(value, list):
                value = [v.to_dict() if isinstance(v, JsonModel) else v for v in value]
            elif isinstance(value, dict):
                value = {
                    k: (v.to_dict() if isinstance(v, JsonModel) else v)
                    for k, v in value.items()
                }
            result[item.name] = value
        return result

    @classmethod
    def from_dict(cls: type[T], raw: Mapping[str, Any]) -> T:
        """Construct a model while tolerating fields added by newer versions."""

        from dataclasses import fields

        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in raw.items() if key in known}
        for name in cls._tuple_fields:
            values[name] = _as_tuple(values.get(name))
        return cls(**values)  # type: ignore[arg-type]


@dataclass
class SessionRevision(JsonModel):
    """Immutable logical point-in-time view of a session transcript."""

    session_id: str
    revision_id: str = field(default_factory=lambda: _new_id("rev"))
    parent_revision_id: str | None = None
    created_at: float = field(default_factory=_now)
    status: str = "committed"
    head_turn_id: str | None = None
    turn_ids: tuple[str, ...] = ()
    message_ids: tuple[str, ...] = ()
    transcript_hash: str | None = None
    workspace_root: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _tuple_fields: ClassVar[frozenset[str]] = frozenset({"turn_ids", "message_ids"})


@dataclass
class TurnRecord(JsonModel):
    """One user submission and all model/tool work caused by it."""

    session_id: str
    turn_id: str = field(default_factory=lambda: _new_id("turn"))
    revision_id: str | None = None
    user_message_id: str | None = None
    started_at: float = field(default_factory=_now)
    ended_at: float | None = None
    status: str = "running"
    message_ids: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    assistant_message_id: str | None = None
    stop_reason: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _tuple_fields: ClassVar[frozenset[str]] = frozenset({"message_ids", "operation_ids"})


@dataclass
class OperationRecord(JsonModel):
    """A tool-side mutation or a non-mutating operation observed in a turn.

    ``inverse_payload`` contains only references and parameters necessary to
    reverse the operation.  It must never be populated with complete file
    contents; content-addressed snapshot references are used instead.
    """

    session_id: str
    operation_id: str = field(default_factory=lambda: _new_id("op"))
    turn_id: str | None = None
    revision_id: str | None = None
    tool_name: str = ""
    operation_type: str = "unknown"
    path: str | None = None
    started_at: float = field(default_factory=_now)
    completed_at: float | None = None
    status: str = "started"
    before_hash: str | None = None
    after_hash: str | None = None
    inverse_kind: str | None = None
    inverse_payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SnapshotManifest(JsonModel):
    """Metadata for a content-addressed workspace snapshot."""

    session_id: str
    content_hash: str
    snapshot_id: str = field(default_factory=lambda: _new_id("snap"))
    created_at: float = field(default_factory=_now)
    size_bytes: int = 0
    encoding: str = "utf-8"
    line_endings: str = "LF"
    source_path: str | None = None
    storage_path: str | None = None
    content_kind: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackPlan(JsonModel):
    """Dry-run result bound to a source revision and immutable plan hash."""

    session_id: str
    plan_id: str = field(default_factory=lambda: _new_id("plan"))
    source_revision_id: str | None = None
    target_turn_id: str | None = None
    generated_at: float = field(default_factory=_now)
    plan_hash: str = ""
    operation_ids: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    requires_confirmation: bool = True
    status: str = "preview"
    metadata: dict[str, Any] = field(default_factory=dict)

    _tuple_fields: ClassVar[frozenset[str]] = frozenset({"operation_ids", "conflicts"})


@dataclass
class ApprovalRecord(JsonModel):
    """Explicit approval or rejection for one exact rollback plan hash."""

    session_id: str
    plan_id: str
    plan_hash: str
    approval_id: str = field(default_factory=lambda: _new_id("approval"))
    actor: str = "user"
    decision: str = "pending"
    created_at: float = field(default_factory=_now)
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryJob(JsonModel):
    """Durable, idempotency-addressable rollback execution state."""

    session_id: str
    plan_id: str
    job_id: str = field(default_factory=lambda: _new_id("recovery"))
    idempotency_key: str | None = None
    status: str = "queued"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    applied_operation_ids: tuple[str, ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _tuple_fields: ClassVar[frozenset[str]] = frozenset({"applied_operation_ids"})


@dataclass
class AuditEvent(JsonModel):
    """Append-only audit entry for preview, approval, execution and recovery."""

    session_id: str
    event_type: str
    audit_id: str = field(default_factory=lambda: _new_id("audit"))
    created_at: float = field(default_factory=_now)
    actor: str = "system"
    revision_id: str | None = None
    turn_id: str | None = None
    operation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ApprovalRecord",
    "AuditEvent",
    "OperationRecord",
    "RecoveryJob",
    "RollbackPlan",
    "SessionRevision",
    "SnapshotManifest",
    "TurnRecord",
]
