"""WebFetch — fetch public http(s) URL text (outbound ASK)."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.web_common import focus_text, html_to_text, is_blocked_url
from tools.web_fetch_tool.prompt import DESCRIPTION, WEB_FETCH_TOOL_NAME

_CONNECT_S = 3.0
_READ_S = 12.0
# 下载上限；给模型看的正文更小。
_MAX_BYTES = 200_000
_OUT_CAP = 8_000
_MAX_REDIRECTS = 5
_CACHE_TTL_S = 15 * 60
_CACHE_MAX = 32

# 结构：cache_key -> (expires_at, content)
_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()


def clear_fetch_cache() -> None:
	_cache.clear()


def _normalize_url(url: str) -> str:
	parts = urlsplit(url.strip())
	# 去掉 fragment；保留 query（文档常按 ? 区分）。
	return urlunsplit(
		(parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
	)


def _cache_get(key: str) -> str | None:
	now = time.monotonic()
	item = _cache.get(key)
	if item is None:
		return None
	expires, content = item
	if expires <= now:
		_cache.pop(key, None)
		return None
	_cache.move_to_end(key)
	return content


def _cache_put(key: str, content: str) -> None:
	_cache[key] = (time.monotonic() + _CACHE_TTL_S, content)
	_cache.move_to_end(key)
	while len(_cache) > _CACHE_MAX:
		_cache.popitem(last=False)


class WebFetchTool:
	name = WEB_FETCH_TOOL_NAME

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
				"required": ["url"],
				"properties": {
					"url": {
						"type": "string",
						"description": (
							"http(s) URL to fetch. Private/loopback hosts are denied."
						),
					},
					"prompt": {
						"type": "string",
						"description": (
							"Optional focus question; return matching excerpts only "
							"(saves tokens). Omit for truncated full page text."
						),
					},
				},
				"additionalProperties": False,
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw_in = input or {}
		url = str(raw_in.get("url") or "").strip()
		prompt = str(raw_in.get("prompt") or "").strip()
		if not url:
			return ToolResult(content="url is required", is_error=True)
		deny = await asyncio.to_thread(is_blocked_url, url)
		if deny:
			return ToolResult(content=f"URL blocked ({deny}): {url}", is_error=True)

		cache_key = f"{_normalize_url(url)}\n{prompt}"
		hit = _cache_get(cache_key)
		if hit is not None:
			return ToolResult(content=hit, is_error=False)

		try:
			import httpx
		except ImportError:
			return ToolResult(content="httpx is not installed", is_error=True)

		timeout = httpx.Timeout(_READ_S, connect=_CONNECT_S)
		current = url
		try:
			async with httpx.AsyncClient(
				timeout=timeout,
				follow_redirects=False,
				max_redirects=0,
			) as client:
				resp = None
				for _ in range(_MAX_REDIRECTS + 1):
					abort.raise_if_aborted()
					deny = await asyncio.to_thread(is_blocked_url, current)
					if deny:
						return ToolResult(
							content=f"URL blocked ({deny}): {current}",
							is_error=True,
						)
					async with client.stream("GET", current) as stream_resp:
						if stream_resp.status_code in (301, 302, 303, 307, 308):
							loc = stream_resp.headers.get("location")
							if not loc:
								return ToolResult(
									content=f"redirect without Location: {current}",
									is_error=True,
								)
							current = urljoin(current, loc)
							# 先短暂排空再跟随重定向。
							await stream_resp.aclose()
							continue

						deny = await asyncio.to_thread(is_blocked_url, str(stream_resp.url))
						if deny:
							return ToolResult(
								content=f"URL blocked ({deny}): {stream_resp.url}",
								is_error=True,
							)

						ctype = (
							(stream_resp.headers.get("content-type") or "")
							.split(";")[0]
							.strip()
							.lower()
						)
						raw, truncated_dl = await _read_capped(
							stream_resp, _MAX_BYTES, abort
						)
						encoding = stream_resp.encoding or "utf-8"
						final_url = str(stream_resp.url)
						status = stream_resp.status_code
						resp = (final_url, ctype, status, raw, truncated_dl, encoding)
						break
				else:
					return ToolResult(content="too many redirects", is_error=True)

			assert resp is not None
			final_url, ctype, status, raw, truncated_dl, encoding = resp
			try:
				text = raw.decode(encoding, errors="replace")
			except Exception:
				text = raw.decode("utf-8", errors="replace")

			truncated = truncated_dl
			is_html = (
				"html" in ctype
				or text.lstrip().lower().startswith("<!doctype html")
				or text.lstrip().lower().startswith("<html")
			)
			if is_html:
				# 多提取一些（超过 OUT_CAP），让 focus_text 能挑相关段落。
				extract_budget = max(_OUT_CAP * 4, _OUT_CAP)
				plain = html_to_text(text, max_chars=extract_budget)
				body = focus_text(plain, prompt, max_chars=_OUT_CAP)
			elif ctype.startswith("text/") or ctype in (
				"application/json",
				"application/xml",
				"application/javascript",
				"",
			):
				body = focus_text(text, prompt, max_chars=_OUT_CAP)
			else:
				content = (
					f"URL: {final_url}\nContent-Type: {ctype or 'unknown'}\n"
					f"Non-text body ({len(raw)} bytes); not extracted."
				)
				_cache_put(cache_key, content)
				return ToolResult(content=content, is_error=False)

			if len(body) > _OUT_CAP:
				body = body[:_OUT_CAP]
				truncated = True
			if truncated and "truncated" not in body.lower():
				body = body + "\n… truncated"

			header = (
				f"URL: {final_url}\nContent-Type: {ctype or 'unknown'}\n"
				f"Status: {status}\n\n"
			)
			content = header + body
			_cache_put(cache_key, content)
			return ToolResult(content=content, is_error=False)
		except httpx.TimeoutException:
			return ToolResult(content=f"fetch timed out: {url}", is_error=True)
		except Exception as e:  # noqa: BLE001
			return ToolResult(
				content=f"fetch failed: {type(e).__name__}: {e}"[:500],
				is_error=True,
			)


async def _read_capped(
	stream_resp: Any, max_bytes: int, abort: AbortController
) -> tuple[bytes, bool]:
	buf = bytearray()
	truncated = False
	async for chunk in stream_resp.aiter_bytes():
		abort.raise_if_aborted()
		if not chunk:
			continue
		remain = max_bytes - len(buf)
		if remain <= 0:
			truncated = True
			break
		if len(chunk) > remain:
			buf.extend(chunk[:remain])
			truncated = True
			break
		buf.extend(chunk)
	return bytes(buf), truncated
