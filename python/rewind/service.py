from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from rewind.journal import OperationJournal
from engine.workspace_lock import LeaseBusyError, LeaseError, WorkspaceLock
from rewind.locks import SessionLock
from rewind.models import ApprovalRecord, RecoveryJob, RollbackPlan, SessionRevision, TurnRecord
from rewind.revision import RevisionStore
from rewind.snapshot import SnapshotStore
from session.hydrate import messages_from_rows
from session.persistence import (
    default_sessions_dir,
    is_session_persistence_disabled,
    safe_session_filename,
    transcript_path,
)


class RollbackError(RuntimeError):
    """Base class for safe rollback failures."""


class RollbackDisabledError(RollbackError):
    """Raised when durable rewind has not been explicitly enabled."""


class RollbackBlockedError(RollbackError):
    """Raised when the request cannot be proven safe to execute."""


class RollbackConflictError(RollbackBlockedError):
    """Raised when a current resource differs from the preview precondition."""


class RollbackApprovalError(RollbackBlockedError):
    """Raised when explicit approval is missing, expired or mismatched."""


class RollbackIdempotencyError(RollbackError):
    """Raised when an idempotency key is reused for a different plan."""


# Engine transcript roles used by revisions / MessageStore.  UI-only rows such as
# ``ui_thought`` must not participate in revision matching — otherwise a live
# journal head is replaced by a synthetic ``chat_*`` bootstrap and file ops vanish.
_ENGINE_ROLES = frozenset({"user", "assistant", "tool", "system"})


@dataclass(frozen=True)
class _FileState:
    exists: bool
    content_hash: str | None
    is_symlink: bool = False


_PLAN_LOCKS: dict[str, threading.RLock] = {}
_PLAN_LOCKS_GUARD = threading.Lock()


def _plan_lock(session_id: str) -> threading.RLock:
    with _PLAN_LOCKS_GUARD:
        lock = _PLAN_LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _PLAN_LOCKS[session_id] = lock
        return lock


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(encoded)


