"""Stop holds pending queue across reads, later settlements and restart."""
from __future__ import annotations

import asyncio

import pytest

from server.inbox_registry import InboxRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.setenv("XEYO_INBOX_AUTORUN", "1")
	return InboxRegistry()


def test_stop_hold_survives_reads_restart_and_another_successful_turn(registry, monkeypatch):
	registry.enqueue("hold", "pending", message_id="queued-user")
	asyncio.run(registry.on_turn_settled("hold", "stopped", "user_stop"))
	for reg in (registry, InboxRegistry()):
		scheduled = []
		monkeypatch.setattr(reg, "_maybe_schedule", lambda sid: scheduled.append(sid))
		for _ in range(4):
			assert reg.snapshot("hold")["paused"] is True
			assert reg.snapshot("hold")["autorun"] is False
		assert scheduled == []
		assert reg.pop_active("hold") == []
		assert reg._pop_first_active("hold") is None
		assert reg.consume_for_boundary("hold") == []
	# Actual scheduler, rather than its spy, enforces the hold on later settlements.
	restarted = InboxRegistry()
	async def later():
		await restarted.on_turn_settled("hold", "succeeded", "", "new-human")
		assert restarted._drain_tasks == {}
	asyncio.run(later())
	assert restarted.snapshot("hold")["items"][0]["text"] == "pending"


def test_only_explicit_resume_releases_hold_and_dispatches(registry):
	registry.enqueue("resume", "pending", message_id="queued-user")
	registry.pause("resume")
	submitted = []
	async def submit(sid, text, **kwargs):
		submitted.append(text)
		return True
	registry._submit = submit
	registry._session_idle = lambda sid: True
	async def run():
		registry.resume("resume")
		await asyncio.sleep(0)
		await asyncio.sleep(0)
	asyncio.run(run())
	assert submitted == ["pending"]
	assert InboxRegistry().snapshot("resume")["paused"] is False


def test_resume_write_failure_keeps_durable_hold(registry, monkeypatch):
	from server.inbox_registry import InboxPersistenceError
	registry.enqueue("failed", "pending")
	registry.pause("failed")
	monkeypatch.setattr("server.inbox_registry.save_inbox_state", lambda *args: False)
	with pytest.raises(InboxPersistenceError): registry.resume("failed")
	assert registry.snapshot("failed")["paused"] is True
