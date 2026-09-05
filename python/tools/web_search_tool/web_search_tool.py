"""WebSearch — public web search (outbound ASK)."""

from __future__ import annotations

import asyncio
import os
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.web_common import is_blocked_url
from tools.web_search_tool.config import (
	get_searxng_url,
	is_searxng_base_allowed,
	normalize_searxng_url,
)
from tools.web_search_tool.prompt import DESCRIPTION, WEB_SEARCH_TOOL_NAME

# 连接超时短：快速失败；HTML/JSON 读取给更长超时。
_CONNECT_S = 3.0
_READ_S = 15.0
_DEFAULT_COUNT = 3
_SNIPPET_MAX = 160
_OUT_CAP = 4096
_DDG = "https://html.duckduckgo.com/html/?q="
_DDG_LITE = "https://lite.duckduckgo.com/lite/?q="
_BING = "https://www.bing.com/search?q="
_MOJEEK = "https://www.mojeek.com/search?q="
_BRAVE = "https://api.search.brave.com/res/v1/web/search"
_UA = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
	"AppleWebKit/537.36 (KHTML, like Gecko) "
	"Chrome/120.0.0.0 Safari/537.36"
)


def _include_ddg() -> bool:
	return (os.environ.get("XEYO_WEBSEARCH_INCLUDE_DDG") or "").strip().lower() in (
		"1",
		"true",
		"yes",
	)


class WebSearchTool:
	name = WEB_SEARCH_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"required": ["query"],
				"properties": {
					"query": {
						"type": "string",
						"description": "Search query.",
					},
					"count": {
						"type": "integer",
						"description": "Max results (1–10). Default 3.",
					},
				},
				"additionalProperties": False,
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = input or {}
		query = str(raw.get("query") or "").strip()
		if not query:
			return ToolResult(content="query is required", is_error=True)
		try:
			count = int(raw.get("count") or _DEFAULT_COUNT)
		except (TypeError, ValueError):
			count = _DEFAULT_COUNT
		count = max(1, min(10, count))

		try:
			import httpx
		except ImportError:
			return ToolResult(content="httpx is not installed", is_error=True)

		errors: list[str] = []

		# 1) 已配置则用 SearXNG
		searx = get_searxng_url()
		if searx:
			abort.raise_if_aborted()
			try:
				results = await _searxng_search(httpx, searx, query, count, abort)
			except Exception as e:  # noqa: BLE001
				errors.append(f"searxng: {type(e).__name__}: {e}")
				results = []
			if results:
				return ToolResult(
					content=_format_results(query, "searxng", results),
					is_error=False,
				)
			if not results:
				errors.append("searxng: no results parsed")

		# 2) 可选 Brave（环境变量密钥）
		brave_key = (os.environ.get("XEYO_BRAVE_API_KEY") or "").strip()
		if brave_key:
			abort.raise_if_aborted()
			try:
				results = await _brave_search(httpx, query, count, abort)
			except Exception as e:  # noqa: BLE001
				errors.append(f"brave: {type(e).__name__}: {e}")
				results = []
			if results:
				return ToolResult(
					content=_format_results(query, "brave", results),
					is_error=False,
				)
			errors.append("brave: no results parsed")

		# 3) Bing ∥ Mojeek 竞速
		abort.raise_if_aborted()
		race_name, race_results, race_errs = await _race_bing_mojeek(
			httpx, query, count, abort
		)
		errors.extend(race_errs)
		if race_results:
			return ToolResult(
				content=_format_results(query, race_name, race_results),
				is_error=False,
			)

		# 4) 可选启用 DDG
		if _include_ddg():
			for name, fn in (
				("duckduckgo", _ddg_search),
				("duckduckgo-lite", _ddg_lite_search),
			):
				abort.raise_if_aborted()
				try:
					results = await fn(httpx, query, count, abort)
				except Exception as e:  # noqa: BLE001
					errors.append(f"{name}: {type(e).__name__}: {e}")
					continue
				if results:
					return ToolResult(
						content=_format_results(query, name, results),
						is_error=False,
					)
				errors.append(f"{name}: no results parsed")

		hint = (
			"All search providers failed (timeout/blocked is common without proxy). "
			"Set SearXNG URL in Settings (or XEYO_SEARXNG_URL), or use a known "
			"https URL with WebFetch."
		)
		detail = "; ".join(errors[:4]) if errors else "unknown"
		return ToolResult(
			content=f"search provider failed: {detail}\n{hint}"[:800],
			is_error=True,
		)


