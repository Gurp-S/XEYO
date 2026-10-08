from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from engine import turn_snapshot
from server.app import app
from server.routers import sessions


@pytest.fixture
def recovery(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	monkeypatch.setattr(sessions, "_pool", SimpleNamespace(is_busy=lambda _sid: False))
	snap = turn_snapshot.TurnSnapshot(session_id="recovery-identity-test", turn_id="old", status="recovery_required")
	turn_snapshot.flush(snap)
	return TestClient(app), snap


def test_stale_abandonment_cannot_stop_a_new_turn(recovery):
	client, snap = recovery
	snap.turn_id = "new"
	snap.status = "running"
	turn_snapshot.flush(snap)
	response = client.post(f"/v1/sessions/{snap.session_id}/recovery/abandon", json={"turn_id": "old"})
	assert response.status_code == 409
	assert turn_snapshot.hydrate(snap.session_id).status == "running"


def test_abandonment_requires_an_explicit_turn_identity(recovery):
	client, snap = recovery
	assert client.post(f"/v1/sessions/{snap.session_id}/recovery/abandon").status_code == 422
	assert turn_snapshot.hydrate(snap.session_id).status == "recovery_required"


def test_matching_recovery_can_be_abandoned_idempotently(recovery):
	client, snap = recovery
	for _ in range(2):
		response = client.post(f"/v1/sessions/{snap.session_id}/recovery/abandon", json={"turn_id": "old"})
		assert response.status_code == 200
		assert response.json()["turn_id"] == "old"
	assert turn_snapshot.hydrate(snap.session_id).status == "stopped"


def test_failed_persistence_is_not_an_accepted_abandonment(recovery, monkeypatch):
	client, snap = recovery
	def fail(*_args, **_kwargs):
		raise OSError("disk unavailable")
	monkeypatch.setattr(turn_snapshot, "_atomic_write", fail)
	response = client.post(f"/v1/sessions/{snap.session_id}/recovery/abandon", json={"turn_id": "old"})
	assert response.status_code == 503
	assert turn_snapshot.hydrate(snap.session_id).status == "recovery_required"


def test_busy_execution_cannot_be_abandoned(recovery, monkeypatch):
	client, snap = recovery
	monkeypatch.setattr(sessions, "_pool", SimpleNamespace(is_busy=lambda _sid: True))
	assert client.post(f"/v1/sessions/{snap.session_id}/recovery/abandon", json={"turn_id": "old"}).status_code == 409
	assert turn_snapshot.hydrate(snap.session_id).status == "recovery_required"


def test_archived_recovery_is_read_only(recovery, monkeypatch):
	from engine import title
	client, snap = recovery
	monkeypatch.setattr(title, "read_archive", lambda _sid: {"archived": True})
	assert client.post(f"/v1/sessions/{snap.session_id}/recovery/abandon", json={"turn_id": "old"}).status_code == 409
	assert turn_snapshot.hydrate(snap.session_id).status == "recovery_required"


def test_abandonment_and_new_turn_flush_share_the_same_lock(recovery, monkeypatch):
	from server import recovery_abandon
	client, snap = recovery
	entered = threading.Event()
	release = threading.Event()
	started_write = threading.Event()
	read = turn_snapshot.hydrate
	monkeypatch.setattr(recovery_abandon, "get_turn_runner", lambda: SimpleNamespace(get_public=lambda _sid: None))
	def gated_read(sid):
		value = read(sid)
		if not entered.is_set():
			entered.set()
			assert release.wait(timeout=5)
		return value
	monkeypatch.setattr(turn_snapshot, "hydrate", gated_read)
	def new_turn():
		started_write.set()
		turn_snapshot.flush(turn_snapshot.TurnSnapshot(session_id=snap.session_id, turn_id="new", status="running"))
	with ThreadPoolExecutor(max_workers=2) as workers:
		abandon = workers.submit(client.post, f"/v1/sessions/{snap.session_id}/recovery/abandon", json={"turn_id": "old"})
		try:
			assert entered.wait(timeout=5)
			write = workers.submit(new_turn)
			assert started_write.wait(timeout=5)
			assert not write.done()
		finally:
			release.set()
		assert abandon.result(timeout=5).status_code == 200
		write.result(timeout=5)
	assert read(snap.session_id).turn_id == "new"
	assert read(snap.session_id).status == "running"
