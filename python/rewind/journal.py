"""Append-only operation and turn journal.

The journal uses one JSON object per line and writes a complete state image for
each transition.  Readers fold records by stable id and therefore retain an
audit-friendly history while exposing the latest safe state to services.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable, TypeVar

from rewind import is_rewind_enabled
from rewind.models import AuditEvent, OperationRecord, TurnRecord
from session.persistence import default_sessions_dir, safe_session_filename


M = TypeVar("M", OperationRecord, TurnRecord, AuditEvent)

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


_OPERATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "started": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
_TURN_TRANSITIONS: dict[str, frozenset[str]] = {
    "running": frozenset({"committed", "failed", "aborted"}),
    "committed": frozenset(),
    "failed": frozenset(),
    "aborted": frozenset(),
}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _session_dir(session_id: str, sessions_dir: Path | None = None) -> Path:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    return (sessions_dir or default_sessions_dir()) / safe_session_filename(sid)


def _jsonl_path(session_id: str, filename: str, sessions_dir: Path | None = None) -> Path:
    return _session_dir(session_id, sessions_dir) / filename


def _fsync_enabled() -> bool:
    """每次 append 后 fsync；默认关闭（flush 已保证进程内顺序完整，读端本就
    容忍 partial line）。审计要求落盘即持久时设 XEYO_REWIND_FSYNC=1。"""
    raw = os.environ.get("XEYO_REWIND_FSYNC", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _append_json(path: Path, payload: dict[str, Any]) -> None:
    """Append one event; a partial write must not be silently hidden."""

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock_for(path):
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
            if _fsync_enabled():
                os.fsync(handle.fileno())
    _invalidate_read_cache(path)


# (path, mtime_ns, size) → 解析后的行。transition_* 每次都要 get_* 最新记录，
# 无缓存时长会话每次全量重读 JSONL，开销随操作数线性恶化。
_READ_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
_READ_CACHE_GUARD = threading.Lock()


def _invalidate_read_cache(path: Path) -> None:
    key = str(path)
    with _READ_CACHE_GUARD:
        for k in [k for k in _READ_CACHE if k[0] == key]:
            _READ_CACHE.pop(k, None)


def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            # 进程被杀可能留下最后一行残页：解析失败的行直接跳过即可，
            # 无需（也不应该）为每个坏行重新打开文件数总行数。
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        st = path.stat()
    except OSError:
        return []
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _READ_CACHE_GUARD:
        cached = _READ_CACHE.get(key)
    if cached is not None:
        return cached
    rows = _parse_jsonl(path)
    with _READ_CACHE_GUARD:
        if len(_READ_CACHE) > 64:
            _READ_CACHE.clear()
        _READ_CACHE[key] = rows
    return rows


def _latest(rows: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = str(row.get(key) or "")
        if identifier:
            latest[identifier] = row
    return list(latest.values())


class OperationJournal:
    """Durable journal for turns, operations and audit events.

    ``enabled`` defaults to ``XEYO_REWIND_ENABLED``.  Explicitly passing
    ``enabled=True`` is useful for isolated tests and administrative tools.
    """

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
    def operations_path(self) -> Path:
        return _jsonl_path(self.session_id, "operations.jsonl", self.sessions_dir)

    @property
    def turns_path(self) -> Path:
        return _jsonl_path(self.session_id, "turns.jsonl", self.sessions_dir)

    @property
    def audit_path(self) -> Path:
        return _jsonl_path(self.session_id, "audit.jsonl", self.sessions_dir)

    def append_operation(self, record: OperationRecord) -> OperationRecord | None:
        self._check_session(record.session_id)
        if not self.enabled:
            return None
        _append_json(self.operations_path, record.to_dict())
        return record

    def start_operation(self, **kwargs: Any) -> OperationRecord | None:
        return self.append_operation(
            OperationRecord(session_id=self.session_id, status="started", **kwargs)
        )

    def transition_operation(
        self,
        operation_id: str,
        status: str,
        *,
        error: str | None = None,
        completed_at: float | None = None,
        **updates: Any,
    ) -> OperationRecord | None:
        current = self.get_operation(operation_id)
        if current is None:
            raise KeyError(f"operation not found: {operation_id}")
        self._check_session(current.session_id)
        allowed = _OPERATION_TRANSITIONS.get(current.status, frozenset())
        if status != current.status and status not in allowed:
            raise ValueError(f"invalid operation transition {current.status!r} -> {status!r}")
        current.status = status
        current.error = error if error is not None else current.error
        current.completed_at = completed_at or (time.time() if status != "started" else None)
        for key, value in updates.items():
            if not hasattr(current, key):
                raise ValueError(f"unknown operation field: {key}")
            setattr(current, key, value)
        return self.append_operation(current)

    def list_operations(
        self,
        *,
        turn_id: str | None = None,
        status: str | None = None,
        latest_only: bool = True,
    ) -> list[OperationRecord]:
        rows = _read_jsonl(self.operations_path)
        if latest_only:
            rows = _latest(rows, "operation_id")
        records = [OperationRecord.from_dict(row) for row in rows]
        if turn_id is not None:
            records = [item for item in records if item.turn_id == turn_id]
        if status is not None:
            records = [item for item in records if item.status == status]
        return sorted(records, key=lambda item: (item.started_at, item.operation_id))

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        for item in reversed(self.list_operations(latest_only=True)):
            if item.operation_id == operation_id:
                return item
        return None

    def append_turn(self, record: TurnRecord) -> TurnRecord | None:
        self._check_session(record.session_id)
        if not self.enabled:
            return None
        _append_json(self.turns_path, record.to_dict())
        return record

    def start_turn(self, **kwargs: Any) -> TurnRecord | None:
        return self.append_turn(TurnRecord(session_id=self.session_id, **kwargs))

    def transition_turn(
        self,
        turn_id: str,
        status: str,
        *,
        error: str | None = None,
        ended_at: float | None = None,
        **updates: Any,
    ) -> TurnRecord | None:
        current = self.get_turn(turn_id)
        if current is None:
            raise KeyError(f"turn not found: {turn_id}")
        allowed = _TURN_TRANSITIONS.get(current.status, frozenset())
        if status != current.status and status not in allowed:
            raise ValueError(f"invalid turn transition {current.status!r} -> {status!r}")
        current.status = status
        current.error = error if error is not None else current.error
        current.ended_at = ended_at or (time.time() if status != "running" else None)
        for key, value in updates.items():
            if not hasattr(current, key):
                raise ValueError(f"unknown turn field: {key}")
            setattr(current, key, value)
        return self.append_turn(current)

    def list_turns(self, *, latest_only: bool = True) -> list[TurnRecord]:
        rows = _read_jsonl(self.turns_path)
        if latest_only:
            rows = _latest(rows, "turn_id")
        records = [TurnRecord.from_dict(row) for row in rows]
        return sorted(records, key=lambda item: (item.started_at, item.turn_id))

    def get_turn(self, turn_id: str) -> TurnRecord | None:
        for item in reversed(self.list_turns(latest_only=True)):
            if item.turn_id == turn_id:
                return item
        return None

    def append_audit(self, event: AuditEvent) -> AuditEvent | None:
        self._check_session(event.session_id)
        if not self.enabled:
            return None
        _append_json(self.audit_path, event.to_dict())
        return event

    def audit(
        self,
        event_type: str,
        *,
        actor: str = "system",
        revision_id: str | None = None,
        turn_id: str | None = None,
        operation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent | None:
        return self.append_audit(
            AuditEvent(
                session_id=self.session_id,
                event_type=event_type,
                actor=actor,
                revision_id=revision_id,
                turn_id=turn_id,
                operation_id=operation_id,
                payload=dict(payload or {}),
            )
        )

    def list_audit(self) -> list[AuditEvent]:
        return [AuditEvent.from_dict(row) for row in _read_jsonl(self.audit_path)]

    def _check_session(self, session_id: str) -> None:
        if str(session_id or "").strip() != self.session_id:
            raise ValueError("journal session_id mismatch")


__all__ = ["OperationJournal"]
