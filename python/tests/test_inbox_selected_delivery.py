"""Selected steer keeps siblings and completes its inbox ownership on delivery."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from engine import t_now_steer
from server import inbox_registry
from server.routers.sessions import session_inbox_item_steer
from session.message_store import MessageStore


@pytest.fixture
def registry(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")
	reg = inbox_registry.InboxRegistry()
	monkeypatch.setattr(inbox_registry, "_registry", reg)
	t_now_steer.clear()
	yield reg
	t_now_steer.clear()


def test_selected_steer_preserves_siblings_on_disk(registry):
	items = [registry.enqueue("selected", text, message_id=text) for text in ("A", "B", "C")]
	asyncio.run(session_inbox_item_steer("selected", items[1].queue_id))
	assert [(i["text"], i["state"]) for i in registry.snapshot("selected")["items"]] == [
		("A", "queued"), ("B", "delivering"), ("C", "queued")
	]
	restarted = inbox_registry.InboxRegistry()
	assert [i["text"] for i in restarted.snapshot("selected")["items"]] == ["A", "B", "C"]


def test_rejected_selected_steer_does_not_drop_siblings(registry, monkeypatch):
	items = [registry.enqueue("rejected", text) for text in ("A", "B", "C")]
	monkeypatch.setattr(t_now_steer, "push", lambda *args, **kwargs: False)
	with pytest.raises(HTTPException) as error:
		asyncio.run(session_inbox_item_steer("rejected", items[1].queue_id))
	assert error.value.status_code == 409
	assert [i["text"] for i in registry.snapshot("rejected")["items"]] == ["A", "B", "C"]
	assert all(i["state"] == "queued" for i in registry.snapshot("rejected")["items"])
	assert [i.text for i in registry.consume_for_boundary("rejected")] == ["A", "B", "C"]


def test_delivered_selected_steer_receipt_does_not_reappear(registry):
	item = registry.enqueue("boundary", "B", message_id="selected-user")
	asyncio.run(session_inbox_item_steer("boundary", item.queue_id))
	landed = t_now_steer.deliver("boundary", MessageStore())
	assert [m.id for m in landed] == ["selected-user"]
	assert registry.finish_boundary_delivery("boundary", [m.id for m in landed]) == 1
	asyncio.run(registry.on_turn_settled("boundary", "succeeded", "", "original-user"))
	assert registry.snapshot("boundary")["items"] == []
	assert registry.finish_boundary_delivery("boundary", ["selected-user"]) == 0
	assert inbox_registry.InboxRegistry().snapshot("boundary")["items"] == []


def test_selected_steer_fallback_reuses_original_slot_then_finishes(registry):
	from server.steer_settle_fallback import fallback_pending
	from server.inbox_persistence import transcript_message_ids

	items = [registry.enqueue("fallback", text, message_id=text) for text in ("A", "B", "C")]
	asyncio.run(session_inbox_item_steer("fallback", items[1].queue_id))
	assert transcript_message_ids("fallback", {"B"}) == set(), "pending inbox ownership is not a delivered transcript row"
	# The first turn ends before another sampling boundary.
	asyncio.run(registry.on_turn_settled("fallback", "succeeded", "", "original-user"))
	assert fallback_pending("fallback") == 1
	snapshot = registry.snapshot("fallback")["items"]
	assert [(i["queue_id"], i["text"], i["state"]) for i in snapshot] == [
		(item.queue_id, item.text, "queued") for item in items
	]
	assert [i.text for i in registry.pop_active("fallback")] == ["A", "B", "C"]
	asyncio.run(registry.on_turn_settled("fallback", "succeeded", "", "A"))
	completed = registry.snapshot("fallback")["items"]
	assert len(completed) == 3
	assert all(i["state"] == "delivered" for i in completed)
	registry.acknowledge_delivered("fallback", [item.queue_id for item in items])
	assert registry.snapshot("fallback")["items"] == []
	assert inbox_registry.InboxRegistry().snapshot("fallback")["items"] == []
