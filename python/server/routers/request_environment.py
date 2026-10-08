"""Update deferred request settings without starting or altering a running turn."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from model.openai_compat import PROVIDER_PRESETS
from server.deps import _extract_bearer, _resolve_base_url, api_error, fake_model_enabled, local_model_allowed
from server.local_gate import require_loopback
from server.request_environment import REQUEST_ENV_FIELDS, request_environment
from server.routers.chat import ChatCompletionRequest
from server.routers.sessions import require_session_id
from server.session_write_guard import require_writable_session
from server.synthetic_round import env_for, note_request_env

router = APIRouter(tags=["session"], dependencies=[Depends(require_loopback)])


@router.post("/v1/sessions/{session_id}/request-environment")
def update_request_environment(session_id: str, body: ChatCompletionRequest,
	authorization: str | None = Header(default=None)) -> dict[str, object]:
	sid = require_session_id(session_id)
	require_writable_session(sid)
	previous = env_for(sid)
	if previous is None:
		raise api_error(409, "request environment unavailable", "environment_unavailable")
	provider = body.provider or previous.get("provider") or "deepseek"
	if provider not in PROVIDER_PRESETS or (provider == "fake" and not fake_model_enabled()) or (provider == "local" and not local_model_allowed()):
		raise api_error(400, f"unsupported provider: {provider}")
	key = _extract_bearer(authorization)
	if not key and provider not in ("fake", "local"):
		raise api_error(401, "Missing API key", "authentication_error")
	# Workspace ownership stays pinned by the human submit path.
	base_url = body.base_url if "base_url" in body.model_fields_set else (
		previous.get("base_url") if provider == previous.get("provider") else None)
	values = request_environment(body, provider=provider,
		base_url=_resolve_base_url(provider, base_url), api_key=key or "local",
		workspace=previous.get("workspace"))
	updated = dict(previous)
	for field in REQUEST_ENV_FIELDS:
		if field in body.model_fields_set:
			updated[field] = values[field]
	updated.update(provider=provider, base_url=values["base_url"], api_key=values["api_key"], workspace=previous.get("workspace"))
	note_request_env(sid, updated)
	return {"ok": True, "session_id": sid}
