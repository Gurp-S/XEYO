"""OpenAI 兼容客户端的共享纯函数（DeepSeek / OpenAI / 本地模型共用）。

把原本散落在 model/deepseek.py 里的模块级辅助函数抽到这里，让
model/deepseek.py 与 model/openai_compat.py 都依赖本叶子模块，而不是
「通用客户端反向依赖厂商专用模块」的倒挂结构。

- normalize_messages_for_openai  内部消息 → OpenAI chat 消息（含图作物化）
- to_openai_tool                 工具 schema → OpenAI function 对象
- get_shared_httpx_client        按事件循环绑定的进程级共享 AsyncClient
- consume_sse_line_with_usage    SSE 单行解析：一次 json.loads 取 (usage, chunks)；
                                 arguments 可 loads 时立刻 yield tool_use
- try_finalize_tool_buf          单条 tool buffer 闭合检测（json.loads）
- finish_tool_bufs               流尾只收尾尚未 emit 的 buffer
"""

from __future__ import annotations

import asyncio
import json
import weakref
from typing import Any

from model.chunks import ModelChunk
from msgtypes.message import ToolUse

try:
	import httpx
except ImportError:  # pragma: no cover
	httpx = None  # type: ignore


#: 环境声道伪造对的 tool_call id 前缀。与 ``prompt.t_now_strategy.ENV_ID_PREFIX``
#: 同源；此处保留本地常量，避免 model 层反向依赖 prompt 层。
ENV_TOOL_CALL_ID_PREFIX = "xeyo_env_"

#: 伪造对补的**结构性占位**思考态（信息：声明该条 assistant 是引擎的环境通知
#: 中继，而非模型自己的思考产出）。存在的唯一原因是协议合规——见
#: ``normalize_messages_for_openai`` assistant 分支的注释。
ENV_RELAY_REASONING_PLACEHOLDER = "[xeyo] environment notice relay"


# 事件循环 → 共享 AsyncClient。httpx 连接池绑定创建它的 loop，不能跨 loop 复用；
# loop 被 GC 时条目随之消失（测试场景每个 loop 一个 client）。
_shared_httpx_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
	weakref.WeakKeyDictionary()
)


def get_shared_httpx_client(timeout: float) -> "httpx.AsyncClient":
	"""进程级共享 AsyncClient，按事件循环绑定（httpx 连接池不能跨 loop 复用）。

	流式请求的 timeout 在请求级覆盖，避免不同供应商超时互相干扰。
	"""
	if httpx is None:  # pragma: no cover
		raise ImportError("httpx is not installed")
	loop = asyncio.get_running_loop()
	client = _shared_httpx_clients.get(loop)
	if client is None:
		client = httpx.AsyncClient(
			timeout=httpx.Timeout(timeout),
			limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
		)
		_shared_httpx_clients[loop] = client
	return client


def try_finalize_tool_buf(buf: dict[str, Any]) -> ToolUse | None:
	"""arguments 已是合法 JSON 时产出 ToolUse；同一 buffer 只发一次。

	用 json.loads 成功作为闭合判据（勿手写括号计数）。空 arguments 留给
	finish_tool_bufs 用 ``{}`` 收尾。
	"""
	if buf.get("_emitted") or not buf.get("name"):
		return None
	raw = buf.get("arguments") or ""
	if not str(raw).strip():
		return None
	try:
		args = json.loads(raw)
	except json.JSONDecodeError:
		return None
	buf["_emitted"] = True
	# 闭合后再到的空白增量忽略（_emitted 已置位）
	return ToolUse(
		id=str(buf.get("id") or "") or f"call_{buf['name']}",
		name=str(buf["name"]),
		input=args if isinstance(args, dict) else {"value": args},
	)


