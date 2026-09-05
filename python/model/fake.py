from __future__ import annotations

import asyncio
from typing import AsyncIterator
from uuid import uuid4

from engine.abort import AbortController
from model.chunks import ModelChunk
from msgtypes.message import ToolUse

# 模拟模型客户端，主要用于测试和调试。


class FakeModelClient:
	"""
	规则：
	1) 若历史里已有 echo 的 tool_result → 回复 echoed: <text>
	2) 若最后一条 user 文本以 echo: 开头 → 发起 tool_use echo
	3) 否则纯文本回复
	"""

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		abort.raise_if_aborted()

		# 1) 找最近的 echo tool_result
		echoed = _find_latest_echo_result(messages)
		if echoed is not None:
			async for chunk in _stream_text(f"echoed: {echoed}", abort):
				yield chunk
			return

		# 2) 找最后一条用户纯文本
		last_user = _last_user_text(messages)
		if last_user is not None and last_user.startswith("echo:"):
			payload = last_user[len("echo:") :].strip()
			await asyncio.sleep(0.05)
			yield ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(
					id=f"call_{uuid4().hex[:8]}",
					name="echo",
					input={"text": payload},
				),
			)
			return

		# 3) 普通回复（逐字流式，便于联调 UI）
		async for chunk in _stream_text(f"ok: {last_user or ''}", abort):
			yield chunk


async def _stream_text(text: str, abort: AbortController) -> AsyncIterator[ModelChunk]:
	for ch in text:
		abort.raise_if_aborted()
		yield ModelChunk(kind="text_delta", text=ch)
		# CLI 可见流式的小延迟；测试仍足够快。
		await asyncio.sleep(0.008)


def _last_user_text(messages: list[dict]) -> str | None:
	from prompt.fence import unwrap_remote_user_text

	for m in reversed(messages):
		if m.get("role") == "user" and isinstance(m.get("content"), str):
			return unwrap_remote_user_text(m["content"])
	return None


def _find_latest_echo_result(messages: list[dict]) -> str | None:
	"""仅当「最近一条真实 user 文本之后」存在 tool_result 时触发 echoed 回复。"""
	from prompt.fence import unwrap_tool_output

	for m in reversed(messages):
		content = m.get("content")
		if m.get("role") == "user" and isinstance(content, str):
			return None
		if isinstance(content, list):
			for block in content:
				if (
					isinstance(block, dict)
					and block.get("type") == "tool_result"
					and not block.get("is_error")
				):
					c = block.get("content")
					if isinstance(c, str):
						inner, _ = unwrap_tool_output(c)
						return inner
	return None
