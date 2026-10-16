"""Retired managed models cannot be restored by stale product settings."""

import json

from fastapi.testclient import TestClient


def test_old_settings_do_not_authorize_local_provider(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	monkeypatch.delenv("XEYO_ALLOW_LOCAL_MODEL", raising=False)
	settings = tmp_path / "settings.json"
	settings.write_text(json.dumps({"local_models": {"enabled": True}}))
	from server.deps import local_model_allowed

	assert not local_model_allowed()
	# The explicit mock-HTTP transport is still available to fullstack tests.
	monkeypatch.setenv("XEYO_ALLOW_LOCAL_MODEL", "1")
	assert local_model_allowed()


def test_old_model_config_does_not_allowlist_its_endpoint():
	from server.deps import _iter_configured_base_urls

	assert _iter_configured_base_urls({
		"local_models": {"base_url": "http://127.0.0.1:8080/v1"},
		"profiles": [{"base_url": "https://cloud.example/v1"}],
	}) == ["https://cloud.example/v1"]


def test_management_routes_are_removed(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	from server.app import app

	# No lifespan: a route lookup must never launch a model or mutate user data.
	client = TestClient(app)
	for method, path in [
		("GET", "/v1/local-models"),
		("POST", "/v1/local-models"),
		("POST", "/v1/local-models/start"),
		("POST", "/v1/local-models/stop"),
		("POST", "/v1/local-models/switch"),
		("GET", "/v1/local-models/log"),
	]:
		assert client.request(method, path, json={}).status_code == 404
	assert client.get("/health").status_code == 200
