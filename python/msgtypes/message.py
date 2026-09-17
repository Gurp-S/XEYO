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
	# T_now v2 留痕面（C 阶段）：引擎注入的易变块以 role=system 进历史，
	# 模型可见、用户不可见。三字段是台账身份，不是内容：
	#   note_kind 管道标记（见 prompt/pre_llm_inject.PIPE_*）
	#   note_key  块登记名（去重身份）
	#   note_fp   正文指纹（值变才重注）
	# 非空即 hidden：UI 面过滤、投影面照常、压缩面按 key 折叠保留最新。
	note_kind: str = ""
	note_key: str = ""
	note_fp: str = ""

	@property
	def hidden(self) -> bool:
		"""是否是引擎注入的留痕条目（模型可见 / 用户不可见）。"""
		return bool(self.note_key)


def system_note(
	text: str,
	*,
	key: str,
	fp: str,
	kind: str = "state",
) -> Message:
	"""构造 T_now 留痕条目（管道 2/3 → 历史中的原生 system 消息）。

	形态即身份：role=system ⇒ 既非 user（说话人隔离成立）也非 assistant
	（模型不会以为自己调过某个工具）；不可调用性来自形态本身。
	"""
	return Message(
		role="system",
		content=text,
		note_kind=kind,
		note_key=key,
		note_fp=fp,
	)


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
	reasoning: str = "",
) -> Message:
	"""构造 assistant 消息。

	reasoning 是厂商思考态原文（DeepSeek `reasoning_content`），作为 content
	数组的 block 留档：原样存储，不做任何清洗/截断/重排。**任何带 reasoning
	的 assistant 轮（含纯文本轮）都承载**——dsh 口径
	（`dsh-src/packages/llm/llm-deepseek/src/serialize.ts:228-233`）：
	官方规则只要求工具轮回传、非工具轮忽略该字段（无害）；且非工具轮的
	reasoning 是跨厂商转码时恢复思考签名的唯一载体（2026-09-14 落地）。
	"""
	blocks: list[dict[str, Any]] = []
	if reasoning:
		blocks.append({"type": "reasoning", "text": reasoning})
	if text:
		blocks.append({"type": "text", "text": text})
	for tu in tool_uses or []:
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
		# block 数组只在「有工具或带思考」时使用；纯文本无 reasoning 轮回落
		# 纯字符串（老形状零回归——下游 20+ 处 isinstance(content,str) 消费者
		# 只需兼容"带 reasoning 的纯文本轮"这一种新形状）。
		content=blocks if (tool_uses or reasoning) else text,
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