"""Anthropic Messages API 原生客户端（Claude 一级公民）。

为什么需要原生适配器（而不是走 OpenAI 兼容层）：
  Claude 的思考态（thinking）以 **content block + signature** 形式存在，签名是
  厂商不透明字节，回传时须逐块原样带回；OpenAI 报文没有承载签名的字段，
  兼容层必然把签名丢弃，下一轮即被厂商拒收。四家做 Claude 的实现
  （Roo/Cline/gptme/Helix）无一走兼容层，全部落原生消息格式。故本模块直接
  讲 Messages API。

与 OpenAI 路径的协议差异（本模块存在的全部理由）：
  1. ``system`` 不在 messages 里，提到顶层 ``system`` 字段。
  2. assistant 的工具调用是 content block (``tool_use``)，不是 ``tool_calls``。
  3. ``tool_result`` 是 **user 消息里的 block**，且必须与它响应的 ``tool_use``
     **在同一条消息序列内紧接着出现**；OpenAI 的独立 ``role=tool`` 行要合并。
  4. messages 必须严格 user/assistant 交替，相邻同角色消息须合并。
  5. thinking block 带 ``signature``，须逐块原样回传。
  6. ``thinking:{type:"enabled"}`` 在 Claude 4.7+ 返回 400，须用 ``adaptive``
     （配合 ``output_config.effort``）。

环境变量:
  ANTHROPIC_API_KEY     （本客户端必填）
  ANTHROPIC_BASE_URL     默认 https://api.anthropic.com
  ANTHROPIC_MODEL        默认 claude-sonnet-4-5
  ANTHROPIC_THINKING     off | adaptive（默认 off）
  ANTHROPIC_EFFORT       low | medium | high（adaptive 时的强度，可选）
  ANTHROPIC_MAX_TOKENS   默认 8192（Messages API 必填字段）
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

from model._openai_common import get_shared_httpx_client

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192


def _env(name: str, default: str | None = None) -> str | None:
	v = os.environ.get(name)
	if v is None or v.strip() == "":
		return default
	return v.strip()


def _positive_int(value: Any) -> int | None:
	try:
		n = int(value)
	except (TypeError, ValueError):
		return None
	return n if n > 0 else None


# ---------------------------------------------------------------------------
# 请求体构造：内部消息 → Messages API
# ---------------------------------------------------------------------------


def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
	"""把内部消息拆成（顶层 system 文本, 其余对话消息）。

	Anthropic 的 system 是请求顶层字段而非消息；多条 system 按序拼接。
	"""
	system_parts: list[str] = []
	rest: list[dict[str, Any]] = []
	for m in messages:
		if m.get("role") == "system":
			content = m.get("content")
			if isinstance(content, str):
				if content:
					system_parts.append(content)
			elif isinstance(content, list):
				for block in content:
					if isinstance(block, dict) and block.get("type") == "text":
						text = str(block.get("text") or "")
						if text:
							system_parts.append(text)
			continue
		rest.append(m)
	return "\n\n".join(system_parts), rest


def _data_url_to_image_block(url: str) -> dict[str, Any] | None:
	"""``data:image/png;base64,XXXX`` → Anthropic image block；非 data URL 返回 None。"""
	data, _, media_type = _split_data_url(url)
	if not data:
		return None
	return {
		"type": "image",
		"source": {"type": "base64", "media_type": media_type, "data": data},
	}


def _tool_result_content(block: dict[str, Any], images: list[str] | None = None) -> dict[str, Any]:
	"""内部 tool_result block → Anthropic tool_result block。

	Anthropic 的 tool_result.content 既可是字符串，也可是 block 数组
	（承载图片）。无图时发字符串，保持报文最小。

	``images`` 是**同一条消息里跟在 tool_result 之后的 image_url block**
	（内部表示为兄弟 block，见 ``msgtypes.message.tool_result_message``）——
	Anthropic 没有并列图片槽，须折进 tool_result.content 里。
	"""
	inner: list[dict[str, Any]] = []
	text = str(block.get("content") or "")
	if text:
		inner.append({"type": "text", "text": text})
	for url in images or []:
		img = _data_url_to_image_block(url)
		if img is not None:
			inner.append(img)
	out: dict[str, Any] = {
		"type": "tool_result",
		"tool_use_id": str(block.get("tool_use_id") or ""),
	}
	out["content"] = inner if len(inner) > 1 else (text or "")
	if block.get("is_error"):
		out["is_error"] = True
	return out


def _split_data_url(url: str) -> tuple[str, str, str]:
	"""``data:image/png;base64,XXXX`` → (base64, 前缀, media_type)。

	非 data: URL（含 xeyo-media:// 与 http(s)）返回空 data，由调用方跳过
	或交由 media_store 物化后重试——本模块不做图片物化，避免与
	``normalize_messages_for_openai`` 的双份实现漂移。
	"""
	if not url.startswith("data:"):
		return "", "", ""
	head, _, body = url.partition(",")
	if ";base64" not in head:
		return "", "", ""
	media = head[len("data:") :].split(";")[0].strip() or "image/png"
	return body, head, media


def _blocks_to_anthropic(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""内部 content block 数组 → Anthropic content block 数组（单条消息内）。"""
	out: list[dict[str, Any]] = []
	# 紧跟在 tool_result 之后的 image_url block 折进该 tool_result 内：
	# Anthropic 一个 tool_result 自带 content 数组，没有并列图片槽。
	pending_tool_result_idx: int | None = None
	pending_images: list[str] = []

	def _flush_pending() -> None:
		nonlocal pending_tool_result_idx, pending_images
		if pending_tool_result_idx is not None and pending_images:
			out[pending_tool_result_idx] = _tool_result_content(
				out[pending_tool_result_idx], pending_images
			)
		pending_tool_result_idx = None
		pending_images = []

	for block in content:
		if not isinstance(block, dict):
			continue
		btype = block.get("type")
		if btype == "image_url":
			image_url = block.get("image_url")
			url = ""
			if isinstance(image_url, dict):
				url = str(image_url.get("url") or "")
			if pending_tool_result_idx is not None:
				pending_images.append(url)
				continue
			img = _data_url_to_image_block(url)
			if img is not None:
				out.append(img)
			continue
		_flush_pending()
		if btype == "text":
			text = str(block.get("text") or "")
			if text:
				out.append({"type": "text", "text": text})
		elif btype == "thinking":
			# 思考态回放：text + signature 逐块原样带回。签名缺失时不发该块
			# （厂商对无签名 thinking 的接受度不确定，宁可不带也不发坏块）。
			sig = str(block.get("signature") or "")
			text = str(block.get("text") or "")
			if text and sig:
				out.append({"type": "thinking", "thinking": text, "signature": sig})
		elif btype == "reasoning":
			# 跨厂商转码：OpenAI 系只有明文思考、无签名——Anthropic 无法承载，
			# 静默丢弃该块（不伪造签名，不编造内容）。
			continue
		elif btype == "redacted_thinking":
			data = str(block.get("data") or "")
			if data:
				out.append({"type": "redacted_thinking", "data": data})
		elif btype == "tool_use":
			out.append(
				{
					"type": "tool_use",
					"id": str(block.get("id") or "toolu_unknown"),
					"name": str(block.get("name") or "unknown"),
					"input": block.get("input") or {},
				}
			)
		elif btype == "tool_result":
			out.append(_tool_result_content(block))
			pending_tool_result_idx = len(out) - 1
	_flush_pending()
	return out