def _append_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RollbackBlockedError(
                    f"invalid rollback state at {path.name}:{line_no}"
                ) from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _latest_by(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = str(row.get(key) or "")
        if identifier:
            latest[identifier] = dict(row)
    return list(latest.values())


def _safe_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise RollbackBlockedError(f"operation path is outside workspace: {raw_path}")
    return resolved


def _file_state(path: Path) -> _FileState:
    if path.is_symlink():
        return _FileState(False, None, True)
    if not path.exists():
        return _FileState(False, None, False)
    if path.is_dir():
        raise RollbackBlockedError(f"rollback path is a directory: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RollbackBlockedError(f"cannot read rollback path: {path}") from exc
    return _FileState(True, _sha256(data), False)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.rewind.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The file replacement is still atomic; directory fsync is best effort
            # on platforms that do not expose it.
            pass
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class _PlanStore:
    def __init__(self, session_id: str, *, sessions_dir: Path | None = None) -> None:
        self.session_id = session_id
        self.sessions_dir = sessions_dir
        self.path = (
            (sessions_dir or default_sessions_dir())
            / safe_session_filename(session_id)
            / "rollback_plans.jsonl"
        )

    def append(self, plan: RollbackPlan) -> RollbackPlan:
        _append_json(self.path, plan.to_dict())
        return plan

    def latest(self, plan_id: str) -> RollbackPlan | None:
        rows = _latest_by(_read_jsonl(self.path), "plan_id")
        for row in rows:
            if row.get("plan_id") == plan_id:
                return RollbackPlan.from_dict(row)
        return None

    def update(self, plan: RollbackPlan, **updates: Any) -> RollbackPlan:
        for key, value in updates.items():
            if not hasattr(plan, key):
                raise ValueError(f"unknown rollback plan field: {key}")
            setattr(plan, key, value)
        return self.append(plan)


class _ApprovalStore:
    def __init__(self, session_id: str, *, sessions_dir: Path | None = None) -> None:
        self.path = (
            (sessions_dir or default_sessions_dir())
            / safe_session_filename(session_id)
            / "rollback_approvals.jsonl"
        )

    def append(self, approval: ApprovalRecord) -> ApprovalRecord:
        _append_json(self.path, approval.to_dict())
        return approval

    def latest(self, approval_id: str) -> ApprovalRecord | None:
        rows = _latest_by(_read_jsonl(self.path), "approval_id")
        for row in rows:
            if row.get("approval_id") == approval_id:
                return ApprovalRecord.from_dict(row)
        return None


class _RecoveryStore:
    def __init__(self, session_id: str, *, sessions_dir: Path | None = None) -> None:
        self.path = (
            (sessions_dir or default_sessions_dir())
            / safe_session_filename(session_id)
            / "recovery_jobs.jsonl"
        )

    def append(self, job: RecoveryJob) -> RecoveryJob:
        _append_json(self.path, job.to_dict())
        return job

    def list(self) -> list[RecoveryJob]:
        rows = _latest_by(_read_jsonl(self.path), "job_id")
        return [RecoveryJob.from_dict(row) for row in rows]

    def by_idempotency(self, key: str) -> RecoveryJob | None:
        for job in self.list():
            if job.idempotency_key == key:
                return job
        return None

    def latest(self, job_id: str) -> RecoveryJob | None:
        for job in self.list():
            if job.job_id == job_id:
                return job
        return None

    def update(self, job: RecoveryJob, **updates: Any) -> RecoveryJob:
        for key, value in updates.items():
            if not hasattr(job, key):
                raise ValueError(f"unknown recovery job field: {key}")
            setattr(job, key, value)
        job.updated_at = time.time()
        return self.append(job)


class RollbackService:
    """The only backend entry point for previewing and executing a rewind.

    The service never mutates transcript or workspace state during ``preview``.
    ``execute`` requires an exact plan hash, explicit confirmation and an
    idempotency key, then rechecks the revision and file preconditions while
    holding a session lease followed by a workspace lease.
    """

    def __init__(
        self,
        session_id: str,
        workspace_root: str | Path,
        *,
        sessions_dir: Path | None = None,
        enabled: bool | None = None,
        session_busy: Callable[[str], bool] | None = None,
        on_commit: Callable[[str], None] | None = None,
        on_interrupt: Callable[[str], bool] | None = None,
        on_force_idle: Callable[[str], None] | None = None,
        on_acquire_busy: Callable[[str], int | None] | None = None,
        on_release_busy: Callable[[str, int], None] | None = None,
        lease_ttl_seconds: float = 300.0,
        plan_ttl_seconds: float = 900.0,
    ) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"workspace root is not a directory: {root}")
        self.session_id = sid
        self.workspace_root = root
        self.enabled = bool(enabled) if enabled is not None else self._env_enabled()
        self.sessions_dir = sessions_dir
        self.plan_ttl_seconds = max(30.0, float(plan_ttl_seconds))
        self._session_busy = session_busy
        self._on_commit = on_commit
        self._on_interrupt = on_interrupt
        self._on_force_idle = on_force_idle
        self._on_acquire_busy = on_acquire_busy
        self._on_release_busy = on_release_busy
        self._lease_ttl_seconds = max(30.0, float(lease_ttl_seconds))
        self.journal = OperationJournal(sid, sessions_dir=sessions_dir, enabled=self.enabled)
        self.revisions = RevisionStore(sid, sessions_dir=sessions_dir, enabled=self.enabled)
        self.snapshots = SnapshotStore(sid, enabled=self.enabled)
        self.plans = _PlanStore(sid, sessions_dir=sessions_dir)
        self.approvals = _ApprovalStore(sid, sessions_dir=sessions_dir)
        self.jobs = _RecoveryStore(sid, sessions_dir=sessions_dir)
        self.transcript = transcript_path(sid, sessions_dir=sessions_dir)
        self._lock = _plan_lock(sid)

    @staticmethod
    def _env_enabled() -> bool:
        from rewind import is_rewind_enabled

        return is_rewind_enabled()

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RollbackDisabledError(
                "rewind is disabled; set XEYO_REWIND_ENABLED=1 or unset XEYO_REWIND_ENABLED=0"
            )
        if is_session_persistence_disabled():
            raise RollbackBlockedError("session persistence is disabled; rollback is blocked")

    def _load_transcript_rows(self) -> list[dict[str, Any]]:
        from session.record_transcript import transcript_read_paths
        from session.surface import fold_surface_rows

        if not self.transcript.is_file():
            raise RollbackBlockedError("session transcript is not available")
        raw: list[dict[str, Any]] = []
        for p in transcript_read_paths(self.transcript):
            raw.extend(_read_jsonl(p))
        # 46 号：v2 与 v3 共享同一 fold 视图——v3 marker 影子化的行对 v2
        # 的 plan/重写同样不可见（否则 v2 会把已回溯回合当保留前缀）。
        rows = fold_surface_rows(raw)
        if not rows:
            raise RollbackBlockedError("session transcript is empty")
        return rows

    def _engine_rows(self, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            role = str(row.get("role") or "")
            if role not in _ENGINE_ROLES:
                continue
            if not row.get("id"):
                continue
            out.append(dict(row))
        return out

    def _current_message_ids(self, rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
        return tuple(str(row.get("id")) for row in self._engine_rows(rows))

    def _chat_turn_id(self, user_message_id: str) -> str:
        return f"chat_{user_message_id}"

    def _workspace_relative_path(self, raw_path: str) -> str | None:
        try:
            path = Path(str(raw_path)).expanduser().resolve()
            rel = path.relative_to(self.workspace_root)
        except (OSError, ValueError):
            return None
        return rel.as_posix()

    def _bootstrap_revision_from_transcript(
        self,
        rows: list[dict[str, Any]],
    ) -> SessionRevision | None:
        """Build a revision from the live transcript for chat-only rewind.

        File mutations may be absent (read-only turns, model errors, or turns
        recorded before journal/revision existed).  Users must still edit or
        truncate prior user messages.
        """
        engine_rows = self._engine_rows(rows)
        message_ids = self._current_message_ids(engine_rows)
        if not message_ids:
            return None
        turn_ids = [
            self._chat_turn_id(str(row.get("id")))
            for row in engine_rows
            if row.get("role") == "user" and row.get("id")
        ]
        if not turn_ids:
            return None
        return self.revisions.create(
            parent_revision_id=None,
            head_turn_id=turn_ids[-1],
            turn_ids=turn_ids,
            message_ids=message_ids,
            workspace_root=str(self.workspace_root),
            metadata={"bootstrapped": True, "source": "transcript"},
        )

    def _bootstrap_revision_from_journal(self) -> SessionRevision | None:
        """Recover a head revision from failed turns that never committed one.

        Model/provider errors mark the turn ``failed`` but still record a
        before-snapshot and transcript messages — those turns must remain
        rewindable without forcing the user to start a brand-new session.
        """
        candidates = [
            turn
            for turn in self.journal.list_turns(latest_only=True)
            if turn.status in {"committed", "failed"}
            and turn.message_ids
            and str((turn.metadata or {}).get("before_commit") or "").strip()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.started_at, item.turn_id))
        revision: SessionRevision | None = None
        for turn in candidates:
            revision = self.revisions.commit_turn(
                turn.turn_id,
                message_ids=turn.message_ids,
                parent_revision_id=revision.revision_id if revision else turn.revision_id,
                workspace_root=str(self.workspace_root),
                metadata={
                    "bootstrapped": True,
                    "turn_status": turn.status,
                },
            )
        return revision

    def _rewindable_turn(self, turn: Any) -> bool:
        if turn.status == "committed":
            return True
        # Aborted/failed turns may still hold a before snapshot and completed file ops
        # (user stopped mid-turn after Edit/Write succeeded).
        if turn.status not in {"failed", "aborted"}:
            return False
        return bool(str((turn.metadata or {}).get("before_commit") or "").strip())

    def _find_target_turn(
        self,
        target_message_id: str,
        head: SessionRevision,
        rows: list[dict[str, Any]],
    ) -> tuple[Any, dict[str, Any]]:
        target_row = next(
            (row for row in rows if str(row.get("id") or "") == target_message_id),
            None,
        )
        if target_row is None or target_row.get("role") != "user":
            raise RollbackBlockedError("target message must be a current user message")
        turns = self.journal.list_turns(latest_only=True)
        for turn in turns:
            if turn.turn_id in head.turn_ids and turn.user_message_id == target_message_id:
                if not self._rewindable_turn(turn):
                    raise RollbackBlockedError("target turn is not committed")
                return turn, target_row
        synthetic_id = self._chat_turn_id(target_message_id)
        if synthetic_id in head.turn_ids:
            meta: dict[str, Any] = {"source": "transcript"}
            for turn in turns:
                if turn.user_message_id != target_message_id:
                    continue
                if not self._rewindable_turn(turn):
                    continue
                meta = {**(turn.metadata or {}), **meta}
                break
            return (
                TurnRecord(
                    session_id=self.session_id,
                    turn_id=synthetic_id,
                    user_message_id=target_message_id,
                    status="committed",
                    metadata=meta,
                ),
                target_row,
            )
        # Journal has a rewindable turn for this message even if the head revision
        # was bootstrapped without that turn id — still allow rewind.
        for turn in turns:
            if turn.user_message_id == target_message_id and self._rewindable_turn(turn):
                return turn, target_row
        raise RollbackBlockedError("target message does not belong to the current revision")

    def _operation_details(
        self,
        head: SessionRevision,
        target_turn_id: str,
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        try:
            target_index = head.turn_ids.index(target_turn_id)
        except ValueError as exc:
            raise RollbackBlockedError("target turn is not in the current revision") from exc
        affected_turn_ids = list(head.turn_ids[target_index:])
        operations = [
            operation
            for operation in self.journal.list_operations(latest_only=True)
            if operation.turn_id in affected_turn_ids
        ]
        operations.sort(key=lambda item: (item.started_at, item.operation_id), reverse=True)
        details: list[dict[str, Any]] = []
        for operation in operations:
            details.append(
                {
                    "operation_id": operation.operation_id,
                    "turn_id": operation.turn_id,
                    "tool_name": operation.tool_name,
                    "operation_type": operation.operation_type,
                    "path": operation.path,
                    "status": operation.status,
                    "before_hash": operation.before_hash,
                    "after_hash": operation.after_hash,
                    "inverse_kind": operation.inverse_kind,
                    "inverse_payload": dict(operation.inverse_payload),
                }
            )
        retained_turn_ids = list(head.turn_ids[:target_index])
        return details, affected_turn_ids, retained_turn_ids

    def _journal_ops_for_target_message(
        self,
        rows: list[dict[str, Any]],
        target_message_id: str,
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        """Resolve file ops via journal turns matched by user message id.

        Survives synthetic ``chat_*`` revision bootstraps: operations are keyed by
        real journal turn ids, not by transcript bootstrap ids.
        """
        user_ids_from_target: list[str] = []
        seen_target = False
        for row in rows:
            if str(row.get("role") or "") != "user" or not row.get("id"):
                continue
            mid = str(row["id"])
            if mid == target_message_id:
                seen_target = True
            if seen_target:
                user_ids_from_target.append(mid)
        if not seen_target:
            return [], [], ""

        turns = [
            turn
            for turn in self.journal.list_turns(latest_only=True)
            if turn.user_message_id in set(user_ids_from_target)
            and self._rewindable_turn(turn)
        ]
        turns.sort(key=lambda item: (item.started_at, item.turn_id))
        affected_ids = [turn.turn_id for turn in turns]
        affected_set = set(affected_ids)
        operations = [
            operation
            for operation in self.journal.list_operations(latest_only=True)
            if operation.turn_id in affected_set
        ]
        operations.sort(key=lambda item: (item.started_at, item.operation_id), reverse=True)
        details: list[dict[str, Any]] = []
        for operation in operations:
            details.append(
                {
                    "operation_id": operation.operation_id,
                    "turn_id": operation.turn_id,
                    "tool_name": operation.tool_name,
                    "operation_type": operation.operation_type,
                    "path": operation.path,
                    "status": operation.status,
                    "before_hash": operation.before_hash,
                    "after_hash": operation.after_hash,
                    "inverse_kind": operation.inverse_kind,
                    "inverse_payload": dict(operation.inverse_payload),
                }
            )
        before_commit = ""
        if turns:
            before_commit = str((turns[0].metadata or {}).get("before_commit") or "").strip()
        return details, affected_ids, before_commit

    def _trash_candidates_from_ops(self, details: list[dict[str, Any]]) -> list[str]:
        """Relative paths of files created by the agent (exist after, absent before)."""
        out: list[str] = []
        seen: set[str] = set()
        for detail in details:
            if detail.get("before_hash") is not None:
                continue
            if detail.get("after_hash") is None:
                continue
            rel = self._workspace_relative_path(str(detail.get("path") or ""))
            if not rel or rel in seen:
                continue
            seen.add(rel)
            out.append(rel)
        return out

    def _shadow_restore_plan(
        self,
        target_commit: str,
    ) -> tuple[list[str], list[str]]:
        """Paths to restore via shadow-git, plus worktree drift conflicts.

        Drift = path differs between target and HEAD *and* the working tree no
        longer matches HEAD (user edited after the last agent snapshot).
        """
        from engine.shadow_git import ShadowGit
        from engine.workspace_restore import WorkspaceRestoreTransaction

        commit = str(target_commit or "").strip()
        if not commit:
            return [], []
        shadow = ShadowGit(self.workspace_root)
        head = shadow.head_commit()
        if not head:
            return [], []
        try:
            paths = shadow.diff_paths(commit, head)
        except Exception:
            return [], []
        if not paths:
            return [], []
        conflicts: list[str] = []
        try:
            tx = WorkspaceRestoreTransaction(self.workspace_root, owner="preview")
            head_tree = tx._tree_entries(head)
            for rel in paths:
                current = tx._current_entry(rel)
                expected = head_tree.get(rel)
                expected_hash = expected.object_hash if expected else None
                if current.is_symlink or current.is_directory:
                    conflicts.append(f"{rel}: unsupported path type for restore")
                    continue
                if expected is None:
                    if current.exists:
                        # Untracked relative to HEAD but listed in diff — treat as dirty.
                        conflicts.append(
                            f"{rel}: local modifications after agent snapshot"
                        )
                    continue
                if not current.exists or current.object_hash != expected_hash:
                    conflicts.append(
                        f"{rel}: local modifications after agent snapshot"
                    )
        except Exception as exc:  # noqa: BLE001
            conflicts.append(f"shadow preview failed: {exc}")
        return paths, conflicts

    def _check_file_preconditions(
        self,
        details: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        simulated: dict[str, _FileState] = {}
        conflicts: list[str] = []
        normalized: list[dict[str, Any]] = []
        for detail in details:
            raw_path = str(detail.get("path") or "")
            if not raw_path:
                conflicts.append(f"{detail.get('operation_id')}: missing path")
                continue
            try:
                path = _safe_path(self.workspace_root, raw_path)
                state = simulated.get(str(path))
                if state is None:
                    state = _file_state(path)
                    simulated[str(path)] = state
                if state.is_symlink:
                    conflicts.append(f"{detail['operation_id']}: symlink path is not supported")
                    continue
                expected_exists = detail.get("after_hash") is not None
                expected_hash = detail.get("after_hash")
                if state.exists != expected_exists or (
                    expected_exists and state.content_hash != expected_hash
                ):
                    conflicts.append(
                        f"{detail['operation_id']}: expected after hash {expected_hash}, "
                        f"found {state.content_hash}"
                    )
                    continue
                inverse_kind = detail.get("inverse_kind")
                if inverse_kind not in {"restore_snapshot", "delete_file"}:
                    conflicts.append(f"{detail['operation_id']}: operation is not reversible")
                    continue
                if inverse_kind == "restore_snapshot" and not detail.get("before_hash"):
                    conflicts.append(f"{detail['operation_id']}: before snapshot is missing")
                    continue
                if inverse_kind == "delete_file" and not expected_exists:
                    conflicts.append(f"{detail['operation_id']}: created file has no after hash")
                    continue
                if detail.get("status") != "completed":
                    conflicts.append(f"{detail['operation_id']}: operation is {detail.get('status')}")
                    continue
                before_hash = detail.get("before_hash")
                simulated[str(path)] = _FileState(before_hash is not None, before_hash, False)
                normalized_detail = dict(detail)
                normalized_detail["path"] = str(path)
                normalized.append(normalized_detail)
            except RollbackBlockedError as exc:
                conflicts.append(f"{detail.get('operation_id')}: {exc}")
        return normalized, conflicts

    def _snapshot_text(self, content_hash: str | None) -> str:
        if not content_hash:
            return ""
        try:
            return self.snapshots.get_text(str(content_hash)) or ""
        except Exception:
            return ""

    def _preview_diff_for_operation(self, detail: Mapping[str, Any]) -> str:
        from tools.fileio.diff_preview import format_capped_unified_diff

        raw_path = str(detail.get("path") or "")
        if not raw_path:
            return ""
        inverse_kind = str(detail.get("inverse_kind") or "")
        before_hash = detail.get("before_hash")
        after_hash = detail.get("after_hash")

        current = self._snapshot_text(after_hash) if after_hash else ""
        if not current:
            try:
                path = _safe_path(self.workspace_root, raw_path)
                if path.is_file():
                    current = path.read_text(encoding="utf-8")
            except Exception:
                current = ""

        restored = self._snapshot_text(before_hash) if before_hash else ""
        if inverse_kind == "delete_file":
            restored = ""

        if current == restored and not (inverse_kind == "delete_file" and current):
            return ""

        return format_capped_unified_diff(
            current,
            restored,
            file_path=raw_path,
            max_lines=60,
        )

    def _plan_payload_without_hash(self, plan: RollbackPlan) -> dict[str, Any]:
        payload = plan.to_dict()
        payload["plan_hash"] = ""
        return payload

    def _set_plan_status(self, plan: RollbackPlan, status: str) -> RollbackPlan:
        return self.plans.update(plan, status=status)

    def _wait_for_session_idle(self) -> None:
        if self._session_busy is None or not self._session_busy(self.session_id):
            return
        if self._on_interrupt is not None:
            self._on_interrupt(self.session_id)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not self._session_busy(self.session_id):
                return
            time.sleep(0.25)
            if self._on_interrupt is not None:
                self._on_interrupt(self.session_id)
        if self._on_force_idle is not None:
            self._on_force_idle(self.session_id)
        if self._session_busy is not None and self._session_busy(self.session_id):
            raise LeaseBusyError("session is busy")

    def preview(
        self,
        *,
        target_message_id: str,
        edited_text: str,
        actor: str = "user",
        ttl_seconds: float | None = None,
    ) -> RollbackPlan:
        self._require_enabled()
        target_id = str(target_message_id or "").strip()
        text = str(edited_text or "")
        if not target_id:
            raise RollbackBlockedError("target_message_id is required")
        if not text.strip():
            raise RollbackBlockedError("edited message cannot be empty")
        self._wait_for_session_idle()
        if self._session_busy is not None and self._session_busy(self.session_id):
            raise LeaseBusyError("session is busy")

        from engine.workspace_revision import WorkspaceRevision

        with self._lock:
            rows = self._load_transcript_rows()
            current_ids = self._current_message_ids(rows)
            head = self.revisions.head()
            if head is None:
                head = self._bootstrap_revision_from_journal()
            if head is None:
                head = self._bootstrap_revision_from_transcript(rows)
            elif current_ids != head.message_ids:
                refreshed = self._bootstrap_revision_from_transcript(rows)
                if refreshed is not None and refreshed.message_ids == current_ids:
                    head = refreshed
            if head is None:
                raise RollbackBlockedError("session has no committed rewind revision")
            if current_ids != head.message_ids:
                raise RollbackConflictError("transcript no longer matches current revision")
            target_turn, _target_row = self._find_target_turn(target_id, head, rows)
            if target_turn.turn_id in head.turn_ids:
                details, affected_turn_ids, retained_turn_ids = self._operation_details(
                    head, target_turn.turn_id
                )
            else:
                details, affected_turn_ids, retained_turn_ids = [], [], list(head.turn_ids)
            journal_details, journal_affected, journal_commit = self._journal_ops_for_target_message(
                rows, target_id
            )
            if journal_details:
                details = journal_details
            if journal_affected:
                affected_turn_ids = list(
                    dict.fromkeys([*affected_turn_ids, *journal_affected])
                )
            target_commit = journal_commit or str(
                (target_turn.metadata or {}).get("before_commit") or ""
            ).strip()
            # Prefer journal turn metadata when the head still uses synthetic chat_* turns.
            if not target_commit:
                for turn in self.journal.list_turns(latest_only=True):
                    if turn.user_message_id == target_id and self._rewindable_turn(turn):
                        target_commit = str(
                            (turn.metadata or {}).get("before_commit") or ""
                        ).strip()
                        if target_commit:
                            break
            normalized, conflicts = self._check_file_preconditions(details)
            # Journal hash drift is informative when we will restore via shadow-git
            # (target_commit).  It must NOT silence conflicts for journal-only
            # inverse restore — that path used to force-overwrite user edits.
            hash_warnings: list[str] = []
            shadow_paths: list[str] = []
            worktree_conflicts: list[str] = []
            if target_commit:
                shadow_paths, worktree_conflicts = self._shadow_restore_plan(target_commit)
                if worktree_conflicts:
                    conflicts = list(dict.fromkeys([*conflicts, *worktree_conflicts]))
                if conflicts and details:
                    # Prefer shadow restore: journal hash mismatches become warnings.
                    hash_warnings = [
                        c for c in conflicts if c not in worktree_conflicts
                    ]
                    conflicts = list(worktree_conflicts)
                    if not normalized and details:
                        for item in details:
                            enriched = dict(item)
                            try:
                                enriched["preview_diff"] = self._preview_diff_for_operation(
                                    enriched
                                )
                            except Exception:  # noqa: BLE001
                                pass
                            normalized.append(enriched)
            for item in normalized:
                if "preview_diff" not in item:
                    item["preview_diff"] = self._preview_diff_for_operation(item)
            # Synthetic preview rows when Bash/etc. changed files without journal ops.
            if target_commit and not normalized and shadow_paths:
                for rel in shadow_paths:
                    normalized.append(
                        {
                            "operation_id": f"shadow:{rel}",
                            "turn_id": target_turn.turn_id,
                            "tool_name": "shadow_git",
                            "operation_type": "workspace_restore",
                            "path": str(self.workspace_root / rel),
                            "status": "completed",
                            "before_hash": None,
                            "after_hash": None,
                            "inverse_kind": "restore_snapshot",
                            "inverse_payload": {"source": "shadow_diff"},
                            "preview_diff": "",
                        }
                    )
            try:
                target_index = head.turn_ids.index(target_turn.turn_id)
            except ValueError:
                target_index = max(0, len(head.turn_ids) - len(affected_turn_ids))
            target_position = head.message_ids.index(target_id)
            retained_message_ids = list(head.message_ids[:target_position])
            ttl = max(30.0, float(ttl_seconds or self.plan_ttl_seconds))
            now = time.time()
            restores_workspace = bool(target_commit) or bool(normalized)
            # Fingerprint only plan-touched paths so Vite/test noise cannot invalidate execute.
            op_paths: list[str] = []
            for item in normalized:
                raw = str(item.get("path") or "").strip()
                if not raw:
                    continue
                try:
                    rel = Path(raw).resolve().relative_to(self.workspace_root).as_posix()
                except ValueError:
                    # 同 index._normalize_rel_path：不能用 lstrip("./")（字符集剥离
                    # 会改写 ".gitignore" 类根目录点文件）。
                    rel = raw.replace("\\", "/")
                    while rel.startswith("./"):
                        rel = rel[2:]
                    rel = rel.lstrip("/").strip()
                if rel:
                    op_paths.append(rel)
            fingerprint_paths = list(
                WorkspaceRevision.normalize_paths([*shadow_paths, *op_paths])
            )
            workspace_rev = WorkspaceRevision(self.workspace_root).calculate(
                paths=fingerprint_paths
            )
            checkpoint_id = ""
            if target_commit and target_id:
                from rewind.checkpoint import derive_checkpoint_id, put_checkpoint_cache

                checkpoint_id = derive_checkpoint_id(
                    session_id=self.session_id,
                    user_message_id=target_id,
                    before_commit=target_commit,
                )
                try:
                    put_checkpoint_cache(
                        self.session_id,
                        checkpoint_id=checkpoint_id,
                        user_message_id=target_id,
                        before_commit=target_commit,
                        shadow_paths=shadow_paths,
                        fingerprint_paths=fingerprint_paths,
                    )
                except Exception:  # noqa: BLE001
                    pass
            plan = RollbackPlan(
                session_id=self.session_id,
                source_revision_id=head.revision_id,
                target_turn_id=target_turn.turn_id,
                generated_at=now,
                operation_ids=tuple(item["operation_id"] for item in normalized),
                conflicts=tuple(conflicts),
                requires_confirmation=True,
                status="blocked" if conflicts else "approval_required",
                metadata={
                    "target_message_id": target_id,
                    "edited_text_hash": _sha256(text.encode("utf-8")),
                    "edited_text_length": len(text),
                    "affected_turn_ids": affected_turn_ids,
                    "retained_turn_ids": retained_turn_ids,
                    "retained_message_ids": retained_message_ids,
                    "removed_message_count": len(head.message_ids) - len(retained_message_ids),
                    "removed_turn_count": len(affected_turn_ids),
                    "operations": normalized,
                    "workspace_root": str(self.workspace_root),
                    "workspace_revision": workspace_rev,
                    "fingerprint_paths": fingerprint_paths,
                    "workspace_fingerprint": _json_hash(
                        {str(item.get("path")): item.get("after_hash") for item in normalized}
                    ),
                    "expires_at": now + ttl,
                    "actor": actor,
                    "target_turn_index": target_index,
                    "target_commit": target_commit,
                    "hash_warnings": hash_warnings,
                    "shadow_paths": shadow_paths,
                    "restores_workspace": restores_workspace,
                    "checkpoint_id": checkpoint_id or None,
                },
            )
            plan.plan_hash = _json_hash(self._plan_payload_without_hash(plan))
            self.plans.append(plan)
            self.journal.audit(
                "rollback_preview_blocked" if conflicts else "rollback_preview_created",
                actor=actor,
                revision_id=head.revision_id,
                turn_id=target_turn.turn_id,
                payload={
                    "plan_id": plan.plan_id,
                    "plan_hash": plan.plan_hash,
                    "conflict_count": len(conflicts),
                    "operation_count": len(normalized),
                },
            )
            return plan

    def _validate_plan(self, plan: RollbackPlan, *, plan_hash: str) -> None:
        if plan.plan_hash != plan_hash:
            raise RollbackApprovalError("plan_hash does not match preview")
        expires_at = float(plan.metadata.get("expires_at") or 0)
        if expires_at and time.time() >= expires_at:
            raise RollbackApprovalError("rollback preview has expired")
        if plan.status not in {"approval_required", "approved"}:
            raise RollbackBlockedError(f"rollback plan is not executable: {plan.status}")
        if plan.conflicts:
            raise RollbackBlockedError("rollback plan contains conflicts")
        planned_root = str(plan.metadata.get("workspace_root") or "").strip()
        if planned_root and Path(planned_root).resolve() != self.workspace_root:
            raise RollbackConflictError("workspace changed after preview")
        current = self.revisions.head()
        if current is None or current.revision_id != plan.source_revision_id:
            raise RollbackConflictError("current revision changed after preview")

    def _create_approval(self, plan: RollbackPlan, *, actor: str) -> ApprovalRecord:
        approval = ApprovalRecord(
            session_id=self.session_id,
            plan_id=plan.plan_id,
            plan_hash=plan.plan_hash,
            actor=actor,
            decision="approved",
            metadata={"scope": "exact_plan", "expires_at": plan.metadata.get("expires_at")},
        )
        self.approvals.append(approval)
        self._set_plan_status(plan, "approved")
        self.journal.audit(
            "rollback_approved",
            actor=actor,
            revision_id=plan.source_revision_id,
            turn_id=plan.target_turn_id,
            payload={"plan_id": plan.plan_id, "plan_hash": plan.plan_hash, "approval_id": approval.approval_id},
        )
        return approval

    def _checkpoint_files(self, details: list[dict[str, Any]], job_id: str) -> list[dict[str, Any]]:
        checkpoint: list[dict[str, Any]] = []
        seen: set[str] = set()
        for detail in details:
            raw_path = str(detail.get("path") or "")
            path = _safe_path(self.workspace_root, raw_path)
            if str(path) in seen:
                continue
            seen.add(str(path))
            state = _file_state(path)
            item: dict[str, Any] = {
                "path": str(path),
                "exists": state.exists,
                "content_hash": state.content_hash,
                "is_symlink": state.is_symlink,
            }
            if state.exists:
                content = path.read_text(encoding="utf-8")
                manifest = self.snapshots.put_text(
                    content,
                    source_path=str(path),
                    metadata={"role": "pre_rollback_checkpoint", "job_id": job_id},
                )
                if manifest is None:
                    raise RollbackBlockedError("pre-rollback checkpoint could not be persisted")
                item["snapshot_hash"] = manifest.content_hash
                item["snapshot_id"] = manifest.snapshot_id
            checkpoint.append(item)
        return checkpoint

    def _apply_inverse(
        self,
        detail: dict[str, Any],
        lease: Any = None,
        *,
        force: bool = False,
    ) -> None:
        if lease is not None:
            lease.validate()
        path = _safe_path(self.workspace_root, str(detail.get("path") or ""))
        current = _file_state(path)
        expected_exists = detail.get("after_hash") is not None
        expected_hash = detail.get("after_hash")
        if current.is_symlink:
            raise RollbackConflictError(f"conditional write failed for {path}: symlink")
        if not force and (
            current.exists != expected_exists
            or (expected_exists and current.content_hash != expected_hash)
        ):
            raise RollbackConflictError(
                f"conditional write failed for {path}: expected {expected_hash}, found {current.content_hash}"
            )
        inverse_kind = str(detail.get("inverse_kind") or "")
        if inverse_kind == "delete_file":
            if not current.exists:
                return
            path.unlink()
            return
        if inverse_kind != "restore_snapshot":
            raise RollbackBlockedError(f"unsupported inverse operation: {inverse_kind}")
        before_hash = str(detail.get("before_hash") or "")
        if not before_hash:
            raise RollbackBlockedError(f"missing before snapshot for {path}")
        content = self.snapshots.get_text(before_hash)
        _write_atomic(path, content)
        restored = _file_state(path)
        if not restored.exists or restored.content_hash != before_hash:
            raise RollbackBlockedError(f"restored file hash mismatch: {path}")

    def _normalize_ops_for_execute(
        self,
        details: list[dict[str, Any]],
        *,
        target_commit: str,
    ) -> list[dict[str, Any]]:
        """Resolve journal ops for execute.

        Hash drift is never soft-accepted.  When ``target_commit`` is set the
        caller restores via shadow-git and may pass empty details here.
        """
        del target_commit
        if not details:
            return []
        # Skip synthetic shadow preview rows — they are not journal inverses.
        real = [
            item
            for item in details
            if not str(item.get("operation_id") or "").startswith("shadow:")
        ]
        if not real:
            return []
        normalized, conflicts = self._check_file_preconditions(real)
        if conflicts:
            raise RollbackConflictError("; ".join(conflicts))
        return normalized

    def _restore_ops_scoped(
        self,
        details: list[dict[str, Any]],
        *,
        target_commit: str,
        job: RecoveryJob,
        actor: str,
        plan: RollbackPlan,
    ) -> None:
        """Restore agent-touched files via journal inverse — never force."""
        del target_commit
        for detail in details:
            self._apply_inverse(detail, None, force=False)
            operation_id = str(detail["operation_id"])
            job.applied_operation_ids = tuple((*job.applied_operation_ids, operation_id))
            self.jobs.update(job, applied_operation_ids=job.applied_operation_ids)
            self.journal.audit(
                "rollback_operation_applied",
                actor=actor,
                revision_id=plan.source_revision_id,
                turn_id=plan.target_turn_id,
                operation_id=operation_id,
                payload={"job_id": job.job_id, "path": detail.get("path"), "scoped": True},
            )

    def _rewrite_transcript(
        self,
        retained_ids: list[str],
        *,
        target_message_id: str | None = None,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        from session.record_transcript import discard_rotated_transcripts

        rows = self._load_transcript_rows()
        current_ids = list(self._current_message_ids(rows))
        head = self.revisions.head()
        if head is None or tuple(current_ids) != head.message_ids:
            raise RollbackConflictError("transcript changed before conditional rewrite")
        if current_ids[: len(retained_ids)] != retained_ids:
            raise RollbackConflictError("transcript prefix no longer matches rollback plan")
        if target_message_id:
            retained: list[dict[str, Any]] = []
            for row in rows:
                if str(row.get("id") or "") == target_message_id:
                    break
                retained.append(row)
        else:
            keep = set(retained_ids)
            retained = [row for row in rows if str(row.get("id") or "") in keep]
        text = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in retained)
        backup_text = self.transcript.read_text(encoding="utf-8")
        backup_manifest = self.snapshots.put_text(
            backup_text,
            source_path=str(self.transcript),
            metadata={"role": "pre_rollback_transcript"},
        )
        if backup_manifest is None:
            raise RollbackBlockedError("pre-rollback transcript checkpoint could not be persisted")
        _write_atomic(self.transcript, text)
        # 46 号：重写后回填仍生效的 v3 rewind marker。fold 对「marker 在、
        # 影子首行缺失」保守不隐藏，因此回填方向安全；丢失 marker 则会让
        # 已被 v3 回溯的行在下次 fold 复活。
        try:
            from rewind.hotpath import _append_transcript as _v2_append
            from session.surface import active_markers

            markers = active_markers(rows)
            if markers:
                _v2_append(self.transcript, markers)
        except Exception:  # noqa: BLE001 — marker 回填失败不阻断 v2 提交
            self.journal.audit(
                "rollback_surface_marker_backfill_failed",
                actor="system",
                revision_id=head.revision_id if head else None,
                turn_id=plan.target_turn_id,
            )
        discarded = discard_rotated_transcripts(self.transcript)
        if discarded:
            self.journal.audit(
                "rollback_rotated_transcripts_discarded",
                actor="system",
                revision_id=head.revision_id if head else None,
                payload={"paths": discarded},
            )
        return backup_manifest.content_hash, _sha256(text.encode("utf-8")), retained

    def _restore_checkpoint(self, checkpoint: list[dict[str, Any]], transcript_hash: str | None) -> list[str]:
        errors: list[str] = []
        for item in checkpoint:
            path = Path(str(item["path"]))
            try:
                current = _file_state(path)
                expected = item.get("content_hash")
                if item.get("exists"):
                    if current.exists and current.content_hash == expected:
                        continue
                    content = self.snapshots.get_text(str(item.get("snapshot_hash") or ""))
                    _write_atomic(path, content)
                elif current.exists:
                    path.unlink()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {type(exc).__name__}: {exc}")
        if transcript_hash:
            try:
                original = self.snapshots.get_text(transcript_hash)
                _write_atomic(self.transcript, original)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"transcript: {type(exc).__name__}: {exc}")
        return errors

    def _job_response(
        self,
        job: RecoveryJob,
        revision: SessionRevision | None = None,
        *,
        retained_messages: list[dict[str, Any]] | None = None,
        edited_text: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"job": job.to_dict()}
        if revision is not None:
            payload["revision"] = revision.to_dict()
        if retained_messages is not None:
            payload["retained_messages"] = retained_messages
        if edited_text is not None:
            payload["edited_text"] = edited_text
        return payload

    def get_job(self, job_id: str) -> RecoveryJob | None:
        return self.jobs.latest(str(job_id or "").strip())

    def _apply_workspace_restore(
        self,
        *,
        plan: RollbackPlan,
        job: RecoveryJob,
        details: list[dict[str, Any]],
        target_commit: str,
        shadow_paths: list[str],
        fingerprint_paths: list[str],
        expected_rev: str,
        allow_full_tree: bool,
        actor: str,
    ) -> WorkspaceLock | None:
        """Run file restore after transcript is already committed. Returns lock if held."""
        from engine.workspace_revision import WorkspaceRevision

        workspace_lock_instance: WorkspaceLock | None = None
        if target_commit:
            paths = list(shadow_paths)
            if not paths and not allow_full_tree:
                paths, worktree_conflicts = self._shadow_restore_plan(target_commit)
                if worktree_conflicts:
                    raise RollbackConflictError("; ".join(worktree_conflicts))
            self.jobs.update(
                job,
                status="executing",
                metadata={
                    **job.metadata,
                    "checkpoint": [],
                    "full_tree_restore": allow_full_tree,
                    "shadow_paths": paths,
                    "restore_workspace": True,
                    "fingerprint_paths": fingerprint_paths,
                    "phase": "workspace_restoring",
                },
            )
            if paths or allow_full_tree:
                from engine.workspace_restore import WorkspaceRestoreTransaction

                trash_candidates = self._trash_candidates_from_ops(
                    [
                        item
                        for item in details
                        if not str(item.get("operation_id") or "").startswith("shadow:")
                    ]
                )
                tx = WorkspaceRestoreTransaction(
                    self.workspace_root, owner=job.job_id
                )
                try:
                    tx.execute(
                        target_commit,
                        expected_rev,
                        trash_candidates=trash_candidates,
                        auto_trash_created=True,
                        path_scope=None if allow_full_tree else paths,
                        fingerprint_paths=(
                            None if allow_full_tree else fingerprint_paths
                        ),
                    )
                except Exception as tx_exc:
                    raise RollbackBlockedError(
                        f"Restore transaction failed: {tx_exc}"
                    ) from tx_exc
            else:
                self.journal.audit(
                    "rollback_shadow_noop",
                    actor=actor,
                    revision_id=plan.source_revision_id,
                    turn_id=plan.target_turn_id,
                    payload={
                        "plan_id": plan.plan_id,
                        "job_id": job.job_id,
                        "target_commit": target_commit,
                        "reason": "no_changed_paths",
                    },
                )
            return None

        normalized = self._normalize_ops_for_execute(details, target_commit="")
        checkpoint = self._checkpoint_files(normalized or [], job.job_id)
        self.jobs.update(
            job,
            status="executing",
            metadata={
                **job.metadata,
                "checkpoint": checkpoint,
                "full_tree_restore": False,
                "restore_workspace": True,
                "fingerprint_paths": fingerprint_paths,
                "phase": "workspace_restoring",
            },
        )
        if normalized:
            current_rev = WorkspaceRevision(self.workspace_root).calculate(
                paths=fingerprint_paths
            )
            if current_rev != expected_rev:
                raise RollbackConflictError(
                    f"workspace changed after preview: expected {expected_rev}, got {current_rev}"
                )
            workspace_lock_instance = WorkspaceLock(
                self.workspace_root,
                owner=job.job_id,
                ttl_seconds=self._lease_ttl_seconds,
            )
            workspace_lock_instance.acquire()
            self._restore_ops_scoped(
                normalized,
                target_commit="",
                job=job,
                actor=actor,
                plan=plan,
            )
        return workspace_lock_instance

    def execute(
        self,
        *,
        plan_id: str,
        plan_hash: str,
        idempotency_key: str,
        confirmed: bool,
        expected_workspace_revision: str | None = None,
        full_tree_restore: bool | None = None,
        restore_workspace: bool | None = None,
        async_workspace: bool | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        self._require_enabled()
        if not idempotency_key.strip():
            raise RollbackApprovalError("idempotency_key is required")
        from engine.workspace_revision import WorkspaceRevision
        from rewind import is_rewind_full_tree_enabled

        allow_full_tree = (
            bool(full_tree_restore)
            if full_tree_restore is not None
            else is_rewind_full_tree_enabled()
        )
        # v2 FE passes true; tests omit → sync full commit (backward compatible).
        do_async_workspace = bool(async_workspace) if async_workspace is not None else False
        with self._lock:
            existing = self.jobs.by_idempotency(idempotency_key)
            if existing is not None:
                if existing.plan_id != plan_id:
                    raise RollbackIdempotencyError("idempotency key is bound to another plan")
                return self._job_response(existing)
            plan = self.plans.latest(plan_id)
            if plan is None:
                raise RollbackBlockedError("rollback plan not found")
            self._validate_plan(plan, plan_hash=plan_hash)
            if not confirmed:
                raise RollbackApprovalError("explicit rollback confirmation is required")
            # Skip long idle wait when session is already free.
            if self._session_busy is not None and self._session_busy(self.session_id):
                self._wait_for_session_idle()
            pool_busy_lease: int | None = None
            if self._on_acquire_busy is not None:
                pool_busy_lease = self._on_acquire_busy(self.session_id)
                if pool_busy_lease is None:
                    raise LeaseBusyError("session is busy")
            elif self._session_busy is not None and self._session_busy(self.session_id):
                raise LeaseBusyError("session is busy")
            approval = self._create_approval(plan, actor=actor)
            session_lease = None
            workspace_lock_instance: WorkspaceLock | None = None
            job = RecoveryJob(
                session_id=self.session_id,
                plan_id=plan.plan_id,
                idempotency_key=idempotency_key,
                status="accepted",
                metadata={
                    "plan_hash": plan.plan_hash,
                    "approval_id": approval.approval_id,
                    "phase": "accepted",
                },
            )
            self.jobs.append(job)
            self.journal.audit(
                "rollback_execute_started",
                actor=actor,
                revision_id=plan.source_revision_id,
                turn_id=plan.target_turn_id,
                payload={"plan_id": plan.plan_id, "job_id": job.job_id},
            )
            checkpoint: list[dict[str, Any]] = []
            transcript_backup_hash: str | None = None
            try:
                WorkspaceLock(
                    self.workspace_root,
                    owner="reclaim",
                    ttl_seconds=self._lease_ttl_seconds,
                ).reclaim_stale_if_expired()
                session_lease = SessionLock(
                    self.session_id,
                    owner=job.job_id,
                    ttl_seconds=self._lease_ttl_seconds,
                ).acquire()
                session_lease.validate()
                details = list(plan.metadata.get("operations") or [])
                target_commit = str(plan.metadata.get("target_commit") or "").strip()
                shadow_paths = [
                    str(p).replace("\\", "/")
                    for p in (plan.metadata.get("shadow_paths") or [])
                    if str(p).strip()
                ]
                fingerprint_paths = list(
                    WorkspaceRevision.normalize_paths(
                        plan.metadata.get("fingerprint_paths")
                    )
                )
                expected_rev = expected_workspace_revision or str(
                    plan.metadata.get("workspace_revision") or ""
                )
                if not expected_rev:
                    raise RollbackBlockedError("expected_workspace_revision is missing")
                do_restore_workspace = (
                    bool(restore_workspace)
                    if restore_workspace is not None
                    else bool(plan.metadata.get("restores_workspace"))
                )

                # 工作区指纹预检：外部改动必须在 **transcript 重写之前**拦截。
                # 此前比对只存在于异步恢复路径——同步 execute 会先截断对话、
                # 后才发现工作区已变，用户在预览与执行之间手改的文件面临被
                # 检查点覆盖（测试合同：test_execute_blocks_when_external_file_change_is_detected）。
                if fingerprint_paths:
                    precheck_rev = WorkspaceRevision(
                        self.workspace_root
                    ).calculate(paths=fingerprint_paths)
                    if precheck_rev != expected_rev:
                        raise RollbackConflictError(
                            "workspace changed after preview: "
                            f"expected {expected_rev}, got {precheck_rev}"
                        )

                # --- Rewind v2: transcript first (Cursor-like chat projection) ---
                retained_ids = [
                    str(item) for item in plan.metadata.get("retained_message_ids") or []
                ]
                target_message_id = str(plan.metadata.get("target_message_id") or "")
                (
                    transcript_backup_hash,
                    transcript_hash,
                    retained_rows,
                ) = self._rewrite_transcript(
                    retained_ids,
                    target_message_id=target_message_id or None,
                )
                retained_turn_ids = tuple(
                    str(item) for item in plan.metadata.get("retained_turn_ids") or []
                )
                new_revision = self.revisions.create(
                    parent_revision_id=plan.source_revision_id,
                    head_turn_id=None,
                    turn_ids=retained_turn_ids,
                    message_ids=tuple(retained_ids),
                    transcript_hash=transcript_hash,
                    workspace_root=str(self.workspace_root),
                    metadata={
                        "operation": "rollback_commit",
                        "source_revision_id": plan.source_revision_id,
                        "target_turn_id": plan.target_turn_id,
                        "plan_id": plan.plan_id,
                        "job_id": job.job_id,
                        "restore_workspace": do_restore_workspace,
                    },
                )
                if new_revision is None:
                    raise RollbackBlockedError("rollback revision commit failed")

                from memory.session_md import (
                    clear_after_rollback,
                    count_tool_results_rows,
                )
                from memory.working import reset_after_rollback

                reset_after_rollback(self.session_id)
                # A5 差分重写：把 delta 截断点对齐到保留转录的工具结果数——
                # 回滚精确到 turn，保留转录之前写下的叙事（不再整文件失忆）；
                # 无法计量时 count_tool_results_rows 返回 None → 退回旧行为整删。
                clear_after_rollback(
                    self.session_id,
                    keep_tool_calls=count_tool_results_rows(retained_rows),
                )
                if self._on_commit is not None:
                    self._on_commit(self.session_id)

                self.jobs.update(
                    job,
                    status="transcript_committed",
                    metadata={
                        **job.metadata,
                        "transcript_hash": transcript_hash,
                        "phase": "transcript_committed",
                        "restore_workspace": do_restore_workspace,
                        "full_tree_restore": allow_full_tree,
                        "shadow_paths": shadow_paths,
                        "fingerprint_paths": fingerprint_paths,
                        "target_commit": target_commit,
                        "retained_message_ids": retained_ids,
                    },
                )

                def _finish_workspace() -> None:
                    nonlocal workspace_lock_instance
                    try:
                        if do_restore_workspace:
                            workspace_lock_instance = self._apply_workspace_restore(
                                plan=plan,
                                job=job,
                                details=details,
                                target_commit=target_commit,
                                shadow_paths=shadow_paths,
                                fingerprint_paths=fingerprint_paths,
                                expected_rev=expected_rev,
                                allow_full_tree=allow_full_tree,
                                actor=actor,
                            )
                        self.jobs.update(
                            job,
                            status="committed",
                            metadata={
                                **job.metadata,
                                "phase": "committed",
                                "transcript_hash": transcript_hash,
                            },
                        )
                        self._set_plan_status(plan, "committed")
                        self.journal.audit(
                            "rollback_committed",
                            actor=actor,
                            revision_id=new_revision.revision_id,
                            turn_id=plan.target_turn_id,
                            payload={"plan_id": plan.plan_id, "job_id": job.job_id},
                        )
                    except Exception as ws_exc:  # noqa: BLE001
                        message = f"{type(ws_exc).__name__}: {ws_exc}"
                        self.jobs.update(
                            job,
                            status="recovery_required",
                            error=message,
                            metadata={
                                **job.metadata,
                                "phase": "recovery_required",
                                "transcript_hash": transcript_hash,
                            },
                        )
                        self.journal.audit(
                            "rollback_recovery_required",
                            actor=actor,
                            revision_id=plan.source_revision_id,
                            turn_id=plan.target_turn_id,
                            payload={
                                "plan_id": plan.plan_id,
                                "job_id": job.job_id,
                                "error": message,
                            },
                        )
                    finally:
                        if workspace_lock_instance is not None:
                            try:
                                workspace_lock_instance.release()
                            except Exception:  # noqa: BLE001
                                pass
                            workspace_lock_instance = None

                if do_restore_workspace and do_async_workspace:
                    import threading

                    # Release session lease before background work so chat can continue.
                    if session_lease is not None:
                        session_lease.release()
                        session_lease = None
                    if pool_busy_lease is not None and self._on_release_busy is not None:
                        self._on_release_busy(self.session_id, pool_busy_lease)
                        pool_busy_lease = None
                    threading.Thread(
                        target=_finish_workspace,
                        name=f"rewind-ws-{job.job_id}",
                        daemon=True,
                    ).start()
                    return self._job_response(
                        job,
                        new_revision,
                        retained_messages=retained_rows,
                    )

                _finish_workspace()
                if job.status == "recovery_required":
                    return self._job_response(job, new_revision, retained_messages=retained_rows)
                return self._job_response(
                    job,
                    new_revision,
                    retained_messages=retained_rows,
                )
            except Exception as exc:  # noqa: BLE001
                compensation_errors: list[str] = []
                if checkpoint:
                    compensation_errors = self._restore_checkpoint(
                        checkpoint, transcript_backup_hash
                    )
                message = f"{type(exc).__name__}: {exc}"
                status = (
                    "recovery_required"
                    if (
                        compensation_errors
                        or job.applied_operation_ids
                        or "recovery requires attention" in message.lower()
                    )
                    else "blocked"
                )
                metadata = {
                    **job.metadata,
                    "checkpoint": checkpoint,
                    "transcript_backup_hash": transcript_backup_hash,
                    "compensation_errors": compensation_errors,
                }
                self.jobs.update(job, status=status, error=message, metadata=metadata)
                self._set_plan_status(plan, status)
                self.journal.audit(
                    "rollback_recovery_required"
                    if status == "recovery_required"
                    else "rollback_blocked",
                    actor=actor,
                    revision_id=plan.source_revision_id,
                    turn_id=plan.target_turn_id,
                    payload={
                        "plan_id": plan.plan_id,
                        "job_id": job.job_id,
                        "error": message,
                        "compensation_errors": compensation_errors,
                    },
                )
                if status == "recovery_required":
                    return self._job_response(job)
                if isinstance(exc, RollbackConflictError):
                    raise exc
                raise RollbackBlockedError(message) from exc
            finally:
                if pool_busy_lease is not None and self._on_release_busy is not None:
                    self._on_release_busy(self.session_id, pool_busy_lease)
                if workspace_lock_instance is not None:
                    workspace_lock_instance.release()
                if session_lease is not None:
                    session_lease.release()

    def resolve_recovery(
        self,
        *,
        job_id: str,
        action: str,
        actor: str = "user",
    ) -> dict[str, Any]:
        """Retry checkpoint restore or abandon a recovery_required job."""
        self._require_enabled()
        action_norm = str(action or "").strip().lower()
        if action_norm not in {"retry_checkpoint", "abandon"}:
            raise RollbackBlockedError(
                "action must be retry_checkpoint or abandon"
            )
        with self._lock:
            job = self.jobs.latest(str(job_id or "").strip())
            if job is None:
                raise RollbackBlockedError("rollback job not found")
            if job.status != "recovery_required":
                raise RollbackBlockedError(
                    f"job is not recoverable: {job.status}"
                )
            plan = self.plans.latest(job.plan_id)
            if action_norm == "abandon":
                try:
                    from engine.workspace_restore import WorkspaceRestoreTransaction

                    WorkspaceRestoreTransaction(
                        self.workspace_root, owner=job.job_id
                    ).reconcile()
                except Exception:  # noqa: BLE001
                    pass
                self.jobs.update(
                    job,
                    status="abandoned",
                    error=None,
                    metadata={**job.metadata, "recovery_action": "abandon"},
                )
                if plan is not None:
                    self._set_plan_status(plan, "abandoned")
                self.journal.audit(
                    "rollback_recovery_abandoned",
                    actor=actor,
                    revision_id=plan.source_revision_id if plan else None,
                    turn_id=plan.target_turn_id if plan else None,
                    payload={"plan_id": job.plan_id, "job_id": job.job_id},
                )
                return self._job_response(job)

            checkpoint = list(job.metadata.get("checkpoint") or [])
            transcript_hash = job.metadata.get("transcript_backup_hash")
            errors = self._restore_checkpoint(
                checkpoint,
                str(transcript_hash) if transcript_hash else None,
            )
            try:
                from engine.workspace_restore import WorkspaceRestoreTransaction

                WorkspaceRestoreTransaction(
                    self.workspace_root, owner=job.job_id
                ).reconcile()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"reconcile: {type(exc).__name__}: {exc}")
            if errors:
                self.jobs.update(
                    job,
                    metadata={
                        **job.metadata,
                        "compensation_errors": errors,
                        "recovery_action": "retry_checkpoint",
                    },
                )
                raise RollbackBlockedError(
                    "checkpoint recovery still incomplete: " + "; ".join(errors)
                )
            self.jobs.update(
                job,
                status="recovered",
                error=None,
                metadata={
                    **job.metadata,
                    "compensation_errors": [],
                    "recovery_action": "retry_checkpoint",
                },
            )
            if plan is not None:
                self._set_plan_status(plan, "recovered")
            self.journal.audit(
                "rollback_recovery_resolved",
                actor=actor,
                revision_id=plan.source_revision_id if plan else None,
                turn_id=plan.target_turn_id if plan else None,
                payload={"plan_id": job.plan_id, "job_id": job.job_id},
            )
            return self._job_response(job)


__all__ = [
    "RollbackApprovalError",
    "RollbackBlockedError",
    "RollbackConflictError",
    "RollbackDisabledError",
    "RollbackError",
    "RollbackIdempotencyError",
    "RollbackService",
]
