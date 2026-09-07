from __future__ import annotations

import json
from pathlib import Path

import pytest

from msgtypes.message import Message
from rewind.journal import OperationJournal
from rewind.revision import RevisionStore
from rewind.service import (
    RollbackApprovalError,
    RollbackConflictError,
    RollbackService,
)
from server.session_pool import SessionPool
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


def _build_session(tmp_path: Path) -> tuple[RollbackService, Path, dict[str, str]]:
    session_id = "rollback-service-test"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()

    import os

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
        inverse_payload={"before_snapshot_id": before.snapshot_id, "after_snapshot_id": after.snapshot_id},
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
    revision_two = revisions.commit_turn(
        turn_two.turn_id,
        message_ids=(second_user.id, second_assistant.id),
        parent_revision_id=revision_one.revision_id,
        workspace_root=str(workspace),
    )
    assert revision_two is not None

    service = RollbackService(
        session_id,
        workspace,
        sessions_dir=sessions_dir,
        enabled=True,
    )
    return service, target, {"target_message_id": second_user.id, "operation_id": operation.operation_id}


def test_preview_is_dry_run_and_execute_requires_confirmation(tmp_path: Path) -> None:
    service, target, ids = _build_session(tmp_path)
    transcript = service.transcript
    original_transcript = transcript.read_text(encoding="utf-8")

    plan = service.preview(target_message_id=ids["target_message_id"], edited_text="new prompt")

    assert plan.status == "approval_required"
    assert plan.plan_hash
    assert ids["operation_id"] in plan.operation_ids
    op = next(item for item in plan.metadata["operations"] if item["operation_id"] == ids["operation_id"])
    assert "preview_diff" in op
    assert "-after" in op["preview_diff"]
    assert "+before" in op["preview_diff"]
    assert target.read_text(encoding="utf-8") == "after\n"
    assert transcript.read_text(encoding="utf-8") == original_transcript

    with pytest.raises(RollbackApprovalError):
        service.execute(
            plan_id=plan.plan_id,
            plan_hash=plan.plan_hash,
            idempotency_key="confirm-later",
            confirmed=False,
        )


def test_execute_restores_files_truncates_transcript_and_is_idempotent(tmp_path: Path) -> None:
    service, target, ids = _build_session(tmp_path)
    plan = service.preview(target_message_id=ids["target_message_id"], edited_text="new prompt")

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="same-request",
        confirmed=True,
    )
    job = result["job"]
    assert job["status"] == "committed"
    assert target.read_text(encoding="utf-8") == "before\n"
    rows = [json.loads(line) for line in service.transcript.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["id"] != ids["target_message_id"]
    assert service.revisions.head() is not None
    assert service.revisions.head().message_ids == (rows[0]["id"], rows[1]["id"])

    retry = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="same-request",
        confirmed=True,
    )
    assert retry["job"]["job_id"] == job["job_id"]
    assert target.read_text(encoding="utf-8") == "before\n"


def test_execute_blocks_when_external_file_change_is_detected(tmp_path: Path) -> None:
    service, target, ids = _build_session(tmp_path)
    plan = service.preview(target_message_id=ids["target_message_id"], edited_text="new prompt")
    target.write_bytes(b"external change\n")

    with pytest.raises(RollbackConflictError):
        service.execute(
            plan_id=plan.plan_id,
            plan_hash=plan.plan_hash,
            idempotency_key="conflict-request",
            confirmed=True,
        )
    rows = service.transcript.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4
    assert target.read_text(encoding="utf-8") == "external change\n"


