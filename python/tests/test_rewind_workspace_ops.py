"""Regression: workspace file restore must survive ui_thought / created files."""

from __future__ import annotations

import json
import os
from pathlib import Path

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
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "ts": 1.0,
    }


def _build_session_with_write(tmp_path: Path) -> tuple[RollbackService, Path, dict[str, str]]:
    session_id = "rollback-workspace-ops"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")

    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)
    snapshots = SnapshotStore(session_id, root=tmp_path / "snapshots", enabled=True)

    first_user = Message(role="user", content="first")
    first_assistant = Message(role="assistant", content="first answer")
    second_user = Message(role="user", content="old prompt")
    second_assistant = Message(role="assistant", content="old answer")
    rows = [_row(item) for item in (first_user, first_assistant, second_user, second_assistant)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    turn_one = journal.start_turn(user_message_id=first_user.id)
    assert turn_one is not None
    journal.transition_turn(
        turn_one.turn_id,
        "committed",
        message_ids=(first_user.id, first_assistant.id),
        assistant_message_id=first_assistant.id,
    )
    revision_one = revisions.commit_turn(
        turn_one.turn_id,
        message_ids=(first_user.id, first_assistant.id),
        workspace_root=str(workspace),
    )
    assert revision_one is not None

    old_content = "before\n"
    new_content = "after\n"
    target = workspace / "tracked.txt"
    target.write_bytes(new_content.encode("utf-8"))
    before = snapshots.put_text(old_content, source_path=str(target), metadata={"role": "before"})
    after = snapshots.put_text(new_content, source_path=str(target), metadata={"role": "after"})
    assert before is not None and after is not None
    operation = journal.start_operation(
        turn_id="pending",
        revision_id=revision_one.revision_id,
        tool_name="FileWrite",
        operation_type="write",
        path=str(target),
        before_hash=before.content_hash,
        after_hash=after.content_hash,
        inverse_kind="restore_snapshot",
        inverse_payload={
            "before_snapshot_id": before.snapshot_id,
            "after_snapshot_id": after.snapshot_id,
        },
    )
    assert operation is not None
    journal.transition_operation(operation.operation_id, "completed")

    turn_two = journal.start_turn(
        revision_id=revision_one.revision_id,
        user_message_id=second_user.id,
    )
    assert turn_two is not None
    journal.transition_operation(operation.operation_id, "completed", turn_id=turn_two.turn_id)
    journal.transition_turn(
        turn_two.turn_id,
        "committed",
        message_ids=(second_user.id, second_assistant.id),
        operation_ids=(operation.operation_id,),
        assistant_message_id=second_assistant.id,
    )
    revisions.commit_turn(
        turn_two.turn_id,
        message_ids=(second_user.id, second_assistant.id),
        parent_revision_id=revision_one.revision_id,
        workspace_root=str(workspace),
    )

    service = RollbackService(
        session_id,
        workspace,
        sessions_dir=sessions_dir,
        enabled=True,
    )
    return service, target, {
        "target_message_id": second_user.id,
        "operation_id": operation.operation_id,
    }


def test_ui_thought_rows_do_not_drop_journal_file_operations(tmp_path: Path) -> None:
    service, target, ids = _build_session_with_write(tmp_path)
    with service.transcript.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "thought_ui_1",
                    "role": "ui_thought",
                    "content": "thinking",
                    "ts": 2.0,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    plan = service.preview(target_message_id=ids["target_message_id"], edited_text="new prompt")
    assert ids["operation_id"] in plan.operation_ids
    assert plan.metadata.get("operations")
    assert plan.status == "approval_required"

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="ui-thought-ops",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"
    assert target.read_text(encoding="utf-8") == "before\n"


def test_rewind_restores_agent_created_file_via_shadow_commit(tmp_path: Path) -> None:
    from engine.shadow_git import ShadowGit

    session_id = "create-file-rewind"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")

    shadow = ShadowGit(workspace)
    before = shadow.snapshot("before turn")

    icon = workspace / "gui" / "icon.svg"
    icon.parent.mkdir(parents=True)
    icon.write_text("<svg id='new'/>", encoding="utf-8")
    shadow.snapshot("after icon created")

    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)
    snapshots = SnapshotStore(session_id, root=tmp_path / "snapshots", enabled=True)

    user = Message(role="user", content="add an icon")
    assistant = Message(role="assistant", content="done")
    rows = [_row(user), _row(assistant)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    turn = journal.start_turn(
        user_message_id=user.id,
        metadata={"before_commit": before},
    )
    assert turn is not None
    after_snap = snapshots.put_text(
        "<svg id='new'/>",
        source_path=str(icon),
        metadata={"role": "after"},
    )
    assert after_snap is not None
    operation = journal.start_operation(
        turn_id=turn.turn_id,
        revision_id=None,
        tool_name="FileWrite",
        operation_type="write",
        path=str(icon),
        before_hash=None,
        after_hash=after_snap.content_hash,
        inverse_kind="delete_file",
        inverse_payload={},
    )
    assert operation is not None
    journal.transition_operation(operation.operation_id, "completed")
    journal.transition_turn(
        turn.turn_id,
        "committed",
        message_ids=(user.id, assistant.id),
        operation_ids=(operation.operation_id,),
        assistant_message_id=assistant.id,
        metadata={"before_commit": before},
    )
    revisions.commit_turn(
        turn.turn_id,
        message_ids=(user.id, assistant.id),
        workspace_root=str(workspace),
        metadata={"operation_count": 1},
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user.id, edited_text="add an icon elsewhere")
    assert plan.metadata.get("target_commit") == before
    assert any(
        str(op.get("path") or "").endswith("icon.svg")
        for op in (plan.metadata.get("operations") or [])
    )

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="create-file-rewind",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"
    assert not icon.exists()
