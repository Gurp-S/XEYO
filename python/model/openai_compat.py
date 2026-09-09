"""通用 OpenAI 兼容 Chat Completions 客户端（DeepSeek / OpenAI 等）。"""

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


def parse_sse_usage(line: str) -> dict[str, Any] | None:
	"""从 SSE 行取 usage（与 deepseek 共用 consume_sse_line_with_usage，避免重复解析）。"""
	return _consume_sse_line_with_usage(line, {})[0]


def _positive_int(value: Any) -> int | None:
	try:
		n = int(value)
	except (TypeError, ValueError):
		return None
	return n if n > 0 else None


def context_tokens_from_usage(usage: dict[str, Any] | None) -> int | None:
	"""读取本次请求真实输入 token 数，不用字符数伪造。"""
	if not isinstance(usage, dict):
		return None
	for key in ("prompt_tokens", "input_tokens", "context_tokens"):
		value = _positive_int(usage.get(key))
		if value is not None:
			return value
	return None


def _context_limit_from_usage_fields(usage: dict[str, Any] | None) -> int | None:
	"""只从 usage 字段取供应商返回的上下文窗口；不读 env / 破表。"""
	if isinstance(usage, dict):
		for key in ("context_limit", "context_window", "context_length", "max_context_tokens"):
			value = _positive_int(usage.get(key))
			if value is not None:
				return value
	return None


def context_limit_from_usage(
	usage: dict[str, Any] | None,
	model: str | None = None,
) -> int | None:
	"""只接受供应商明确返回 / 运行配置显式提供的 context 上限。

	优先级：usage 字段 → env XEYO_CONTEXT_LIMIT_TOKENS。均未提供时返回 None
	（前端显示「暂无数据」，绝不按模型名伪造窗口）。
	"""
	del model  # 废弃：绝不按模型名猜窗口
	value = _context_limit_from_usage_fields(usage)
	if value is not None:
		return value
	env_limit = _positive_int(os.environ.get("XEYO_CONTEXT_LIMIT_TOKENS"))
	if env_limit is not None:
		return env_limit
	return None


# 供应商视觉输入的最大边长；超过时发送前等比缩放（见 media_store）。
_DEFAULT_IMAGE_MAX_DIMENSION = 8192
_OPENAI_IMAGE_MAX_DIMENSION = 6000


def image_max_dimension(
	provider: str,
	model: str,
	*,
	image_count: int = 1,
) -> int:
	"""返回当前供应商/模型允许的单图最大边长。

	- DeepSeek：默认 8192；图多时收紧（>8 张降到 4096），可
	  XEYO_MAX_IMAGE_DIMENSION_DEEPSEEK 覆盖（覆盖后再按图数收紧）。
	- OpenAI：6000（与 gpt-4o 系列视觉输入上限对齐）。
	- 未知供应商：协议安全上限 8192。
	"""
	prov = (provider or "").strip().lower()
	if prov == "openai":
		return _OPENAI_IMAGE_MAX_DIMENSION
	base = _OPENAI_IMAGE_MAX_DIMENSION
	if prov == "deepseek":
		raw = os.environ.get("XEYO_MAX_IMAGE_DIMENSION_DEEPSEEK", "").strip()
		base = _positive_int(raw) if raw else _DEFAULT_IMAGE_MAX_DIMENSION
		base = base or _DEFAULT_IMAGE_MAX_DIMENSION
		if image_count is not None and int(image_count or 0) > 8:
			base = min(base, 4096)
		return max(256, base)
	return _DEFAULT_IMAGE_MAX_DIMENSION


