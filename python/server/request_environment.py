"""One field contract for human requests and deferred execution settings."""
from __future__ import annotations

from typing import Any

REQUEST_ENV_FIELDS = (
	"model", "provider", "base_url", "thinking", "reasoning_effort",
	"max_budget_usd", "context_limit", "max_tokens", "permission_preset",
	"permission_mode", "workspace", "agent_mode", "multi_agent",
	"output_compact", "output_mode", "code_compact", "code_mode",
	"browser_preview_url", "searxng_url",
)


def request_environment(body: Any, *, provider: str, base_url: str,
	api_key: str, workspace: str | None) -> dict[str, Any]:
	values = {field: getattr(body, field, None) for field in REQUEST_ENV_FIELDS}
	values.update(provider=provider, base_url=base_url, api_key=api_key, workspace=workspace)
	return values
