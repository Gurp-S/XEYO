"""Queued turns read the current environment and forward the whole contract."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server import synthetic_round


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.setenv("XEYO_ALLOW_FAKE_MODEL", "1")
	synthetic_round.clear_request_envs()
	yield
	synthetic_round.clear_request_envs()


@pytest.mark.asyncio
async def test_settings_update_then_synthetic_uses_latest_whole_environment(monkeypatch):
	synthetic_round.note_request_env("latest", {"model": "old", "provider": "fake", "api_key": "local", "workspace": "pinned"})
	settings = {"model": "new", "provider": "fake", "max_tokens": 5432,
		"agent_mode": "ask", "multi_agent": True, "output_compact": True,
		"output_mode": "ultra", "code_compact": True, "code_mode": "full",
		"context_limit": 90000, "thinking": "enabled", "reasoning_effort": "high",
		"browser_preview_url": "https://example.com", "searxng_url": "http://localhost:8080",
		"workspace": "cannot-repin"}
	client = TestClient(app)
	response = client.post("/v1/sessions/latest/request-environment", json=settings)
	assert response.status_code == 200
	assert response.json() == {"ok": True, "session_id": "latest"}
	captured = {}
	async def invoke(app, scope, body):
		captured.update(json.loads(body))
		return 200
	monkeypatch.setattr(synthetic_round, "_invoke_asgi_head", invoke)
	assert await synthetic_round.submit_synthetic("latest", "queued input", surface="inbox")
	for key, value in settings.items():
		assert captured[key] == ("pinned" if key == "workspace" else value)
	assert captured["queue_if_busy"] is False
	assert captured["messages"][0]["content"] == "queued input"


def test_environment_update_cannot_create_an_unknown_session_or_bypass_provider_gate(monkeypatch):
	client = TestClient(app)
	assert client.post("/v1/sessions/unknown/request-environment", json={"model": "fake", "provider": "fake"}).status_code == 409
	synthetic_round.note_request_env("known", {"model": "old"})
	monkeypatch.setenv("XEYO_ALLOW_FAKE_MODEL", "0")
	assert client.post("/v1/sessions/known/request-environment", json={"model": "fake", "provider": "fake"}).status_code == 400
	assert synthetic_round.env_for("known")["model"] == "old"


def test_partial_tui_model_update_preserves_limits_and_explicit_null_clears_them():
	synthetic_round.note_request_env("partial", {"model": "old", "provider": "fake", "max_tokens": 1234, "context_limit": 90000})
	client = TestClient(app)
	assert client.post("/v1/sessions/partial/request-environment", json={"model": "new", "provider": "fake"}).status_code == 200
	assert synthetic_round.env_for("partial")["max_tokens"] == 1234
	assert client.post("/v1/sessions/partial/request-environment", json={"model": "new", "provider": "fake", "max_tokens": None}).status_code == 200
	assert synthetic_round.env_for("partial")["max_tokens"] is None
