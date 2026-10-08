import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.routers import sessions


@pytest.fixture
def transcript_client(monkeypatch, tmp_path):
	path = tmp_path / "transcript.jsonl"
	monkeypatch.setattr(sessions, "transcript_path", lambda _sid: path)
	monkeypatch.setattr(sessions, "transcript_read_paths", lambda _path: [path])
	monkeypatch.setattr(sessions, "_pool", SimpleNamespace(
		get_if_present=lambda _sid: None, session_cwd=lambda _sid: "", cwd="",
	))
	return TestClient(app), path


@pytest.mark.parametrize("bad_line", ["{broken json", "[]", "null", "42"])
def test_skipped_transcript_rows_are_reported_as_degraded(transcript_client, bad_line):
	client, path = transcript_client
	path.write_text(json.dumps({"role": "user", "content": "hello"}) + "\n" + bad_line + "\n", encoding="utf-8")
	response = client.get("/v1/sessions/integrity-test/messages")
	assert response.status_code == 200
	receipt = response.json()
	assert receipt["transcript_found"] is True
	assert receipt["skipped_lines"] == 1
	assert receipt["degraded"] is True


def test_failed_archive_read_is_not_a_complete_snapshot(transcript_client, monkeypatch, tmp_path):
	client, path = transcript_client
	path.write_text(json.dumps({"role": "user", "content": "hello"}) + "\n", encoding="utf-8")
	archive = tmp_path / "old.jsonl"
	archive.write_bytes(b"\xff\xfe\xff")
	monkeypatch.setattr(sessions, "transcript_read_paths", lambda _path: [archive, path])
	receipt = client.get("/v1/sessions/integrity-test/messages").json()
	assert receipt["degraded"] is True
	assert len(receipt["read_errors"]) == 1


def test_clean_transcript_is_a_complete_snapshot(transcript_client):
	client, path = transcript_client
	path.write_text(json.dumps({"role": "user", "content": "hello"}) + "\n", encoding="utf-8")
	receipt = client.get("/v1/sessions/integrity-test/messages").json()
	assert receipt["degraded"] is False
	assert receipt["skipped_lines"] == 0
	assert receipt["read_errors"] == []
