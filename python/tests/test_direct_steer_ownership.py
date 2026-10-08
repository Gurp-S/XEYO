"""Direct steer has durable pending ownership and enters transcript on delivery."""
from __future__ import annotations

import asyncio

import pytest

from engine import t_now_steer
from server import inbox_registry
from server.boundary_submission import submit_boundary
from server.inbox_persistence import transcript_message_ids
from server.steer_settle_fallback import fallback_pending, on_turn_settled
from session.message_store import MessageStore
from session.record_transcript import record_transcript_sync
from msgtypes.message import assistant_text_message, user_message


@pytest.fixture
def registry(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")
	reg = inbox_registry.InboxRegistry()
	reg._session_idle = lambda sid: False
	monkeypatch.setattr(inbox_registry, "_registry", reg)
	t_now_steer.clear()
	yield reg
	t_now_steer.clear()


def test_pending_direct_steer_recovers_without_premature_transcript(registry):
	item, boundary = submit_boundary(registry, "direct", "pending", media_refs=[], message_id="steer")
	assert boundary
	assert transcript_message_ids("direct", {"steer"}) == set()
	recovered = inbox_registry.InboxRegistry().snapshot("direct")["items"]
	assert [(row["queue_id"], row["text"], row["state"]) for row in recovered] == [(item.queue_id, "pending", "queued")]
	store = MessageStore()
	store.append(user_message("initial", message_id="first"))
	store.append(assistant_text_message("original reply", message_id="reply"))
	record_transcript_sync(store.items, session_id="direct")
	assert [m.id for m in t_now_steer.deliver("direct", store)] == ["steer"]
	assert [m.id for m in store.items] == ["first", "reply", "steer"]
	assert registry.finish_boundary_delivery("direct", ["steer"]) == 1
	assert registry.snapshot("direct")["items"] == []
	assert inbox_registry.InboxRegistry().snapshot("direct")["items"] == []


def test_long_direct_steer_retains_original_owner_on_fallback_and_stop(registry):
	text = "long-steer" * 600
	item, _ = submit_boundary(registry, "long", text, media_refs=[], message_id="long-mid")
	asyncio.run(on_turn_settled("long", "stopped", "user_stop"))
	snapshot = registry.snapshot("long")
	assert snapshot["paused"] is True
	assert [(row["queue_id"], row["text"], row["state"]) for row in snapshot["items"]] == [(item.queue_id, text, "queued")]
	assert t_now_steer.pending_count("long") == 0
	assert fallback_pending("long") == 0
	assert registry.pop_active("long") == []
	assert inbox_registry.InboxRegistry().snapshot("long")["paused"] is True


def test_failed_boundary_admission_keeps_durable_owner(registry, monkeypatch):
	monkeypatch.setattr(t_now_steer, "push", lambda *args, **kwargs: False)
	item, boundary = submit_boundary(registry, "failed", "kept", media_refs=[], message_id=None)
	assert boundary is False
	assert item.message_id
	assert inbox_registry.InboxRegistry().snapshot("failed")["items"][0]["queue_id"] == item.queue_id
	assert registry.snapshot("failed")["items"][0]["state"] == "queued"


def test_failed_durable_admission_does_not_enter_model_queue(registry, monkeypatch):
	monkeypatch.setattr(inbox_registry, "save_inbox_state", lambda *args: False)
	with pytest.raises(inbox_registry.InboxPersistenceError):
		submit_boundary(registry, "unwritten", "kept in draft", media_refs=[], message_id="mid")
	assert t_now_steer.pending_count("unwritten") == 0
	assert registry.snapshot("unwritten")["items"] == []


def test_retried_direct_input_identity_enters_model_history_once(registry):
	for _ in range(2):
		submit_boundary(registry, "retry", "same request", media_refs=[], message_id="same-mid")
	store = MessageStore()
	t_now_steer.deliver("retry", store)
	assert [m.id for m in store.items] == ["same-mid"]
	assert len(registry.snapshot("retry")["items"]) == 1


def test_identical_text_with_distinct_input_ids_remains_two_messages(registry):
	for mid in ("one", "two"):
		submit_boundary(registry, "distinct", "same text", media_refs=[], message_id=mid)
	store = MessageStore()
	t_now_steer.deliver("distinct", store)
	assert [m.id for m in store.items] == ["one", "two"]


def test_input_id_cannot_change_its_pending_content(registry):
	from server.pending_input_identity import InputIdentityConflict
	submit_boundary(registry, "conflict", "first", media_refs=[], message_id="mid")
	with pytest.raises(InputIdentityConflict):
		submit_boundary(registry, "conflict", "changed", media_refs=[], message_id="mid")
	assert [row["text"] for row in registry.snapshot("conflict")["items"]] == ["first"]


def test_settlement_before_boundary_push_cannot_strand_input(registry):
	# The parent settles after HTTP busy detection but before worker admission.
	registry._session_idle = lambda sid: True
	item, boundary = submit_boundary(registry, "late", "arrived late", media_refs=[], message_id="late-mid")
	assert boundary is False
	assert t_now_steer.pending_count("late") == 0
	assert [(row["queue_id"], row["state"]) for row in registry.snapshot("late")["items"]] == [(item.queue_id, "queued")]
