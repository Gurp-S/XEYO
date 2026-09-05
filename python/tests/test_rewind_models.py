from __future__ import annotations

from rewind.models import (
    ApprovalRecord,
    AuditEvent,
    OperationRecord,
    RecoveryJob,
    RollbackPlan,
    SessionRevision,
    SnapshotManifest,
    TurnRecord,
)


def test_core_models_round_trip_without_raw_file_bodies() -> None:
    revision = SessionRevision(
        session_id="session-1",
        turn_ids=("turn-1",),
        message_ids=("msg-1", "msg-2"),
        metadata={"source": "test"},
    )
    raw = revision.to_dict()
    restored = SessionRevision.from_dict(raw)

    assert restored.session_id == "session-1"
    assert restored.turn_ids == ("turn-1",)
    assert restored.message_ids == ("msg-1", "msg-2")
    assert raw["turn_ids"] == ["turn-1"]

    operation = OperationRecord(
        session_id="session-1",
        turn_id="turn-1",
        path="src/app.py",
        before_hash="a" * 64,
        after_hash="b" * 64,
        inverse_kind="restore_snapshot",
        inverse_payload={"before_snapshot_id": "snap_1"},
    )
    operation_raw = operation.to_dict()
    assert "old_content" not in operation_raw
    assert "new_content" not in operation_raw
    assert operation_raw["inverse_payload"] == {"before_snapshot_id": "snap_1"}
    assert OperationRecord.from_dict(operation_raw).path == "src/app.py"


def test_all_enterprise_models_are_json_serializable() -> None:
    models = [
        TurnRecord(session_id="s"),
        SnapshotManifest(session_id="s", content_hash="a" * 64),
        RollbackPlan(session_id="s", operation_ids=("op_1",)),
        ApprovalRecord(session_id="s", plan_id="plan_1", plan_hash="hash"),
        RecoveryJob(session_id="s", plan_id="plan_1", applied_operation_ids=("op_1",)),
        AuditEvent(session_id="s", event_type="preview"),
    ]
    for model in models:
        data = model.to_dict()
        restored = type(model).from_dict(data)
        assert restored.to_dict() == data