def consume_sse_line_with_usage(
	line: str, tool_bufs: dict[int, dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[ModelChunk]]:
	"""单次 json.loads 解析一行 SSE，返回 (usage, chunks)。

	tool_calls 的 arguments 拼到可 loads 时立刻 yield tool_use（提前执行只读工具）。
	"""
	if not line or not line.startswith("data:"):
		return None, []
	payload = line[len("data:") :].strip()
	if not payload or payload == "[DONE]":
		return None, []
	try:
		event = json.loads(payload)
	except json.JSONDecodeError:
		return None, []
	usage = event.get("usage")
	u = usage if isinstance(usage, dict) and usage else None
	choices = event.get("choices") or []
	if not choices:
		return u, []
	delta = choices[0].get("delta") or {}
	out: list[ModelChunk] = []
	reasoning = delta.get("reasoning_content")
	if reasoning:
		out.append(ModelChunk(kind="reasoning_delta", text=str(reasoning)))
	if delta.get("content"):
		out.append(ModelChunk(kind="text_delta", text=delta["content"]))
	for tc in delta.get("tool_calls") or []:
		idx = tc.get("index", 0)
		buf = tool_bufs.setdefault(
			idx, {"id": "", "name": "", "arguments": "", "_emitted": False}
		)
		if buf.get("_emitted"):
			# 已闭合：忽略后续 arguments 增量（厂商偶发补空白）
			if tc.get("id") and not buf.get("id"):
				buf["id"] = tc["id"]
			continue
		if tc.get("id"):
			buf["id"] = tc["id"]
		fn = tc.get("function") or {}
		touched = False
		if fn.get("name"):
			buf["name"] = fn["name"]
			touched = True
		if fn.get("arguments"):
			buf["arguments"] = str(buf.get("arguments") or "") + str(fn["arguments"])
			touched = True
		# name 可能晚于完整 arguments 到达；任一字段更新都试一次闭合
		if touched:
			finalized = try_finalize_tool_buf(buf)
			if finalized is not None:
				out.append(ModelChunk(kind="tool_use", tool_use=finalized))
	return u, out


def finish_tool_bufs(tool_bufs: dict[int, dict[str, Any]]) -> list[ModelChunk]:
	"""流结束时只收尾尚未 emit 的 buffer（含空 args → ``{}``）。"""
	out: list[ModelChunk] = []
	for buf in tool_bufs.values():
		if buf.get("_emitted") or not buf.get("name"):
			continue
		raw = buf.get("arguments") or ""
		try:
			args = json.loads(raw if str(raw).strip() else "{}")
		except json.JSONDecodeError:
			args = {"_raw": raw}
		buf["_emitted"] = True
		out.append(
			ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id=str(buf.get("id") or "") or f"call_{buf['name']}",
					name=str(buf["name"]),
					input=args if isinstance(args, dict) else {"value": args},
				),
			)
		)
	return out


