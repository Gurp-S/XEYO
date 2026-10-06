"""Shared SSRF / HTTP helpers for WebFetch and WebSearch."""

from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape as _html_unescape
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
	# 字面 IP
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
		# AWS / 云元数据端点
		if str(ip) == "169.254.169.254":
			return "metadata_ip"
	except ValueError:
		# 主机名——解析后检查；DNS 失败 = 拒绝（不许放行）
		try:
			infos = socket.getaddrinfo(host, None)
		except OSError:
			# 不只 gaierror：Windows 在网络栈抖动时会抛带 winerror 的 OSError，
			# 原来只捕 gaierror 会让"拒绝"这条路径本身以 500 逃出路由。
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


def is_local_inference_url(url: str) -> bool:
	"""是否为"本机/内网推理服务"可接受的地址：http(s) 且主机落在环回或私网单播。

	给 ``provider=local`` 用。本地 llama.cpp 确实要连 ``127.0.0.1`` 或局域网里的
	一台机器，通用 SSRF 门会把这些一起挡掉，所以那条分支需要一条更宽但**有边界**的
	判据。边界是刻意挑明的：放宽只到环回 / RFC1918 / 站点本地单播这一族 ——
	云元数据（169.254.0.0/16 是 link-local，``is_private`` 也把它算作私有，所以
	必须显式排除）、reserved、multicast、unspecified、非 http(s) scheme、以及解析
	不出来的主机名，一概不放行。

	URL 策略只在本模块有一份：调用方不要再自己解析一次 IP。
	"""
	raw = (url or "").strip()
	if not raw:
		return False
	try:
		parsed = urlparse(raw)
	except Exception:  # noqa: BLE001 — 解不出来就不是本机地址
		return False
	if (parsed.scheme or "").lower() not in ("http", "https"):
		return False
	host = (parsed.hostname or "").strip().lower()
	if not host:
		return False
	if host in _PRIVATE_HOSTS or host == "localhost" or host.endswith(".localhost"):
		return True

	def _ok(ip_text: str) -> bool:
		try:
			ip = ipaddress.ip_address(ip_text)
		except ValueError:
			return False
		# 环回先判：Python 把 ``::1`` 也算进 is_reserved，放在后面会被误拒。
		if ip.is_loopback:
			return True
		if ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
			return False
		return bool(ip.is_private)

	try:
		return _ok(host)
	except Exception:  # noqa: BLE001 — 不是字面 IP 就走解析分支
		pass
	# 主机名：解析后逐条检查；解析失败＝拒绝，不因"查不到"而放行。
	try:
		infos = socket.getaddrinfo(host, None)
	except OSError:
		return False
	return bool(infos) and all(_ok(info[4][0]) for info in infos)


def html_to_text(html: str, *, max_chars: int = 1_000_000) -> str:
	text = _SCRIPT_RE.sub(" ", html)
	text = _CHROME_RE.sub(" ", text)
	text = _BR_RE.sub("\n", text)
	text = _BLOCK_CLOSE_RE.sub("\n\n", text)
	text = _TAG_RE.sub(" ", text)
	# 解码必须在剥标签之后：先解码会把正文里的 &lt;script&gt; 当成真标签剥掉。
	text = _html_unescape(text).replace("\xa0", " ")
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
	# 若混有内容词，则丢弃超常见英文噪音词。
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
		# 关键词未命中——返回文档头部（仍比整页便宜）。
		if len(body) > max_chars:
			return body[:max_chars] + "\n… truncated (no prompt match; head)"
		return body

	# 优先得分最高的段落；头部命中之间保持相对顺序。
	# 限制段落数量，避免弱相邻段落稀释焦点。
	top = scored[: max(1, min(5, len(scored)))]
	min_keep = top[0][0]
	# 保留与最高分差 1 以内（或 score>=2）的段落。
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
