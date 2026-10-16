"""Reordering must change durable delivery order without losing concurrent items."""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.inbox_registry import InboxPersistenceError, InboxRegistry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")


def seed():
    registry = InboxRegistry()
    ids = [registry.enqueue("order-test", text, message_id=f"message-{text}").queue_id for text in ("a", "b", "c")]
    return registry, ids


def ids_of(registry):
    return [item["queue_id"] for item in registry.snapshot("order-test")["items"]]


def test_order_survives_restart_and_controls_actual_delivery():
    registry, ids = seed()
    order = [ids[2], ids[0], ids[1]]
    assert registry.reorder("order-test", ids, order)
    recovered = InboxRegistry()
    assert ids_of(recovered) == order
    assert [item.queue_id for item in recovered.pop_active("order-test")] == order


@pytest.mark.parametrize("change", ["enqueue", "cancel", "deliver"])
def test_stale_order_is_rejected_without_changing_new_state(change):
    registry, ids = seed()
    if change == "enqueue":
        registry.enqueue("order-test", "new arrival")
    elif change == "cancel":
        registry.remove("order-test", ids[0])
    else:
        registry.pop_active("order-test")
    before = registry.snapshot("order-test")
    assert not registry.reorder("order-test", ids, ids[::-1])
    assert registry.snapshot("order-test") == before


def test_non_pending_item_keeps_its_position_and_receipt():
    registry, ids = seed()
    # A delivery already owns the middle slot; only queued slots can move.
    item = registry._queues["order-test"][1]
    item.state = "delivering"
    item.delivery_id = "inflight-receipt"
    assert registry.reorder("order-test", [ids[0], ids[2]], [ids[2], ids[0]])
    assert ids_of(registry) == [ids[2], ids[1], ids[0]]
    assert item.delivery_id == "inflight-receipt"


def test_failed_persist_rolls_back_in_memory_and_on_disk(monkeypatch):
    registry, ids = seed()
    monkeypatch.setattr("server.inbox_registry.save_inbox_state", lambda *_args: False)
    with pytest.raises(InboxPersistenceError):
        registry.reorder("order-test", ids, ids[::-1])
    assert ids_of(registry) == ids
    assert ids_of(InboxRegistry()) == ids


def test_duplicate_or_incomplete_permutation_is_rejected():
    registry, ids = seed()
    assert not registry.reorder("order-test", ids, [ids[0], ids[0], ids[2]])
    assert not registry.reorder("order-test", ids, ids[:-1])
    assert ids_of(registry) == ids


def test_route_receipt_conflict_and_archived_protection(monkeypatch):
    import server.inbox_registry as module
    from server.routers import sessions
    registry, ids = seed()
    monkeypatch.setattr(module, "_registry", registry)
    body = sessions.InboxOrderRequest(expected_order=ids, order=ids[::-1])
    assert sessions.session_inbox_reorder("order-test", body)["order"] == ids[::-1]
    with pytest.raises(HTTPException) as conflict:
        sessions.session_inbox_reorder("order-test", body)
    assert conflict.value.status_code == 409
    monkeypatch.setattr("engine.title.read_archive", lambda _sid: {"archived": True})
    with pytest.raises(HTTPException) as archived:
        sessions.session_inbox_reorder("order-test", body)
    assert archived.value.status_code == 403