def _clip_snippet(text: str) -> str:
	s = " ".join((text or "").split())
	if len(s) <= _SNIPPET_MAX:
		return s
	return s[: _SNIPPET_MAX - 1] + "…"


def _format_results(
	query: str, provider: str, results: list[dict[str, str]]
) -> str:
	lines = [f"Query: {query}", f"provider: {provider}"]
	for i, r in enumerate(results, 1):
		lines.append(f"{i}. {r['title']}")
		lines.append(f"   {r['url']}")
		snip = _clip_snippet(r.get("snippet") or "")
		if snip:
			lines.append(f"   {snip}")
	body = "\n".join(lines)
	if len(body) > _OUT_CAP:
		return body[: _OUT_CAP - 14] + "\n…(truncated)"
	return body


def _timeout(httpx: Any) -> Any:
	return httpx.Timeout(_READ_S, connect=_CONNECT_S)


async def _result_item(title: str, url: str, snippet: str) -> dict[str, str] | None:
	url = (url or "").strip()
	# is_blocked_url 对域名走同步 DNS（无超时）——挪线程防冻结事件循环。
	import asyncio

	if not url.startswith("http") or await asyncio.to_thread(is_blocked_url, url):
		return None
	return {
		"title": (title or url).strip() or url,
		"url": url,
		"snippet": (snippet or "").strip(),
	}


async def _race_bing_mojeek(
	httpx: Any, query: str, count: int, abort: AbortController
) -> tuple[str, list[dict[str, str]], list[str]]:
	"""Return (provider, results, errors). First non-empty wins."""
	errors: list[str] = []

	async def run(name: str, fn: Any) -> tuple[str, list[dict[str, str]], str | None]:
		try:
			out = await fn(httpx, query, count, abort)
			return name, out or [], None
		except Exception as e:  # noqa: BLE001
			return name, [], f"{name}: {type(e).__name__}: {e}"

	tasks = [
		asyncio.create_task(run("bing", _bing_search)),
		asyncio.create_task(run("mojeek", _mojeek_search)),
	]
	pending = set(tasks)
	winner: tuple[str, list[dict[str, str]]] | None = None
	try:
		while pending and winner is None:
			abort.raise_if_aborted()
			done, pending = await asyncio.wait(
				pending, return_when=asyncio.FIRST_COMPLETED
			)
			for t in done:
				name, results, err = t.result()
				if err:
					errors.append(err)
				elif results:
					winner = (name, results)
				else:
					errors.append(f"{name}: no results parsed")
	finally:
		for t in pending:
			t.cancel()
		if pending:
			await asyncio.gather(*pending, return_exceptions=True)

	if winner:
		return winner[0], winner[1], errors
	return "", [], errors


async def _searxng_search(
	httpx: Any,
	base: str,
	query: str,
	count: int,
	abort: AbortController,
) -> list[dict[str, str]]:
	abort.raise_if_aborted()
	base_n = normalize_searxng_url(base)
	deny = is_searxng_base_allowed(base_n)
	if deny:
		raise RuntimeError(deny)
	url = f"{base_n}/search"
	params = {"q": query, "format": "json"}
	async with httpx.AsyncClient(timeout=_timeout(httpx)) as client:
		resp = await client.get(url, params=params)
		resp.raise_for_status()
		data = resp.json()
	out: list[dict[str, str]] = []
	for item in data.get("results") or []:
		if not isinstance(item, dict):
			continue
		row = await _result_item(
			str(item.get("title") or ""),
			str(item.get("url") or ""),
			str(item.get("content") or item.get("snippet") or ""),
		)
		if not row:
			continue
		out.append(row)
		if len(out) >= count:
			break
	return out


