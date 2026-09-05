"""Per-request WebSearch config (SearXNG base URL)."""

from __future__ import annotations

import contextvars
import os
from urllib.parse import urlparse

_searxng_url_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
	"xeyo_searxng_url", default=None
)


def normalize_searxng_url(raw: str | None) -> str:
	"""Return normalized base URL or empty string if invalid/empty."""
	s = (raw or "").strip().rstrip("/")
	if not s:
		return ""
	try:
		parsed = urlparse(s)
	except Exception:
		return ""
	scheme = (parsed.scheme or "").lower()
	if scheme not in ("http", "https"):
		return ""
	if not (parsed.hostname or "").strip():
		return ""
	# Drop path noise beyond root; SearXNG base is origin (+ optional path prefix).
	path = (parsed.path or "").rstrip("/")
	netloc = parsed.netloc
	return f"{scheme}://{netloc}{path}"


def set_searxng_url(url: str | None) -> None:
	normalized = normalize_searxng_url(url)
	_searxng_url_ctx.set(normalized or None)


def get_searxng_url() -> str:
	"""Prefer request context; fall back to XEYO_SEARXNG_URL env."""
	ctx = _searxng_url_ctx.get()
	if ctx:
		return ctx
	return normalize_searxng_url(os.environ.get("XEYO_SEARXNG_URL"))


def is_searxng_base_allowed(url: str) -> str | None:
	"""Allow http(s) including loopback/private for user-configured SearXNG only.

	Returns deny reason or None if allowed.
	"""
	s = normalize_searxng_url(url)
	if not s:
		return "invalid_searxng_url"
	return None
