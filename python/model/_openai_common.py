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
import logging
import weakref
from typing import Any

from model.chunks import ModelChunk
from msgtypes.message import ToolUse

try:
	import httpx
except ImportError:  # pragma: no cover
	httpx = None  # type: ignore


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
	line: str, tool_bufs: dict[int, dict[str, Any]], *, end_state: dict | None = None
) -> tuple[dict[str, Any] | None, list[ModelChunk]]:
	"""单次 json.loads 解析一行 SSE，返回 (usage, chunks)。

	tool_calls 的 arguments 拼到可 loads 时立刻 yield tool_use（提前执行只读工具）。
	"""
	if not line or not line.startswith("data:"):
		return None, []
	payload = line[len("data:") :].strip()
	if payload == "[DONE]" and end_state is not None:
		end_state["done"] = True
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
	if end_state is not None and choices[0].get("finish_reason"):
		end_state["finish_reason"] = choices[0]["finish_reason"]
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
	if end_state is not None and (out or delta.get("tool_calls")):
		end_state["has_output"] = True
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


def prune_orphan_tool_rows(
	messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
	"""丢弃没有前置 assistant tool_calls 应答的 ``role="tool"`` 行（fail-open）。

	厂商按「工具结果必须是某条 assistant tool_calls 的应答」校验请求体：投影链
	（压缩 / T_now 注入 / 任何上游改写）一旦多出一条无主的 tool 行，该会话就会
	对**之后每一条消息**都以 400 失败——结构性卡死，改消息内容无效。**实测
	2026-09-20**（sess_mu9oqy8m_63ljiu）：投影 manifest 137 calls / 138 results，
	厂商回 ``Messages with role 'tool' must be a response to a preceding message
	with 'tool_calls'``。``session.tool_sequence.discard_unpaired_tool_results``
	只覆盖 MessageStore 投影之前的内部形状；这里是**最后一公里**（wire 出口），
	覆盖它之后的一切改写。

	宁可这一条结果不进上下文（信息缺失，模型仍可重读），也不能让整个会话报废。
	返回 (行, 被丢弃的 tool_call_id 列表)；无丢弃时行对象原样返回。
	"""
	out: list[dict[str, Any]] = []
	outstanding: set[str] = set()
	dropped: list[str] = []
	for m in messages:
		role = m.get("role")
		if role == "assistant":
			outstanding = {
				str(c.get("id"))
				for c in (m.get("tool_calls") or [])
				if isinstance(c, dict) and c.get("id")
			}
			out.append(m)
			continue
		if role == "tool":
			tid = str(m.get("tool_call_id") or "")
			if tid and tid in outstanding:
				outstanding.discard(tid)
				out.append(m)
			else:
				dropped.append(tid)
			continue
		outstanding = set()
		out.append(m)
	if not dropped:
		return messages, []
	return out, dropped


def normalize_messages_for_openai(
	messages: list[dict[str, Any]],
	*,
	provider: str = "",
	model: str = "",
) -> list[dict[str, Any]]:
	"""将内部消息转换为 OpenAI chat 格式，并按供应商上限物化图片。"""
	from media_store import materialize_image_url
	from model.tool_media import append_tool_media, tool_images

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
	pending_tool_images: list[dict] = []
	for m in messages:
		role = m.get("role")
		content = m.get("content")
		if role != "tool":
			append_tool_media(out, pending_tool_images)

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
				#
				# 这里**曾经**还有一条"给引擎伪造的 tool_call id 补一段占位思考"
				# 的分支（2026-09-14 实测：DeepSeek thinking 模式对没签发过的 id
				# 强制要求 reasoning_content，缺则 400）。它是在替 T_now 旧档
				# ``env_channel`` 的伪对擦屁股。自 2026-09-22 起降级阶梯改为
				# 包封片段（见 prompt/notice_channel.py），生产路径不再产伪对，
				# 故不再往历史里编造模型从未产出的思考——真要用那档做对照，
				# 就该看见它原本的 400，而不是被补丁掩盖。
				reasoning_text = "".join(reasoning_parts)
				if reasoning_text:
					msg["reasoning_content"] = reasoning_text
				if tool_calls:
					msg["tool_calls"] = tool_calls
				out.append(msg)
				continue

		if role == "tool":
			pending_tool_images.extend(tool_images(content, provider=provider, model=model, image_count=image_count))
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
	pruned, dropped = prune_orphan_tool_rows(out)
	if dropped:
		# 只记数量与前几个 id（工具调用 id 非内容），便于定位投影链上的改写点。
		logging.getLogger(__name__).warning(
			"wire boundary dropped %d orphan tool result row(s) "
			"(no preceding assistant tool_calls): %s",
			len(dropped),
			", ".join(dropped[:5]),
		)
		try:  # 观测：丢了几行进账本（失败绝不影响发射）
			from usage.ledger import record_wire_drop

			record_wire_drop(dropped_ids=dropped, target="openai_compat")
		except Exception:  # noqa: BLE001
			logging.getLogger(__name__).debug("record_wire_drop failed", exc_info=True)
		return pruned
	append_tool_media(out, pending_tool_images)
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
