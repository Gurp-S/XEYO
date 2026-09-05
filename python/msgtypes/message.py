from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

# 消息体

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolUse:
	id: str
	name: str
	input: dict[str, Any]


@dataclass
class Message:
	role: Role
	content: str | list[dict[str, Any]]
	id: str = field(default_factory=lambda: uuid4().hex)
	tool_call_id: str | None = None  # role=tool 时关联 tool_use.id
	name: str | None = None  # tool 名
	# T28：过程旁白（background only）——随 assistant 消息留档供追溯；
	# 投影送模型时忽略此字段（as_api_messages 只读 content）。
	narration: str = ""
	# 44 号：中断锚（「用户看到的必须入史」）——abort 时部分输出以该标记留档。
	interrupted: bool = False


def user_message(
	text: str,
	*,
	images: list[str] | None = None,
	message_id: str | None = None,
) -> Message:
	mid = (message_id or "").strip() or uuid4().hex
	urls = [
		u.strip()
		for u in (images or [])
		if u and (u.strip().startswith("data:image") or u.strip().startswith("xeyo-media://"))
	]
	if not urls:
		return Message(role="user", content=text, id=mid)
	blocks: list[dict[str, Any]] = []
	if text:
		blocks.append({"type": "text", "text": text})
	for u in urls:
		blocks.append({"type": "image_url", "image_url": {"url": u}})
	return Message(role="user", content=blocks, id=mid)


def assistant_text_message(
	text: str,
	tool_uses: list[ToolUse] | None = None,
	*,
	narration: str = "",
	interrupted: bool = False,
) -> Message:
	if not tool_uses:
		return Message(
			role="assistant", content=text, narration=narration or "", interrupted=interrupted
		)
	blocks: list[dict[str, Any]] = []
	if text:
		blocks.append({"type": "text", "text": text})
	for tu in tool_uses:
		blocks.append(
			{
				"type": "tool_use",
				"id": tu.id,
				"name": tu.name,
				"input": tu.input,
			}
		)
	return Message(
		role="assistant",
		content=blocks,
		narration=narration or "",
		interrupted=interrupted,
	)


def tool_result_message(
	tool_use_id: str,
	name: str,
	content: str,
	*,
	is_error: bool = False,
	images: list[str] | None = None,
) -> Message:
	# γ4 围栏在投影送模型时（proj_cache 增量 / 全量 project）添加，
	# 不在此处写入，以免污染 transcript / ToolResultEvent / UI。
	blocks: list[dict[str, Any]] = [
		{
			"type": "tool_result",
			"tool_use_id": tool_use_id,
			"content": content,
			"is_error": is_error,
		}
	]
	for url in images or []:
		u = (url or "").strip()
		if u.startswith("data:image"):
			blocks.append({"type": "image_url", "image_url": {"url": u}})
	return Message(
		role="tool",
		name=name,
		tool_call_id=tool_use_id,
		content=blocks,
	)