"""DeepSeek V4 Flash — 带 SSE 流式的 OpenAI 兼容 HTTP。

环境变量:
  DEEPSEEK_API_KEY   （本客户端必填）
  DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
  DEEPSEEK_MODEL     默认 deepseek-v4-flash
  DEEPSEEK_THINKING  disabled | enabled
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any, AsyncIterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common.errors import (
	NetworkError,
	ProviderError,
	parse_retry_after,
	provider_error_message,
	sanitize_http_body,
)

from engine.abort import AbortController
from model.chunks import ModelChunk
from msgtypes.message import ToolUse

try:
	import httpx
except ImportError:  # pragma: no cover
	httpx = None  # type: ignore

from model._openai_common import (
	consume_sse_line_with_usage as _consume_sse_line_with_usage,
	finish_tool_bufs as _finish_tool_bufs,
	get_shared_httpx_client,
	normalize_messages_for_openai as _normalize_messages_for_openai,
	to_openai_tool as _to_openai_tool,
)


def _env(name: str, default: str | None = None) -> str | None:
	v = os.environ.get(name)
	if v is None or v.strip() == "":
		return default
	return v.strip()


class DeepSeekModelClient:
	def __init__(
		self,
		*,
		api_key: str | None = None,
		base_url: str | None = None,
		model: str | None = None,
		thinking: str | None = None,
		temperature: float | None = None,
	) -> None:
		key = api_key or _env("DEEPSEEK_API_KEY")
		if not key:
			raise RuntimeError("DEEPSEEK_API_KEY is not set")
		self._api_key = key
		self._base_url = (
			base_url
			or _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
			or "https://api.deepseek.com"
		).rstrip("/")
		self._model = (
			model or _env("DEEPSEEK_MODEL", "deepseek-v4-flash") or "deepseek-v4-flash"
		)
		self._thinking = thinking or _env("DEEPSEEK_THINKING", "disabled") or "disabled"
		self._temperature = temperature
		self.last_usage: dict[str, Any] | None = None  # 最近一次流式请求的 usage（含缓存命中）
		self.context_limit: int | None = None  # 上下文窗口(token);由 build_default_engine 注入保守默认(G67)
		self._session_id: str = ""
		self._usage_recorded_this_stream = False

	def set_session_id(self, session_id: str | None) -> None:
		"""注入会话 id（server/session_pool._inject_session_ids），供用量账本归因。"""
		self._session_id = (session_id or "").strip()

	def _record_usage_safe(self, usage: dict[str, Any] | None) -> None:
		"""G58: DeepSeek 客户端路径补用量账本(镜像 openai_compat)，防账本黑洞。"""
		if not usage:
			return
		try:
			from usage.ledger import record_from_openai_usage

			sid = self._session_id
			if not sid:
				try:
					from engine.workspace_context import get_workspace_context

					ctx = get_workspace_context()
					if ctx is not None and ctx.session_id:
						sid = str(ctx.session_id).strip()
				except Exception:
					sid = ""
			# B0.5：流内单结算 + 请求归因（dsh S2/S4）。meta 由 stream() 在每次
			# 逻辑调用开始时注入；非 stream 路径无 meta → 不写 request_id。
			record_from_openai_usage(
				provider="deepseek",
				model=self._model,
				api_key=self._api_key,
				usage=usage,
				session_id=sid,
				request_id=str(getattr(self, "_meta_request_id", "") or ""),
				attempt=int(getattr(self, "_meta_attempt", 1) or 1),
				kind=str(getattr(self, "_meta_kind", "turn") or "turn"),
			)
		except Exception:  # noqa: BLE001
			logging.getLogger(__name__).debug(
				"deepseek usage ledger write failed", exc_info=True
			)

	def _headers(self) -> dict[str, str]:
		return {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
			"Accept": "text/event-stream",
		}

	def _build_body(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		*,
		stream: bool,
	) -> dict[str, Any]:
		body: dict[str, Any] = {
			"model": self._model,
			"messages": _normalize_messages_for_openai(messages),
			"stream": stream,
		}
		openai_tools = [_to_openai_tool(t) for t in tools]
		if openai_tools:
			body["tools"] = openai_tools
			body["tool_choice"] = "auto"
		if self._thinking in ("disabled", "enabled"):
			body["thinking"] = {"type": self._thinking}
		if self._temperature is not None:
			body["temperature"] = self._temperature
		# 流式 usage，供热路径记录 H_obs / P1 校准
		if stream:
			body["stream_options"] = {"include_usage": True}
		return body

	async def stream(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		# 调用方（query_loop / C2 摘要旁路）会在调用前注入 B0.5 记账 meta：
		# model._meta_request_id / _meta_attempt / _meta_kind —— 本处不取参，
		# 保持 stream() 接口对所有模型实现（含测试 fake）一致。
		abort.raise_if_aborted()
		if httpx is not None:
			async for chunk in self._stream_httpx(messages, tools, abort):
				yield chunk
			return
		async for chunk in self._stream_stdlib(messages, tools, abort):
			yield chunk

	async def _stream_httpx(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		body = self._build_body(messages, tools, stream=True)
		url = f"{self._base_url}/chat/completions"
		tool_bufs: dict[int, dict[str, str]] = {}
		self.last_usage = None
		self._usage_recorded_this_stream = False
		last_usage: dict[str, Any] | None = None
		client = get_shared_httpx_client(120.0)
		async with client.stream(
			"POST", url, headers=self._headers(), json=body, timeout=120.0
		) as resp:
			if resp.status_code >= 400:
				err = await resp.aread()
				raw = err.decode("utf-8", errors="replace")
				raise ProviderError(
					provider_error_message(
						resp.status_code,
						sanitize_http_body(raw),
					),
					status_code=resp.status_code,
					retry_after_ms=parse_retry_after(resp.headers.get("Retry-After")),
				)
			async for line in resp.aiter_lines():
				abort.raise_if_aborted()
				u, chunks = _consume_sse_line_with_usage(line, tool_bufs)
				if u:
					last_usage = u
					self.last_usage = u
					# 用量尾帧到达即记账(不等流结束):中断也不丢 usage(G58)
					if not self._usage_recorded_this_stream:
						self._usage_recorded_this_stream = True
						self._record_usage_safe(u)
				for chunk in chunks:
					yield chunk
		for chunk in _finish_tool_bufs(tool_bufs):
			abort.raise_if_aborted()
			yield chunk
		self.last_usage = last_usage
		if last_usage and not self._usage_recorded_this_stream:
			self._record_usage_safe(last_usage)

	async def _stream_stdlib(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		"""通过 worker 线程中的 urllib 处理 SSE → async 队列（真正增量 yield）。"""
		body = self._build_body(messages, tools, stream=True)
		url = f"{self._base_url}/chat/completions"
		data = json.dumps(body).encode("utf-8")
		loop = asyncio.get_running_loop()
		queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
		self.last_usage = None
		self._usage_recorded_this_stream = False

		def worker() -> None:
			tool_bufs: dict[int, dict[str, str]] = {}
			last_usage: dict[str, Any] | None = None
			try:
				req = Request(url, data=data, headers=self._headers(), method="POST")
				with urlopen(req, timeout=120) as resp:
					while True:
						raw = resp.readline()
						if not raw:
							break
						line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
						u, chunks = _consume_sse_line_with_usage(line, tool_bufs)
						if u:
							last_usage = u
						for chunk in chunks:
							loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
				for chunk in _finish_tool_bufs(tool_bufs):
					loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
				if last_usage:
					self.last_usage = last_usage
				loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
			except HTTPError as e:
				detail = sanitize_http_body(e.read().decode("utf-8", errors="replace"))
				loop.call_soon_threadsafe(
					queue.put_nowait,
					("err", ProviderError(
						provider_error_message(e.code, detail),
						status_code=e.code,
						retry_after_ms=parse_retry_after(e.headers.get("Retry-After")),
					)),
				)
			except URLError as e:
				loop.call_soon_threadsafe(
					queue.put_nowait,
					("err", NetworkError(str(e))),
				)
			except Exception as e:  # noqa: BLE001
				loop.call_soon_threadsafe(queue.put_nowait, ("err", e))

		threading.Thread(target=worker, name="deepseek-sse", daemon=True).start()

		while True:
			abort.raise_if_aborted()
			kind, payload = await queue.get()
			if kind == "done":
				if self.last_usage and not self._usage_recorded_this_stream:
					self._record_usage_safe(self.last_usage)
				return
			if kind == "err":
				raise payload
			yield payload  # type: ignore[misc]

	async def _complete_non_stream(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
	) -> tuple[str, list[ToolUse]]:
		# 非流式不是 engine 的流式逻辑调用：清掉可能残留的 stream meta，
		# 避免上一条流式请求的 request_id 错误贴到本行（B0.5 归因洁净）。
		self._meta_request_id = ""
		body = self._build_body(messages, tools, stream=False)
		url = f"{self._base_url}/chat/completions"
		data = json.dumps(body).encode("utf-8")
		headers = {**self._headers(), "Accept": "application/json"}
		req = Request(url, data=data, headers=headers, method="POST")
		try:
			with urlopen(req, timeout=120) as resp:
				raw = resp.read().decode("utf-8")
		except HTTPError as e:
			detail = e.read().decode("utf-8", errors="replace")
			raise ProviderError(
				detail,
				status_code=e.code,
				retry_after_ms=parse_retry_after(e.headers.get("Retry-After")),
			) from e
		except URLError as e:
			raise NetworkError(str(e)) from e

		parsed = json.loads(raw)
		usage = parsed.get("usage")
		self.last_usage = usage if isinstance(usage, dict) else None
		self._record_usage_safe(self.last_usage)  # G58: 非流式同样入账本
		msg = ((parsed.get("choices") or [{}])[0].get("message")) or {}
		text = msg.get("content") or ""
		tool_uses: list[ToolUse] = []
		for tc in msg.get("tool_calls") or []:
			fn = tc.get("function") or {}
			try:
				args = json.loads(fn.get("arguments") or "{}")
			except json.JSONDecodeError:
				args = {"_raw": fn.get("arguments")}
			tool_uses.append(
				ToolUse(
					id=tc.get("id") or f"call_{fn.get('name')}",
					name=fn.get("name") or "unknown",
					input=args if isinstance(args, dict) else {"value": args},
				)
			)
		return text, tool_uses


def _extract_sse_usage(line: str) -> dict[str, Any] | None:
	"""从 SSE 行取 usage（DeepSeek 流式带 include_usage 时返回）。

	薄封装：共享解析器 consume_sse_line_with_usage 返回 (usage, chunks)，这里只取 usage。
	"""
	return _consume_sse_line_with_usage(line, {})[0]


def _consume_sse_line(
	line: str, tool_bufs: dict[int, dict[str, str]]
) -> list[ModelChunk]:
	"""兼容旧签名：只返回 chunks。"""
	return _consume_sse_line_with_usage(line, tool_bufs)[1]