def test_preview_bootstraps_revision_from_failed_turn(tmp_path: Path) -> None:
    session_id = "failed-turn-bootstrap"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)

    user = Message(role="user", content="delete no remote")
    assistant = Message(role="assistant", content="partial")
    rows = [_row(user), _row(assistant)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    turn = journal.start_turn(user_message_id=user.id)
    assert turn is not None
    journal.transition_turn(
        turn.turn_id,
        "failed",
        error="provider 400",
        message_ids=(user.id, assistant.id),
        assistant_message_id=assistant.id,
        metadata={"before_commit": "abc123"},
    )
    assert revisions.head() is None

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    service.journal = journal
    service.revisions = revisions

    plan = service.preview(target_message_id=user.id, edited_text="delete no remote v2")
    assert plan.target_turn_id == turn.turn_id
    assert service.revisions.head() is not None
    assert user.id in service.revisions.head().message_ids


def test_preview_bootstraps_revision_from_transcript_without_journal(tmp_path: Path) -> None:
    session_id = "transcript-only-bootstrap"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    user1 = Message(role="user", content="first question")
    assistant1 = Message(role="assistant", content="first answer")
    user2 = Message(role="user", content="second question")
    assistant2 = Message(role="assistant", content="second answer")
    rows = [_row(user1), _row(assistant1), _row(user2), _row(assistant2)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    assert service.revisions.head() is None

    plan = service.preview(target_message_id=user1.id, edited_text="first question edited")
    assert plan.metadata["removed_message_count"] == 4
    assert plan.metadata["operations"] == []
    assert service.revisions.head() is not None

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="chat-only",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"
    kept = [json.loads(line) for line in service.transcript.read_text(encoding="utf-8").splitlines()]
    assert len(kept) == 0


def test_preview_waits_then_force_idles_stale_session(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sessions_dir = tmp_path / "sessions"
    session_id = "busy-sess"
    user1 = Message(role="user", content="hello")
    rows = [_row(user1)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    busy = {"flag": True}
    forced: list[str] = []

    def session_busy(_sid: str) -> bool:
        return busy["flag"]

    def on_force_idle(_sid: str) -> None:
        forced.append(_sid)
        busy["flag"] = False

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
        session_busy=session_busy,
        on_force_idle=on_force_idle,
    )
    plan = service.preview(target_message_id=user1.id, edited_text="hello edited")
    assert forced == [session_id]
    assert plan.metadata.get("target_message_id") == user1.id


def test_execute_acquires_pool_busy_lease(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sessions_dir = tmp_path / "sessions"
    session_id = "hold-busy"
    user1 = Message(role="user", content="hello")
    rows = [_row(user1)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    pool = SessionPool(cwd=str(workspace), busy_stale_sec=600)
    other = pool.try_begin(session_id)
    assert other is not None

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
        on_acquire_busy=pool.try_begin,
        on_release_busy=lambda sid, lid: pool.end(sid, lid),
        on_force_idle=pool.force_idle,
    )
    plan = service.preview(target_message_id=user1.id, edited_text="hello edited")
    pool.force_idle(session_id)

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="hold-busy-key",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"
    assert not pool.is_busy(session_id)


def test_chat_only_execute_skips_workspace_restore_when_no_file_ops(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "chat-only-skip-restore"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    import os

    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")
    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)

    user1 = Message(role="user", content="ask me")
    assistant1 = Message(role="assistant", content="sure")
    user2 = Message(role="user", content="again")
    assistant2 = Message(role="assistant", content="reply")
    rows = [_row(m) for m in (user1, assistant1, user2, assistant2)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    turn1 = journal.start_turn(user_message_id=user1.id)
    assert turn1 is not None
    journal.transition_turn(
        turn1.turn_id,
        "committed",
        message_ids=(user1.id, assistant1.id),
        assistant_message_id=assistant1.id,
    )
    rev1 = revisions.commit_turn(
        turn1.turn_id,
        message_ids=(user1.id, assistant1.id),
        workspace_root=str(workspace),
    )
    assert rev1 is not None

    turn2 = journal.start_turn(
        revision_id=rev1.revision_id,
        user_message_id=user2.id,
    )
    assert turn2 is not None
    journal.transition_turn(
        turn2.turn_id,
        "committed",
        message_ids=(user2.id, assistant2.id),
        assistant_message_id=assistant2.id,
    )
    revisions.commit_turn(
        turn2.turn_id,
        message_ids=(user2.id, assistant2.id),
        parent_revision_id=rev1.revision_id,
        workspace_root=str(workspace),
    )

    restore_calls = {"n": 0}

    def _fake_tx_execute(self, *_args, **_kwargs) -> str:
        restore_calls["n"] += 1
        return "restored"

    monkeypatch.setattr(
        "engine.workspace_restore.WorkspaceRestoreTransaction.execute",
        _fake_tx_execute,
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user2.id, edited_text="edited again")
    assert not plan.metadata.get("target_commit")
    assert plan.metadata.get("operations") == []

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="chat-only-skip-restore",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"
    assert restore_calls["n"] == 0


def test_before_commit_triggers_workspace_restore_even_without_ops(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "before-commit-restore"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    import os

    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")
    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)

    user1 = Message(role="user", content="ask me")
    assistant1 = Message(role="assistant", content="sure")
    rows = [_row(user1), _row(assistant1)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    turn1 = journal.start_turn(user_message_id=user1.id)
    assert turn1 is not None
    journal.transition_turn(
        turn1.turn_id,
        "committed",
        message_ids=(user1.id, assistant1.id),
        assistant_message_id=assistant1.id,
        metadata={"before_commit": "commit-abc"},
    )
    revisions.commit_turn(
        turn1.turn_id,
        message_ids=(user1.id, assistant1.id),
        workspace_root=str(workspace),
    )

    restore_calls = {"n": 0, "auto": None}

    def _fake_tx_execute(self, *args, **kwargs) -> str:
        restore_calls["n"] += 1
        restore_calls["auto"] = kwargs.get("auto_trash_created")
        return "restored"

    monkeypatch.setattr(
        "engine.workspace_restore.WorkspaceRestoreTransaction.execute",
        _fake_tx_execute,
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user1.id, edited_text="edited")
    assert plan.metadata.get("target_commit") == "commit-abc"
    assert plan.metadata.get("operations") == []

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="before-commit-restore",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
        full_tree_restore=True,
    )
    assert result["job"]["status"] == "committed"
    assert restore_calls["n"] == 1
    assert restore_calls["auto"] is True


def test_before_commit_skips_full_tree_when_setting_off(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "before-commit-skip-tree"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    import os

    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")
    os.environ.pop("XEYO_REWIND_FULL_TREE", None)
    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)

    user1 = Message(role="user", content="ask me")
    assistant1 = Message(role="assistant", content="sure")
    rows = [_row(user1), _row(assistant1)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    turn1 = journal.start_turn(user_message_id=user1.id)
    assert turn1 is not None
    journal.transition_turn(
        turn1.turn_id,
        "committed",
        message_ids=(user1.id, assistant1.id),
        assistant_message_id=assistant1.id,
        metadata={"before_commit": "commit-abc"},
    )
    revisions.commit_turn(
        turn1.turn_id,
        message_ids=(user1.id, assistant1.id),
        workspace_root=str(workspace),
    )

    restore_calls = {"n": 0}

    def _fake_tx_execute(self, *args, **kwargs) -> str:
        restore_calls["n"] += 1
        return "restored"

    monkeypatch.setattr(
        "engine.workspace_restore.WorkspaceRestoreTransaction.execute",
        _fake_tx_execute,
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user1.id, edited_text="edited")
    assert plan.metadata.get("target_commit") == "commit-abc"

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="before-commit-skip",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
        full_tree_restore=False,
    )
    assert result["job"]["status"] == "committed"
    assert restore_calls["n"] == 0


def test_ops_with_target_commit_use_shadow_scoped_restore(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """With target_commit, restore via shadow path_scope (not journal force)."""
    session_id = "scoped-ops-restore"
    sessions_dir = tmp_path / "sessions"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "snapshots").mkdir()
    import os

    os.environ["XEYO_SNAPSHOTS_DIR"] = str(tmp_path / "snapshots")
    from engine.shadow_git import ShadowGit

    shadow = ShadowGit(workspace)
    before = shadow.snapshot("before")

    target = workspace / "docs"
    target.mkdir()
    path = target / "起步.md"
    path.write_text("after empty", encoding="utf-8")
    shadow.snapshot("after")

    journal = OperationJournal(session_id, sessions_dir=sessions_dir, enabled=True)
    revisions = RevisionStore(session_id, sessions_dir=sessions_dir, enabled=True)
    snapshots = SnapshotStore(session_id, root=tmp_path / "snapshots", enabled=True)

    user = Message(role="user", content="clear file")
    assistant = Message(role="assistant", content="done")
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(_row(m), ensure_ascii=False) + "\n" for m in (user, assistant)),
        encoding="utf-8",
    )

    before_s = snapshots.put_text("full content\n", source_path=str(path), metadata={"role": "before"})
    after_s = snapshots.put_text("after empty", source_path=str(path), metadata={"role": "after"})
    assert before_s and after_s

    turn = journal.start_turn(
        user_message_id=user.id,
        metadata={"before_commit": before},
    )
    assert turn is not None
    op = journal.start_operation(
        turn_id=turn.turn_id,
        revision_id=None,
        tool_name="Edit",
        operation_type="file_edit",
        path=str(path),
        before_hash=before_s.content_hash,
        after_hash=after_s.content_hash,
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
        metadata={"operation_count": 1},
    )

    restore_calls: dict[str, object] = {"n": 0, "scope": None}

    def _fake_tx_execute(self, *_args, **kwargs) -> str:
        restore_calls["n"] = int(restore_calls["n"]) + 1
        restore_calls["scope"] = kwargs.get("path_scope")
        return "restored"

    monkeypatch.setattr(
        "engine.workspace_restore.WorkspaceRestoreTransaction.execute",
        _fake_tx_execute,
    )

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user.id, edited_text="clear file again")
    assert plan.metadata.get("target_commit") == before
    assert plan.status == "approval_required"

    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="scoped-not-full-tree",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
        full_tree_restore=False,
    )
    assert result["job"]["status"] == "committed"
    assert restore_calls["n"] == 1
    scope = restore_calls["scope"]
    assert scope is not None
    assert any("起步.md" in str(p) for p in scope)


def test_chat_only_execute_resets_working_snapshot_and_session_md(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import os

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    os.environ["XEYO_SESSIONS_DIR"] = str(sessions_dir)
    session_id = "chat-only-reset-sidecar"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    user1 = Message(role="user", content="first question")
    assistant1 = Message(role="assistant", content="first answer")
    user2 = Message(role="user", content="second question")
    assistant2 = Message(role="assistant", content="second answer")
    rows = [_row(user1), _row(assistant1), _row(user2), _row(assistant2)]
    transcript = transcript_path(session_id, sessions_dir=sessions_dir)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    from memory.session_md import clear_after_rollback, path_for as session_md_path
    from memory.working import flush, hydrate, path_for as working_path, reset_after_rollback

    stale = hydrate(session_id)
    stale.compact_cursor = 4
    stale.c1_frozen_until = 4
    stale.c2_summary_text = "stale summary of truncated turns"
    stale.speculation = ["old hypothesis"]
    flush(session_id, stale)
    session_md_path(session_id).parent.mkdir(parents=True, exist_ok=True)
    session_md_path(session_id).write_text("# stale session notes", encoding="utf-8")

    service = RollbackService(
        session_id,
        str(workspace),
        sessions_dir=sessions_dir,
        enabled=True,
    )
    plan = service.preview(target_message_id=user2.id, edited_text="second question edited")
    result = service.execute(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        idempotency_key="chat-only-reset-sidecar",
        confirmed=True,
        expected_workspace_revision=str(plan.metadata.get("workspace_revision") or ""),
    )
    assert result["job"]["status"] == "committed"

    reloaded = hydrate(session_id)
    assert reloaded.compact_cursor == 0
    assert reloaded.c1_frozen_until == 0
    assert reloaded.c2_summary_text == ""
    assert reloaded.speculation == []
    assert not session_md_path(session_id).is_file()

    # 辅助函数重复调用仍安全
    reset_after_rollback(session_id)
    clear_after_rollback(session_id)
    assert working_path(session_id).is_file()