async def _brave_search(
	httpx: Any, query: str, count: int, abort: AbortController
) -> list[dict[str, str]]:
	abort.raise_if_aborted()
	key = (os.environ.get("XEYO_BRAVE_API_KEY") or "").strip()
	headers = {"Accept": "application/json", "X-Subscription-Token": key}
	params = {"q": query, "count": count}
	async with httpx.AsyncClient(timeout=_timeout(httpx)) as client:
		resp = await client.get(_BRAVE, headers=headers, params=params)
		resp.raise_for_status()
		data = resp.json()
	out: list[dict[str, str]] = []
	for item in (data.get("web") or {}).get("results") or []:
		if not isinstance(item, dict):
			continue
		row = await _result_item(
			str(item.get("title") or ""),
			str(item.get("url") or ""),
			str(item.get("description") or ""),
		)
		if not row:
			continue
		out.append(row)
		if len(out) >= count:
			break
	return out


_RESULT_RE = re.compile(
	r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
	re.I | re.S,
)
_SNIPPET_RE = re.compile(
	r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>'
	r'|<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>',
	re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_BING_LI_RE = re.compile(
	r'<li\s+class="b_algo"[^>]*>(.*?)</li>',
	re.I | re.S,
)
_BING_A_RE = re.compile(
	r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
	re.I | re.S,
)
_BING_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.I | re.S)
_LITE_A_RE = re.compile(
	r'<a[^>]+rel="nofollow"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
	re.I | re.S,
)
_MOJEEK_A_RE = re.compile(
	r'<a[^>]+class="[^"]*\btitle-url\b[^"]*"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
	r'|<a[^>]+href="(https?://[^"]+)"[^>]+class="[^"]*\btitle\b[^"]*"[^>]*>(.*?)</a>'
	r'|<a[^>]+class="[^"]*\btitle\b[^"]*"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
	re.I | re.S,
)
_MOJEEK_S_RE = re.compile(
	r'<p[^>]+class="[^"]*\bs\b[^"]*"[^>]*>(.*?)</p>'
	r'|<span[^>]+class="[^"]*\bs\b[^"]*"[^>]*>(.*?)</span>',
	re.I | re.S,
)


def _unwrap_ddg_href(href: str) -> str:
	if "uddg=" in href:
		qs = parse_qs(urlparse(href).query)
		if "uddg" in qs and qs["uddg"]:
			return unquote(qs["uddg"][0])
	return href


async def _ddg_search(
	httpx: Any, query: str, count: int, abort: AbortController
) -> list[dict[str, str]]:
	abort.raise_if_aborted()
	url = _DDG + quote_plus(query)
	deny = is_blocked_url(url)
	if deny:
		raise RuntimeError(f"search URL blocked ({deny})")
	headers = {"User-Agent": _UA}
	async with httpx.AsyncClient(
		timeout=_timeout(httpx),
		follow_redirects=True,
	) as client:
		resp = await client.get(url, headers=headers)
		resp.raise_for_status()
		html = resp.text
	return await _parse_ddg_html(html, count)


async def _ddg_lite_search(
	httpx: Any, query: str, count: int, abort: AbortController
) -> list[dict[str, str]]:
	abort.raise_if_aborted()
	url = _DDG_LITE + quote_plus(query)
	deny = is_blocked_url(url)
	if deny:
		raise RuntimeError(f"search URL blocked ({deny})")
	headers = {"User-Agent": _UA}
	async with httpx.AsyncClient(
		timeout=_timeout(httpx),
		follow_redirects=True,
	) as client:
		resp = await client.get(url, headers=headers)
		resp.raise_for_status()
		html = resp.text

	out: list[dict[str, str]] = []
	for m in _LITE_A_RE.finditer(html):
		href = _unwrap_ddg_href(m.group(1)).strip()
		if "duckduckgo.com" in href:
			continue
		title = unescape(_TAG_RE.sub("", m.group(2))).strip()
		row = await _result_item(title, href, "")
		if not row:
			continue
		out.append(row)
		if len(out) >= count:
			break
	return out


