"""Local worktree drift must block rewind; journal hash drift alone is a warning."""

from __future__ import annotations

import json
import os
from pathlib import Path

from engine.shadow_git import ShadowGit
from msgtypes.message import Message
from rewind.journal import OperationJournal
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


def test_worktree_drift_blocks_when_target_commit_present(tmp_path: Path) -> None:
    """User edits after the agent snapshot must block — no silent force overwrite."""
    session_id = "hash-mismatch-block"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")

    shadow = ShadowGit(workspace)
    before = shadow.snapshot("before")

    target = workspace / "TitleBar.tsx"
    target.write_text("v1\n", encoding="utf-8")
    after_commit = shadow.snapshot("after agent")

    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)
    snapshots = SnapshotStore(session_id, root=tmp_path / "snapshots", enabled=True)

    user = Message(role="user", content="add icon")
    assistant = Message(role="assistant", content="done")
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(_row(m), ensure_ascii=False) + "\n" for m in (user, assistant)),
        encoding="utf-8",
    )

    before_snap = snapshots.put_text("v1\n", source_path=str(target), metadata={"role": "before"})
    after_snap = snapshots.put_text("v2-icon\n", source_path=str(target), metadata={"role": "after"})
    assert before_snap and after_snap
    # Journal records v2 but disk was snapshotted as v1 then… align disk to after_snap text
    # then snapshot so HEAD matches agent end; then drift past HEAD.
    target.write_text("v2-icon\n", encoding="utf-8")
    after_commit = shadow.snapshot("after edit tool")
    del after_commit  # HEAD is agent end state

    turn = journal.start_turn(user_message_id=user.id, metadata={"before_commit": before})
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

    # User hand-edit after agent — worktree no longer matches HEAD.
    target.write_text("v3-drifted\n", encoding="utf-8")

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user.id, edited_text="add icon elsewhere")
    assert plan.status == "blocked"
    assert plan.conflicts
    assert any("local modifications" in c for c in plan.conflicts)


def test_journal_hash_warning_but_clean_worktree_allows_shadow_restore(
    tmp_path: Path,
) -> None:
    """Journal after_hash can drift; if worktree still matches HEAD, restore via shadow."""
    session_id = "hash-warn-shadow"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")

    shadow = ShadowGit(workspace)
    before = shadow.snapshot("before")

    target = workspace / "TitleBar.tsx"
    target.write_text("v2-icon\n", encoding="utf-8")
    shadow.snapshot("after agent")

    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)
    snapshots = SnapshotStore(session_id, root=tmp_path / "snapshots", enabled=True)

    user = Message(role="user", content="add icon")
    assistant = Message(role="assistant", content="done")
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(_row(m), ensure_ascii=False) + "\n" for m in (user, assistant)),
        encoding="utf-8",
    )

    before_snap = snapshots.put_text("v1\n", source_path=str(target), metadata={"role": "before"})
    # Deliberately wrong after hash vs disk (disk is v2-icon matching HEAD).
    after_snap = snapshots.put_text("v2-WRONG\n", source_path=str(target), metadata={"role": "after"})
    assert before_snap and after_snap

    turn = journal.start_turn(user_message_id=user.id, metadata={"before_commit": before})
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
    plan = service.preview(target_message_id=user.id, edited_text="add icon elsewhere")
    assert plan.status == "approval_required"
    assert plan.conflicts == ()
    assert plan.metadata.get("hash_warnings")
    assert plan.metadata.get("shadow_paths")

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="hash-warn-shadow",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"
    assert "retained_messages" in result
    # Restored to before tree (file absent or not v2-icon).
    assert not target.exists() or target.read_text(encoding="utf-8") != "v2-icon\n"