def _coalesce(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""合并相邻同角色消息（Anthropic 要求严格交替）。

	工具轮会把「assistant(tool_use)」与随后的「user(tool_result)」天然错开；
	真正需要合并的是：连续多个 tool_result 行（内部每个工具一条 role=tool）→
	合成一条 user 消息的多个 tool_result block。
	"""
	out: list[dict[str, Any]] = []
	for m in messages:
		role = m.get("role")
		blocks = m.get("content") or []
		if not isinstance(blocks, list) or not blocks:
			continue
		if out and out[-1]["role"] == role:
			out[-1]["content"].extend(blocks)
		else:
			out.append({"role": role, "content": list(blocks)})
	return out


def normalize_messages_for_anthropic(
	messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
	"""内部消息 → (system 文本, Anthropic messages 数组)。

	转码规则与 OpenAI 路径的差异（见模块 docstring）全部收敛在此函数，
	是唯一的序列化入口。
	"""
	system_text, rest = _split_system(messages)
	norm: list[dict[str, Any]] = []
	for m in rest:
		role = m.get("role")
		content = m.get("content")
		if role == "user":
			if isinstance(content, str):
				if content:
					norm.append({"role": "user", "content": [{"type": "text", "text": content}]})
			elif isinstance(content, list):
				blocks = _blocks_to_anthropic(content)
				if blocks:
					norm.append({"role": "user", "content": blocks})
			continue
		if role == "assistant":
			if isinstance(content, str):
				if content:
					norm.append(
						{"role": "assistant", "content": [{"type": "text", "text": content}]}
					)
			elif isinstance(content, list):
				blocks = _blocks_to_anthropic(content)
				if blocks:
					norm.append({"role": "assistant", "content": blocks})
			continue
		if role == "tool":
			# 内部 role=tool 行 → user 消息里的 tool_result block。
			if isinstance(content, list):
				blocks = _blocks_to_anthropic(content)
			else:
				blocks = [
					{
						"type": "tool_result",
						"tool_use_id": str(m.get("tool_call_id") or ""),
						"content": str(content or ""),
					}
				]
			if blocks:
				norm.append({"role": "user", "content": blocks})
			continue
	norm = _coalesce(norm)
	return system_text, norm


def to_anthropic_tool(schema: dict[str, Any]) -> dict[str, Any]:
	"""工具 schema → Anthropic tool 对象。

	内部 schema 已是 ``{name, description, input_schema}``（与 Anthropic 同构），
	仅补缺失字段；已是 Anthropic 形态的原样返回。不在此滤掉任何键——
	``cache_control`` 之类的厂商标注需透传。
	"""
	if "input_schema" in schema and "name" in schema:
		out = dict(schema)
		out.setdefault("description", "")
		out.setdefault("input_schema", {"type": "object", "properties": {}})
		return out
	return {
		"name": str(schema.get("name") or "unknown"),
		"description": str(schema.get("description") or ""),
		"input_schema": schema.get("input_schema")
		or schema.get("parameters")
		or {"type": "object", "properties": {}},
	}


# ---------------------------------------------------------------------------
# SSE 解析
# ---------------------------------------------------------------------------


def _consume_sse_event(
	event_name: str,
	payload: str,
	state: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[ModelChunk]]:
	"""解析一条 Anthropic SSE 事件 → (usage, chunks)。

	state 跨事件累积：``tool_bufs``（每 block index 一个 json 缓冲）、
	``thinking_sigs``（block index → signature，content_block_stop 时落定）。
	"""
	if not payload:
		return None, []
	try:
		event = json.loads(payload)
	except json.JSONDecodeError:
		return None, []
	etype = event.get("type") or event_name
	out: list[ModelChunk] = []

	if etype == "message_start":
		usage = (event.get("message") or {}).get("usage")
		if isinstance(usage, dict):
			# 输入侧只在 message_start 出现；message_delta 只有 output_tokens，
			# 在此留档，供 delta 合并成一条完整 usage（否则面板输入恒为 0）。
			state["input_usage"] = usage
			return usage, []
		return None, []

	if etype == "content_block_start":
		idx = int(event.get("index") or 0)
		block = event.get("content_block") or {}
		btype = block.get("type")
		if btype == "tool_use":
			tool_bufs = state.setdefault("tool_bufs", {})
			tool_bufs[idx] = {
				"id": str(block.get("id") or ""),
				"name": str(block.get("name") or ""),
				"json": "",
				# input 在 content_block_start 里偶发直接给全量（空对象即流式）
				"prefilled": bool(block.get("input")),
				"input": block.get("input") or {},
			}
		elif btype == "thinking":
			# 思考态以明文增量下发；签名在 content_block_delta(signature_delta)
			# 或 content_block_stop 里落定。此处留一个槽。
			state.setdefault("thinking_bufs", {})[idx] = {"text": "", "signature": ""}
		return None, []

	if etype == "content_block_delta":
		idx = int(event.get("index") or 0)
		delta = event.get("delta") or {}
		dtype = delta.get("type")
		if dtype == "text_delta":
			text = delta.get("text") or ""
			if text:
				out.append(ModelChunk(kind="text_delta", text=str(text)))
		elif dtype == "thinking_delta":
			text = delta.get("thinking") or ""
			buf = state.setdefault("thinking_bufs", {}).setdefault(
				idx, {"text": "", "signature": ""}
			)
			buf["text"] += str(text)
			# 思考态既要回传又要展示：reasoning_delta 供 GUI 实时渲染
			if text:
				out.append(ModelChunk(kind="reasoning_delta", text=str(text)))
		elif dtype == "signature_delta":
			sig = delta.get("signature") or ""
			buf = state.setdefault("thinking_bufs", {}).setdefault(
				idx, {"text": "", "signature": ""}
			)
			buf["signature"] += str(sig)
		elif dtype == "input_json_delta":
			partial = delta.get("partial_json") or ""
			buf = state.setdefault("tool_bufs", {}).get(idx)
			if buf is not None:
				buf["json"] = str(buf.get("json") or "") + str(partial)
		return None, out

	if etype == "content_block_stop":
		idx = int(event.get("index") or 0)
		buf = state.setdefault("tool_bufs", {}).get(idx)
		if buf is not None:
			chunk = _finalize_tool_block(buf)
			if chunk is not None:
				out.append(chunk)
		return None, out

	if etype == "message_delta":
		usage = event.get("usage")
		merged = usage if isinstance(usage, dict) else None
		if merged is not None and state.get("input_usage"):
			# message_delta.usage 只有 output_tokens，输入侧在 message_start；
			# 合并成一条完整 usage 供账本结算（否则面板输入恒为 0）。
			merged = {**state["input_usage"], **merged}
		return merged, out

	if etype == "error":
		err = event.get("error") or {}
		msg = str(err.get("message") or "anthropic stream error")
		raise ProviderError(msg)

	return None, out


def _finalize_tool_block(buf: dict[str, Any]) -> ModelChunk | None:
	raw = str(buf.get("json") or "")
	if raw.strip():
		try:
			args = json.loads(raw)
		except json.JSONDecodeError:
			args = {"_raw": raw}
	else:
		args = buf.get("input") if buf.get("prefilled") else {}
	return ModelChunk(
		kind="tool_use",
		tool_use=ToolUse(
			id=str(buf.get("id") or "") or f"toolu_{buf.get('name')}",
			name=str(buf.get("name") or "unknown"),
			input=args if isinstance(args, dict) else {"value": args},
		),
	)


def _finish_pending_tool_bufs(state: dict[str, Any]) -> list[ModelChunk]:
	"""流结束时收尾尚未闭块的 tool_use（协议异常时的兜底）。"""
	out: list[ModelChunk] = []
	for idx, buf in (state.get("tool_bufs") or {}).items():
		if buf.get("_emitted"):
			continue
		buf["_emitted"] = True
		chunk = _finalize_tool_block(buf)
		if chunk is not None:
			out.append(chunk)
	return out


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class AnthropicModelClient:
	"""Anthropic Messages API 客户端，实现 ModelClient 的 ``stream()`` 契约。"""

	def __init__(
		self,
		*,
		api_key: str | None = None,
		base_url: str | None = None,
		model: str | None = None,
		thinking: str | None = None,
		reasoning_effort: str | None = None,
		max_tokens: int | None = None,
		temperature: float | None = None,
		session_id: str = "",
	) -> None:
		key = (api_key or _env("ANTHROPIC_API_KEY") or "").strip()
		if not key:
			raise RuntimeError("ANTHROPIC_API_KEY is not set")
		self._api_key = key
		self._base_url = (
			base_url
			or _env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
			or "https://api.anthropic.com"
		).rstrip("/")
		self._model = (
			model or _env("ANTHROPIC_MODEL", "claude-sonnet-4-5") or "claude-sonnet-4-5"
		)
		# 归一化思考档：disabled/enabled 是 OpenAI 系的词，Anthropic 用 adaptive。
		raw_thinking = (thinking or _env("ANTHROPIC_THINKING", "off") or "off").lower()
		self._thinking = "adaptive" if raw_thinking in ("adaptive", "enabled", "on") else "off"
		self._reasoning_effort = (
			reasoning_effort or _env("ANTHROPIC_EFFORT", "") or ""
		).strip().lower()
		self._max_tokens = _positive_int(max_tokens) or _positive_int(
			_env("ANTHROPIC_MAX_TOKENS")
		) or DEFAULT_MAX_TOKENS
		self._temperature = temperature
		self._session_id = (session_id or "").strip()
		self.provider = "anthropic"
		self.last_usage: dict[str, Any] | None = None
		self.last_context_tokens: int | None = None
		self.context_limit: int | None = _positive_int(
			os.environ.get("XEYO_CONTEXT_LIMIT_TOKENS")
		)
		# 用户登记的窗口 = 权威口径，后端压缩上限以它为分母（与 OpenAI 兼容层同款
		# 接口；厂商响应里若带窗口元数据，不得事后覆写登记值）。
		self.context_limit_declared: bool = self.context_limit is not None
		self._usage_recorded_this_stream = False

	def declare_context_limit(self, context_limit: int | None) -> None:
		"""登记用户/配置显式指定的上下文窗口（token）并钉住它。"""
		limit = _positive_int(context_limit)
		if limit is None:
			return
		self.context_limit = limit
		self.context_limit_declared = True

	def set_session_id(self, session_id: str | None) -> None:
		"""注入会话 id，供用量账本归因（与 DeepSeek 客户端同款接口）。"""
		self._session_id = (session_id or "").strip()

	def _headers(self) -> dict[str, str]:
		return {
			"x-api-key": self._api_key,
			"anthropic-version": ANTHROPIC_VERSION,
			"Content-Type": "application/json",
			"Accept": "text/event-stream",
		}

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
				provider="anthropic",
				model=self._model,
				api_key=self._api_key,
				usage=_usage_to_openai_shape(usage),
				session_id=sid,
				request_id=str(getattr(self, "_meta_request_id", "") or ""),
				attempt=int(getattr(self, "_meta_attempt", 1) or 1),
				kind=str(getattr(self, "_meta_kind", "turn") or "turn"),
			)
		except Exception:  # noqa: BLE001
			logging.getLogger(__name__).debug(
				"anthropic usage ledger write failed", exc_info=True
			)

	def _build_body(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		*,
		stream: bool,
	) -> dict[str, Any]:
		system_text, norm = normalize_messages_for_anthropic(messages)
		body: dict[str, Any] = {
			"model": self._model,
			"messages": norm,
			"max_tokens": self._max_tokens,
		}
		if system_text:
			body["system"] = system_text
		if self._thinking == "adaptive":
			body["thinking"] = {"type": "adaptive"}
			if self._reasoning_effort:
				body["output_config"] = {"effort": self._reasoning_effort}
		if tools:
			body["tools"] = [to_anthropic_tool(t) for t in tools]
		if self._temperature is not None and self._thinking == "off":
			# 扩展思考开启时 temperature 只能是 1（厂商限制），故不回传。
			body["temperature"] = self._temperature
		if stream:
			body["stream"] = True
		return body

	async def stream(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
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
		url = f"{self._base_url}/v1/messages"
		state: dict[str, Any] = {}
		self.last_usage = None
		self.last_context_tokens = None
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
					provider_error_message(resp.status_code, sanitize_http_body(raw)),
					status_code=resp.status_code,
					retry_after_ms=parse_retry_after(resp.headers.get("Retry-After")),
				)
			event_name = ""
			async for line in resp.aiter_lines():
				abort.raise_if_aborted()
				if line.startswith("event:"):
					event_name = line[len("event:") :].strip()
					continue
				if not line.startswith("data:"):
					continue
				u, chunks = _consume_sse_event(event_name, line[len("data:") :].strip(), state)
				if u:
					if u.get("input_tokens") is not None and "output_tokens" not in u:
						state["input_usage"] = u
					last_usage = u
				for chunk in chunks:
					yield chunk
		for chunk in _finish_pending_tool_bufs(state):
			abort.raise_if_aborted()
			yield chunk
		self.last_usage = last_usage
		self._settle_usage(last_usage)

	def _settle_usage(self, usage: dict[str, Any] | None) -> None:
		if not usage:
			return
		self.last_context_tokens = _positive_int(
			usage.get("input_tokens")
		) or _positive_int(usage.get("prompt_tokens"))
		if not self._usage_recorded_this_stream:
			self._usage_recorded_this_stream = True
			self._record_usage_safe(usage)

	async def _stream_stdlib(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		"""httpx 缺失时的 urllib 回退（与 DeepSeek 客户端同构的线程 + 队列）。"""
		body = self._build_body(messages, tools, stream=True)
		url = f"{self._base_url}/v1/messages"
		data = json.dumps(body).encode("utf-8")
		loop = asyncio.get_running_loop()
		queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
		self.last_usage = None
		self.last_context_tokens = None
		self._usage_recorded_this_stream = False

		def worker() -> None:
			state: dict[str, Any] = {}
			last_usage: dict[str, Any] | None = None
			try:
				req = Request(url, data=data, headers=self._headers(), method="POST")
				with urlopen(req, timeout=120) as resp:
					event_name = ""
					while True:
						raw = resp.readline()
						if not raw:
							break
						line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
						if line.startswith("event:"):
							event_name = line[len("event:") :].strip()
							continue
						if not line.startswith("data:"):
							continue
						u, chunks = _consume_sse_event(
							event_name, line[len("data:") :].strip(), state
						)
						if u:
							if u.get("input_tokens") is not None and "output_tokens" not in u:
								state["input_usage"] = u
							last_usage = u
						for chunk in chunks:
							loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
					for chunk in _finish_pending_tool_bufs(state):
						loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
					loop.call_soon_threadsafe(
						queue.put_nowait, ("usage", last_usage)
					)
					loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
			except HTTPError as e:
				detail = sanitize_http_body(e.read().decode("utf-8", errors="replace"))
				loop.call_soon_threadsafe(
					queue.put_nowait,
					(
						"err",
						ProviderError(
							provider_error_message(e.code, detail),
							status_code=e.code,
							retry_after_ms=parse_retry_after(e.headers.get("Retry-After")),
						),
					),
				)
			except URLError as e:
				loop.call_soon_threadsafe(queue.put_nowait, ("err", NetworkError(str(e))))
			except Exception as e:  # noqa: BLE001
				loop.call_soon_threadsafe(queue.put_nowait, ("err", e))

		threading.Thread(target=worker, name="anthropic-sse", daemon=True).start()

		while True:
			abort.raise_if_aborted()
			kind, payload = await queue.get()
			if kind == "done":
				return
			if kind == "err":
				raise payload
			if kind == "usage":
				self.last_usage = payload
				self._settle_usage(payload)
				continue
			yield payload  # type: ignore[misc]


def _usage_to_openai_shape(usage: dict[str, Any]) -> dict[str, Any]:
	"""Anthropic usage → 账本期望的 OpenAI 字段名。

	Anthropic: input_tokens / output_tokens / cache_read_input_tokens /
	           cache_creation_input_tokens
	OpenAI:    prompt_tokens / completion_tokens / prompt_tokens_details.cached_tokens

	注意 Anthropic 的 ``input_tokens`` **不含**缓存命中与缓存写入部分，
	故 prompt_tokens 应是三者之和，否则面板输入会显著偏低。
	"""
	inp = _positive_int(usage.get("input_tokens")) or 0
	out = _positive_int(usage.get("output_tokens")) or 0
	read = _positive_int(usage.get("cache_read_input_tokens")) or 0
	write = _positive_int(usage.get("cache_creation_input_tokens")) or 0
	converted: dict[str, Any] = {
		"prompt_tokens": inp + read + write,
		"completion_tokens": out,
	}
	if read:
		converted["prompt_tokens_details"] = {"cached_tokens": read}
	if write:
		converted["cache_creation_tokens"] = write
	return converted