def normalize_messages_for_openai(
	messages: list[dict[str, Any]],
	*,
	provider: str = "",
	model: str = "",
) -> list[dict[str, Any]]:
	"""将内部消息转换为 OpenAI chat 格式，并按供应商上限物化图片。"""
	from media_store import materialize_image_url

	image_count = 0
	for row in messages:
		content = row.get("content")
		if isinstance(content, list):
			image_count += sum(
				1
				for block in content
				if isinstance(block, dict) and block.get("type") == "image_url"
			)

	out: list[dict[str, Any]] = []
	for m in messages:
		role = m.get("role")
		content = m.get("content")

		if role == "system":
			out.append(
				{
					"role": "system",
					"content": content if isinstance(content, str) else json.dumps(content),
				}
			)
			continue

		if role == "user":
			if isinstance(content, str):
				out.append({"role": "user", "content": content})
				continue
			if isinstance(content, list):
				vision: list[dict[str, Any]] = []
				texts: list[str] = []
				for block in content:
					if not isinstance(block, dict):
						continue
					if block.get("type") == "tool_result":
						out.append(
							{
								"role": "tool",
								"tool_call_id": block.get("tool_use_id") or "",
								"content": str(block.get("content") or ""),
							}
						)
					elif block.get("type") == "text":
						texts.append(str(block.get("text") or ""))
					elif block.get("type") == "image_url":
						image_url = block.get("image_url")
						if not isinstance(image_url, dict):
							continue
						url = str(image_url.get("url") or "")
						if url.startswith(("xeyo-media://", "data:image/")):
							url = materialize_image_url(
								url,
								provider=provider,
								model=model,
								image_count=image_count,
							)
						vision.append({**block, "image_url": {**image_url, "url": url}})
				if vision:
					caption = "\n".join(t for t in texts if t).strip() or "Image attached."
					out.append(
						{
							"role": "user",
							"content": [
								{"type": "text", "text": caption},
								*vision,
							],
						}
					)
				elif texts:
					out.append({"role": "user", "content": "\n".join(texts)})
				continue

		if role == "assistant":
			if isinstance(content, str):
				out.append({"role": "assistant", "content": content})
				continue
			if isinstance(content, list):
				text_parts: list[str] = []
				reasoning_parts: list[str] = []
				tool_calls: list[dict[str, Any]] = []
				for block in content:
					if not isinstance(block, dict):
						continue
					if block.get("type") == "reasoning":
						reasoning_parts.append(str(block.get("text") or ""))
					elif block.get("type") == "text":
						text_parts.append(str(block.get("text") or ""))
					elif block.get("type") == "tool_use":
						tool_calls.append(
							{
								"id": block.get("id") or "call_unknown",
								"type": "function",
								"function": {
									"name": block.get("name") or "unknown",
									"arguments": json.dumps(
										block.get("input") or {}, ensure_ascii=False
									),
								},
							}
						)
				msg: dict[str, Any] = {
					"role": "assistant",
					"content": "".join(text_parts),
				}
				# 思考态原样回传：厂商要求参与拼接的正是历史里这条 assistant
				# 消息自己的思考，故按原文（未清洗/未截断/未重排）贴回。无思考
				# 则不发该字段。
				reasoning_text = "".join(reasoning_parts)
				if reasoning_text:
					msg["reasoning_content"] = reasoning_text
				elif tool_calls and any(
					str(tc.get("id") or "").startswith(ENV_TOOL_CALL_ID_PREFIX)
					for tc in tool_calls
				):
					# 环境声道伪造对（T_now env_channel）：这条 assistant 与其
					# tool_call id 都是引擎造的，厂商从未签发过该 id。**实测
					# 2026-09-14**（`TerminalBench/zero/probe_envpair_400.py` /
					# `probe_reasoning_400.py`）：DeepSeek 在 thinking 模式下对
					# 「自己没签发过的 tool_call」强制要求 reasoning_content，
					# 缺则 400 `must be passed back to the API`（真 id 则不要求）。
					# 故补一段**结构性占位**（只声明来源，不含任何指令/评价）。
					msg["reasoning_content"] = ENV_RELAY_REASONING_PLACEHOLDER
				if tool_calls:
					msg["tool_calls"] = tool_calls
				out.append(msg)
				continue

		if role == "tool":
			tool_call_id = m.get("tool_call_id") or ""
			# dsh 口径（serialize.ts:269-271）：空 tool 输出在 wire 上也需要
			# 非空内容——部分网关拒收空串 tool 消息，统一给结构性哨兵。
			if isinstance(content, list):
				for block in content:
					if isinstance(block, dict) and block.get("type") == "tool_result":
						out.append(
							{
								"role": "tool",
								"tool_call_id": block.get("tool_use_id") or tool_call_id,
								"content": str(block.get("content") or "") or "(no output)",
							}
						)
			else:
				out.append(
					{
						"role": "tool",
						"tool_call_id": tool_call_id,
						"content": str(content or "") or "(no output)",
					}
				)
	return out


def to_openai_tool(schema: dict[str, Any]) -> dict[str, Any]:
	if schema.get("type") == "function" and "function" in schema:
		return schema
	return {
		"type": "function",
		"function": {
			"name": schema["name"],
			"description": schema.get("description", ""),
			"parameters": schema.get("input_schema")
			or schema.get("parameters")
			or {"type": "object", "properties": {}},
		},
	}