async def _bing_search(
	httpx: Any, query: str, count: int, abort: AbortController
) -> list[dict[str, str]]:
	abort.raise_if_aborted()
	url = _BING + quote_plus(query)
	deny = is_blocked_url(url)
	if deny:
		raise RuntimeError(f"search URL blocked ({deny})")
	headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
	async with httpx.AsyncClient(
		timeout=_timeout(httpx),
		follow_redirects=True,
	) as client:
		resp = await client.get(url, headers=headers)
		resp.raise_for_status()
		html = resp.text

	out: list[dict[str, str]] = []
	for block_m in _BING_LI_RE.finditer(html):
		block = block_m.group(1)
		a = _BING_A_RE.search(block)
		if not a:
			continue
		href = a.group(1).strip()
		title = unescape(_TAG_RE.sub("", a.group(2))).strip()
		snippet = ""
		p = _BING_P_RE.search(block)
		if p:
			snippet = unescape(_TAG_RE.sub("", p.group(1))).strip()
		row = await _result_item(title, href, snippet)
		if not row:
			continue
		out.append(row)
		if len(out) >= count:
			break
	return out


async def _mojeek_search(
	httpx: Any, query: str, count: int, abort: AbortController
) -> list[dict[str, str]]:
	abort.raise_if_aborted()
	url = _MOJEEK + quote_plus(query)
	deny = is_blocked_url(url)
	if deny:
		raise RuntimeError(f"search URL blocked ({deny})")
	headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
	async with httpx.AsyncClient(
		timeout=_timeout(httpx),
		follow_redirects=True,
	) as client:
		resp = await client.get(url, headers=headers)
		resp.raise_for_status()
		html = resp.text
	return await _parse_mojeek_html(html, count)


async def _parse_mojeek_html(html: str, count: int) -> list[dict[str, str]]:
	out: list[dict[str, str]] = []
	# 有结果列表则按其切分；否则扫全页。
	blocks = re.split(r"<li\b", html, flags=re.I)
	if len(blocks) < 2:
		blocks = [html]
	for block in blocks:
		m = _MOJEEK_A_RE.search(block)
		if not m:
			continue
		groups = m.groups()
		href = ""
		title_html = ""
		for i in range(0, len(groups), 2):
			if groups[i]:
				href = groups[i]
				title_html = groups[i + 1] or ""
				break
		if not href:
			continue
		if "mojeek.com" in href:
			continue
		title = unescape(_TAG_RE.sub("", title_html)).strip()
		snippet = ""
		sm = _MOJEEK_S_RE.search(block)
		if sm:
			snippet = unescape(
				_TAG_RE.sub("", sm.group(1) or sm.group(2) or "")
			).strip()
		row = await _result_item(title, href, snippet)
		if not row:
			continue
		out.append(row)
		if len(out) >= count:
			break
	return out


async def _parse_ddg_html(html: str, count: int) -> list[dict[str, str]]:
	out: list[dict[str, str]] = []
	blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*"', html, flags=re.I)
	for block in blocks[1:]:
		m = _RESULT_RE.search(block)
		if not m:
			m2 = re.search(
				r'href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S
			)
			if not m2:
				continue
			href, title_html = m2.group(1), m2.group(2)
		else:
			href, title_html = m.group(1), m.group(2)
		href = _unwrap_ddg_href(href).strip()
		title = unescape(_TAG_RE.sub("", title_html)).strip()
		snip_m = _SNIPPET_RE.search(block)
		snippet = ""
		if snip_m:
			snippet = unescape(
				_TAG_RE.sub("", snip_m.group(1) or snip_m.group(2) or "")
			).strip()
		row = await _result_item(title, href, snippet)
		if not row:
			continue
		out.append(row)
		if len(out) >= count:
			break
	return out
