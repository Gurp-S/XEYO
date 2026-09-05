"""Shared SSRF / HTTP helpers for WebFetch and WebSearch."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

_PRIVATE_HOSTS = frozenset(
	{
		"localhost",
		"localhost.",
		"metadata.google.internal",
	}
)


def is_blocked_url(url: str) -> str | None:
	"""Return deny reason, or None if allowed."""
	raw = (url or "").strip()
	if not raw:
		return "empty_url"
	try:
		parsed = urlparse(raw)
	except Exception:
		return "invalid_url"
	scheme = (parsed.scheme or "").lower()
	if scheme not in ("http", "https"):
		return f"scheme_not_allowed:{scheme or 'none'}"
	host = (parsed.hostname or "").strip().lower()
	if not host:
		return "missing_host"
	if host in _PRIVATE_HOSTS or host.endswith(".localhost"):
		return "private_host"
	# Literal IP
	try:
		ip = ipaddress.ip_address(host)
		if (
			ip.is_private
			or ip.is_loopback
			or ip.is_link_local
			or ip.is_reserved
			or ip.is_multicast
			or ip.is_unspecified
		):
			return "private_ip"
		# AWS / cloud metadata
		if str(ip) == "169.254.169.254":
			return "metadata_ip"
	except ValueError:
		# hostname — resolve and check; DNS failure = deny (do not allow-through)
		try:
			infos = socket.getaddrinfo(host, None)
		except socket.gaierror:
			return "dns_failed"
		for info in infos:
			addr = info[4][0]
			try:
				ip = ipaddress.ip_address(addr)
			except ValueError:
				continue
			if (
				ip.is_private
				or ip.is_loopback
				or ip.is_link_local
				or ip.is_reserved
				or ip.is_multicast
				or ip.is_unspecified
				or str(ip) == "169.254.169.254"
			):
				return "resolves_to_private_ip"
	return None


_CHROME_RE = re.compile(
	r"<(nav|footer|aside|header|form|iframe|svg|noscript)\b[^>]*>.*?</\1>",
	re.I | re.S,
)
_SCRIPT_RE = re.compile(
	r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>",
	re.I | re.S,
)
_BLOCK_CLOSE_RE = re.compile(
	r"</(p|div|h[1-6]|li|tr|section|article|br)\s*>",
	re.I,
)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+\n")
_MULTI_NL = re.compile(r"\n{3,}")
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{1,}")


def html_to_text(html: str, *, max_chars: int = 1_000_000) -> str:
	text = _SCRIPT_RE.sub(" ", html)
	text = _CHROME_RE.sub(" ", text)
	text = _BR_RE.sub("\n", text)
	text = _BLOCK_CLOSE_RE.sub("\n\n", text)
	text = _TAG_RE.sub(" ", text)
	text = (
		text.replace("&nbsp;", " ")
		.replace("&amp;", "&")
		.replace("&lt;", "<")
		.replace("&gt;", ">")
		.replace("&quot;", '"')
		.replace("&#39;", "'")
	)
	text = _WS_RE.sub("\n", text)
	text = _MULTI_NL.sub("\n\n", text)
	text = re.sub(r"[ \t]{2,}", " ", text).strip()
	if len(text) > max_chars:
		text = text[:max_chars] + "\n… truncated"
	return text


def focus_text(text: str, prompt: str, *, max_chars: int) -> str:
	"""Keep paragraphs that best match prompt tokens; fall back to head."""
	prompt = (prompt or "").strip()
	body = (text or "").strip()
	if not body:
		return body
	if not prompt:
		if len(body) > max_chars:
			return body[:max_chars] + "\n… truncated"
		return body

	tokens = {t.lower() for t in _TOKEN_RE.findall(prompt)}
	# Drop ultra-common English noise if mixed with content tokens.
	stop = {
		"the",
		"and",
		"for",
		"with",
		"from",
		"this",
		"that",
		"what",
		"how",
		"are",
		"is",
		"of",
		"to",
		"in",
		"on",
		"a",
		"an",
		"does",
		"do",
		"did",
		"can",
		"will",
		"about",
		"into",
		"over",
		"under",
		"when",
		"where",
		"which",
		"who",
		"why",
		"work",
		"works",
		"working",
	}
	tokens -= stop
	paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
	if not paras:
		paras = [body]

	if not tokens:
		joined = "\n\n".join(paras)
		if len(joined) > max_chars:
			return joined[:max_chars] + "\n… truncated"
		return joined

	scored: list[tuple[int, int, str]] = []
	for i, p in enumerate(paras):
		low = p.lower()
		score = sum(1 for t in tokens if t in low)
		if score > 0:
			scored.append((score, -i, p))
	scored.sort(reverse=True)

	if not scored:
		# No keyword hit — return document head (still cheaper than full page).
		if len(body) > max_chars:
			return body[:max_chars] + "\n… truncated (no prompt match; head)"
		return body

	# Prefer highest-scoring paragraphs; keep relative order among top hits.
	# Cap how many paras we take so weak neighbors don't dilute focus.
	top = scored[: max(1, min(5, len(scored)))]
	min_keep = top[0][0]
	# Keep paras within 1 of best score (or score>=2).
	top = [t for t in top if t[0] >= max(1, min_keep - 1) and (t[0] >= 2 or min_keep == 1)]
	if not top:
		top = scored[:1]
	chosen = sorted(top, key=lambda x: -x[1])  # original order
	parts: list[str] = []
	total = 0
	for _score, _neg_i, p in chosen:
		extra = len(p) + (2 if parts else 0)
		if total + extra > max_chars and parts:
			break
		parts.append(p)
		total += extra
		if total >= max_chars:
			break
	out = "\n\n".join(parts)
	if len(out) > max_chars:
		out = out[:max_chars] + "\n… truncated"
	elif len(out) < len(body):
		out = out + "\n… focused"
	return out
