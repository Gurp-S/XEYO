"""远程 channel token 认证。"""

from __future__ import annotations

import os
import secrets


def remote_token() -> str:
	return os.environ.get("XEYO_REMOTE_TOKEN", "").strip()


def remote_enabled() -> bool:
	return bool(remote_token())


def extract_bearer(authorization: str | None) -> str:
	if not authorization:
		return ""
	parts = authorization.split(" ", 1)
	if len(parts) == 2 and parts[0].lower() == "bearer":
		return parts[1].strip()
	return authorization.strip()


def resolve_presented_token(
	authorization: str | None,
	x_remote_token: str | None,
) -> str:
	if x_remote_token and x_remote_token.strip():
		return x_remote_token.strip()
	return extract_bearer(authorization)


def verify_remote_token(
	authorization: str | None = None,
	x_remote_token: str | None = None,
) -> None:
	"""认证失败时抛出带短码的 ValueError。

	调用方将码映射为 HTTP 状态：
	- disabled → 503
	- missing / invalid → 401
	"""
	expected = remote_token()
	if not expected:
		raise ValueError("disabled")
	presented = resolve_presented_token(authorization, x_remote_token)
	if not presented:
		raise ValueError("missing")
	if not secrets.compare_digest(presented, expected):
		raise ValueError("invalid")
