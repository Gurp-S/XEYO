"""Chat-only execute, scoped fingerprints, and recovery resolve."""

from __future__ import annotations

import json
import os
from pathlib import Path

from engine.shadow_git import ShadowGit
from engine.workspace_revision import WorkspaceRevision
from msgtypes.message import Message
from rewind.journal import OperationJournal
from rewind.models import RecoveryJob
from rewind.revision import RevisionStore
from rewind.service import RollbackService
from rewind.snapshot import SnapshotStore
from session.persistence import transcript_path


def _row(message: Message) -> dict[str, object]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "ts": 1.0,
    }


def _seed(tmp_path: Path, session_id: str) -> tuple[RollbackService, str, Path]:
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")

    shadow = ShadowGit(workspace)
    target = workspace / "tracked.txt"
    target.write_text("v1\n", encoding="utf-8")
    before = shadow.snapshot("before")
    target.write_text("v2\n", encoding="utf-8")
    shadow.snapshot("after")

    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)
    snapshots = SnapshotStore(session_id, root=tmp_path / "snapshots", enabled=True)

    user = Message(role="user", content="hello", id="user-1")
    assistant = Message(role="assistant", content="world", id="asst-1")
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(
            json.dumps(_row(m), ensure_ascii=False) + "\n" for m in (user, assistant)
        ),
        encoding="utf-8",
    )

    before_snap = snapshots.put_text(
        "v1\n", source_path=str(target), metadata={"role": "before"}
    )
    after_snap = snapshots.put_text(
        "v2\n", source_path=str(target), metadata={"role": "after"}
    )
    assert before_snap and after_snap

    turn = journal.start_turn(
        user_message_id=user.id, metadata={"before_commit": before}
    )
    assert turn is not None
    op = journal.start_operation(
        turn_id=turn.turn_id,
        revision_id=None,
        tool_name="Edit",
        operation_type="file_edit",
        path=str(target),
        before_hash=before_snap.content_hash,
        after_hash=after_snap.content_hash,
        inverse_kind="restore_snapshot",
        inverse_payload={},
    )
    assert op is not None
    journal.transition_operation(op.operation_id, "completed")
    journal.transition_turn(
        turn.turn_id,
        "committed",
        message_ids=(user.id, assistant.id),
        operation_ids=(op.operation_id,),
        assistant_message_id=assistant.id,
        metadata={"before_commit": before},
    )
    revisions.commit_turn(
        turn.turn_id,
        message_ids=(user.id, assistant.id),
        workspace_root=str(workspace),
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    return service, user.id, target


def test_execute_chat_only_skips_file_restore(tmp_path: Path) -> None:
    service, user_id, tracked = _seed(tmp_path, "chat-only")
    assert tracked.read_text(encoding="utf-8") == "v2\n"

    plan = service.preview(target_message_id=user_id, edited_text="hello edited")
    assert plan.metadata.get("restores_workspace") is True

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="chat-only-key",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
        restore_workspace=False,
    )
    assert result["job"]["status"] == "committed"
    assert tracked.read_text(encoding="utf-8") == "v2\n"


def test_preview_fingerprint_ignores_unrelated_noise(tmp_path: Path) -> None:
    service, user_id, _tracked = _seed(tmp_path, "fp-scope")
    plan = service.preview(target_message_id=user_id, edited_text="hello edited")
    rev = str(plan.metadata.get("workspace_revision") or "")
    paths = list(plan.metadata.get("fingerprint_paths") or [])
    assert paths
    (service.workspace_root / "vite-noise.js").write_text("noise", encoding="utf-8")
    assert WorkspaceRevision(service.workspace_root).calculate(paths=paths) == rev


def test_resolve_recovery_abandon(tmp_path: Path) -> None:
    service, user_id, _tracked = _seed(tmp_path, "recover-abandon")
    plan = service.preview(target_message_id=user_id, edited_text="edited")
    job = RecoveryJob(
        session_id=service.session_id,
        plan_id=plan.plan_id,
        idempotency_key="rec-key",
        status="recovery_required",
        metadata={"checkpoint": [], "compensation_errors": ["x"]},
        error="partial",
    )
    service.jobs.append(job)
    service._set_plan_status(plan, "recovery_required")

    out = service.resolve_recovery(job_id=job.job_id, action="abandon")
    assert out["job"]["status"] == "abandoned"
