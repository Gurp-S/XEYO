"""HTTP helpers for sessions / attach."""

from __future__ import annotations

from typing import Any

import httpx


def make_client(base_url: str, api_key: str = "", timeout: float | None = 60.0) -> httpx.Client:
	headers: dict[str, str] = {"Accept": "application/json"}
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"
	return httpx.Client(
		base_url=base_url.rstrip("/"),
		headers=headers,
		timeout=timeout,
	)


def list_sessions(client: httpx.Client) -> list[dict[str, Any]]:
	r = client.get("/v1/sessions")
	r.raise_for_status()
	data = r.json()
	sessions = data.get("sessions") if isinstance(data, dict) else data
	return list(sessions or [])


def delete_session(client: httpx.Client, session_id: str) -> dict[str, Any]:
	r = client.delete(f"/v1/sessions/{session_id}")
	r.raise_for_status()
	return r.json() if r.content else {"ok": True}


def get_messages(client: httpx.Client, session_id: str) -> dict[str, Any]:
	r = client.get(f"/v1/sessions/{session_id}/messages")
	r.raise_for_status()
	return r.json()


def resolve_permission_http(
	client: httpx.Client,
	request_id: str,
	*,
	approved: bool,
	choice: str | None = None,
) -> bool:
	body: dict[str, Any] = {
		"request_id": request_id,
		"approved": approved,
		"actor": "cli",
	}
	if choice:
		body["outcome"] = choice
	r = client.post("/v1/permission/resolve", json=body)
	r.raise_for_status()
	return bool(r.json().get("ok", True))


def resolve_ask_http(client: httpx.Client, request_id: str, answer: str) -> bool:
	r = client.post(
		"/v1/ask/resolve",
		json={"request_id": request_id, "answer": answer, "actor": "cli"},
	)
	r.raise_for_status()
	return bool(r.json().get("ok", True))


def resolve_plan_http(client: httpx.Client, request_id: str, approved: bool) -> bool:
	r = client.post(
		f"/v1/plan/{request_id}/approve",
		json={"approved": approved, "actor": "cli"},
	)
	r.raise_for_status()
	return bool(r.json().get("ok", True))


def interrupt_http(client: httpx.Client, session_id: str) -> bool:
	r = client.post("/v1/interrupt", json={"session_id": session_id})
	r.raise_for_status()
	return bool(r.json().get("ok", True))
