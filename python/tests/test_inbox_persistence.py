"""Inbox crash recovery and durable acknowledgement regressions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from server.inbox_persistence import inbox_state_path
from server.inbox_registry import InboxPersistenceError, InboxRegistry


@pytest.fixture(autouse=True)
def isolate_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")


def test_queued_items_survive_a_registry_restart():
    first = InboxRegistry()
    queued = first.enqueue("session-a", "resume after restart", message_id="user-1")

    recovered = InboxRegistry().snapshot("session-a")["items"]

    assert len(recovered) == 1
    assert recovered[0]["queue_id"] == queued.queue_id
    assert recovered[0]["state"] == "queued"
    assert recovered[0]["message_id"] == "user-1"


def test_delivering_without_transcript_anchor_returns_to_queue(monkeypatch):
    first = InboxRegistry()
    first.enqueue("session-a", "retry this")
    first.pop_active("session-a")
    monkeypatch.setattr(
        "server.inbox_registry.transcript_message_ids", lambda _sid, _targets: set()
    )

    recovered = InboxRegistry().snapshot("session-a")["items"]

    assert len(recovered) == 1
    assert recovered[0]["state"] == "queued"
    assert recovered[0]["delivery_id"] is None


def test_delivering_with_transcript_anchor_becomes_receipt(monkeypatch):
    first = InboxRegistry()
    first.enqueue("session-a", "already landed", message_id="anchor-1")
    first.pop_active("session-a")
    monkeypatch.setattr(
        "server.inbox_registry.transcript_message_ids",
        lambda _sid, _targets: {"anchor-1"},
    )

    recovered = InboxRegistry().snapshot("session-a")["items"]

    assert len(recovered) == 1
    assert recovered[0]["state"] == "delivered"
    assert recovered[0]["delivery_id"] == "anchor-1"


def test_acknowledgement_removes_durable_receipt():
    registry = InboxRegistry()
    item = registry.enqueue("session-a", "complete", message_id="anchor-1")

    async def accepted(*_args, **_kwargs):
        return True

    registry._submit = accepted
    asyncio.run(registry._drain_batch("session-a"))
    asyncio.run(registry.on_turn_settled("session-a", "succeeded", "", "anchor-1"))
    assert inbox_state_path("session-a").is_file()

    assert registry.acknowledge_delivered("session-a", [item.queue_id]) == 1

    assert not inbox_state_path("session-a").exists()


def test_dropping_a_session_removes_queued_content():
    registry = InboxRegistry()
    registry.enqueue("session-a", "remove private queued text")
    assert inbox_state_path("session-a").is_file()

    registry.drop_session("session-a")

    assert not inbox_state_path("session-a").exists()
    assert InboxRegistry().snapshot("session-a")["items"] == []


def test_enqueue_fails_closed_when_durable_write_fails(monkeypatch):
    registry = InboxRegistry()
    monkeypatch.setattr("server.inbox_registry.save_inbox_state", lambda *_args: False)

    with pytest.raises(InboxPersistenceError):
        registry.enqueue("session-a", "must not be accepted")

    assert registry.snapshot("session-a")["items"] == []


def test_inbox_files_are_isolated_from_normalized_id_collisions():
    assert inbox_state_path("session:a") != inbox_state_path("session__a")
