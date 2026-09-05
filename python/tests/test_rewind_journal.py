from __future__ import annotations

import json

import pytest

from rewind.journal import OperationJournal


def test_journal_persists_turn_operation_and_audit(tmp_path) -> None:
    journal = OperationJournal("session-1", sessions_dir=tmp_path, enabled=True)

    turn = journal.start_turn(revision_id="rev_1", user_message_id="msg_1")
    assert turn is not None
    assert turn.status == "running"

    operation = journal.start_operation(
        turn_id=turn.turn_id,
        revision_id="rev_1",
        tool_name="Write",
        operation_type="file_write",
        path="src/app.py",
    )
    assert operation is not None
    completed = journal.transition_operation(
        operation.operation_id,
        "completed",
        before_hash="0" * 64,
        after_hash="1" * 64,
        inverse_kind="restore_snapshot",
        inverse_payload={"before_snapshot_id": "snap_1"},
    )
    assert completed is not None
    assert completed.status == "completed"

    finished = journal.transition_turn(
        turn.turn_id,
        "committed",
        message_ids=("msg_1", "msg_2"),
        operation_ids=(operation.operation_id,),
        assistant_message_id="msg_2",
        stop_reason="end_turn",
    )
    assert finished is not None
    assert finished.status == "committed"

    audit = journal.audit(
        "turn_committed",
        revision_id="rev_1",
        turn_id=turn.turn_id,
        payload={"operation_count": 1},
    )
    assert audit is not None

    assert journal.get_turn(turn.turn_id).status == "committed"
    operations = journal.list_operations(turn_id=turn.turn_id)
    assert len(operations) == 1
    assert operations[0].after_hash == "1" * 64
    assert len(journal.list_audit()) == 1

    assert (tmp_path / "session-1" / "operations.jsonl").is_file()
    raw_lines = (tmp_path / "session-1" / "operations.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 2
    assert json.loads(raw_lines[0])["status"] == "started"
    assert json.loads(raw_lines[1])["status"] == "completed"


def test_journal_is_disabled_by_default_without_writing(tmp_path) -> None:
    journal = OperationJournal("session-2", sessions_dir=tmp_path, enabled=False)
    assert journal.start_turn() is None
    assert journal.start_operation(tool_name="Write") is None
    assert not (tmp_path / "session-2").exists()


def test_invalid_state_transition_is_rejected(tmp_path) -> None:
    journal = OperationJournal("session-3", sessions_dir=tmp_path, enabled=True)
    turn = journal.start_turn()
    assert turn is not None
    journal.transition_turn(turn.turn_id, "failed", error="boom")
    with pytest.raises(ValueError, match="invalid turn transition"):
        journal.transition_turn(turn.turn_id, "committed")

    operation = journal.start_operation(tool_name="Edit")
    assert operation is not None
    journal.transition_operation(operation.operation_id, "cancelled")
    with pytest.raises(ValueError, match="invalid operation transition"):
        journal.transition_operation(operation.operation_id, "completed")