class OpenAICompatClient:
	"""对任意 OpenAI 兼容 base_url 流式调用 chat.completions。"""

	def __init__(
		self,
		*,
		api_key: str,
		base_url: str,
		model: str,
		provider: str = "openai",
		thinking: str = "disabled",
		reasoning_effort: str = "",
		temperature: float | None = None,
		max_tokens: int | None = None,
		session_id: str = "",
	) -> None:
		if not api_key.strip():
			raise RuntimeError("API key is required")
		self._api_key = api_key.strip()
		self._base_url = base_url.rstrip("/")
		self._model = model
		self._provider = provider.lower()
		self._thinking = (thinking or "disabled").strip().lower()
		self._reasoning_effort = (reasoning_effort or "").strip().lower()
		self._temperature = temperature
		# 最大输出 tokens（可选）：None = 不限制，不发送该字段。
		self._max_tokens = _positive_int(max_tokens)
		self._session_id = (session_id or "").strip()
		self.last_usage: dict[str, Any] | None = None  # 最近一次流式请求的 usage（含缓存命中）
		self.last_context_tokens: int | None = None
		# 上下文窗口优先级：厂商 /models 元数据(cfg) → env。绝不按模型名猜窗口。
		self.context_limit: int | None = _positive_int(
			os.environ.get("XEYO_CONTEXT_LIMIT_TOKENS")
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
		# DeepSeek 官方 thinking / reasoning_effort；OpenAI 不传
		if self._provider == "deepseek":
			kind = self._thinking if self._thinking in ("enabled", "disabled") else "disabled"
			body["thinking"] = {"type": kind}
			if kind == "enabled" and self._reasoning_effort in ("low", "high", "max"):
				body["reasoning_effort"] = self._reasoning_effort
		# 通用 OpenAI 兼容模型：直接透传用户选的思考等级
		elif self._reasoning_effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
			body["reasoning_effort"] = self._reasoning_effort
		# 官方流式 usage，供本机记账；厂商看板拿不到历史用量时用它补
		if self._temperature is not None:
			body["temperature"] = self._temperature
		# 最大输出 tokens（可选）：None 则不发送，保持默认。
		if self._max_tokens is not None:
			body["max_tokens"] = self._max_tokens
		if stream:
			body["stream_options"] = {"include_usage": True}
		return body

	def _record_usage_safe(self, usage: dict[str, Any] | None) -> None:
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
			record_from_openai_usage(
				provider=self._provider,
				model=self._model,
				api_key=self._api_key,
				usage=usage,
				session_id=sid,
				base_url=self._base_url,
			)
		except Exception:  # noqa: BLE001
			logging.getLogger(__name__).debug(
				"usage ledger write failed", exc_info=True
			)

	async def stream(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		abort.raise_if_aborted()
		self.last_usage = None
		self.last_context_tokens = None
		self._usage_recorded_this_stream = False
		body = self._build_body(messages, tools, stream=True)
		url = f"{self._base_url}/chat/completions"

		if httpx is not None:
			tool_bufs: dict[int, dict[str, str]] = {}
			last_usage: dict[str, Any] | None = None
			client = get_shared_httpx_client(180.0)
			async with client.stream(
				"POST", url, headers=self._headers(), json=body, timeout=180.0
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
						# smoke-test #4：usage 尾帧到达即记账/更新（不等流结束),
						# 中断(stop/断流)也不丢用量与缓存命中统计。
						self.last_usage = u
						self.last_context_tokens = context_tokens_from_usage(u)
						self.context_limit = (
							_context_limit_from_usage_fields(u)
							or self.context_limit
						)
						if not self._usage_recorded_this_stream:
							self._usage_recorded_this_stream = True
							self._record_usage_safe(u)
					for chunk in chunks:
						yield chunk
			for chunk in _finish_tool_bufs(tool_bufs):
				abort.raise_if_aborted()
				yield chunk
			self.last_usage = last_usage
			self.last_context_tokens = context_tokens_from_usage(last_usage)
			self.context_limit = _context_limit_from_usage_fields(last_usage) or self.context_limit
			if last_usage and not self._usage_recorded_this_stream:
				self._record_usage_safe(last_usage)
			return

		# stdlib 回退
		data = json.dumps(body).encode("utf-8")
		loop = asyncio.get_running_loop()
		queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

		def worker() -> None:
			tool_bufs2: dict[int, dict[str, str]] = {}
			last_usage: dict[str, Any] | None = None
			try:
				req = Request(url, data=data, headers=self._headers(), method="POST")
				with urlopen(req, timeout=180) as resp:
					while True:
						raw = resp.readline()
						if not raw:
							break
						line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
						u, chunks = _consume_sse_line_with_usage(line, tool_bufs2)
						if u:
							last_usage = u
						for chunk in chunks:
							loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
				for chunk in _finish_tool_bufs(tool_bufs2):
					loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
				if last_usage:
					loop.call_soon_threadsafe(queue.put_nowait, ("usage", last_usage))
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

		threading.Thread(target=worker, name="openai-sse", daemon=True).start()
		while True:
			abort.raise_if_aborted()
			kind, payload = await queue.get()
			if kind == "done":
				return
			if kind == "usage":
				self.last_usage = payload if isinstance(payload, dict) else None
				self.last_context_tokens = context_tokens_from_usage(self.last_usage)
				self.context_limit = _context_limit_from_usage_fields(self.last_usage) or self.context_limit
				self._record_usage_safe(self.last_usage)
				continue
			if kind == "err":
				raise payload
			yield payload  # type: ignore[misc]


PROVIDER_PRESETS: dict[str, dict[str, str]] = {
	"deepseek": {
		# OpenAI SDK 风格：base + /chat/completions
		"base_url": "https://api.deepseek.com/v1",
		"label": "DeepSeek",
	},
	"openai": {
		"base_url": "https://api.openai.com/v1",
		"label": "OpenAI",
	},
	# 本地推理（llama.cpp 等）；服务端需 XEYO_ALLOW_LOCAL_MODEL=1 才放行。
	"local": {
		"base_url": "http://localhost:8080/v1",
		"label": "本地模型",
	},
	# HTTP 全栈测试（Playwright 真浏览器+真后端）用的确定性假模型；
	# 服务端需 XEYO_ALLOW_FAKE_MODEL=1 才放行，生产恒关闭。
	"fake": {
		"base_url": "",
		"label": "Fake（测试）",
	},
}
