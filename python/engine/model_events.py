"""Provider → runtime 的严格事件边界。

各 provider 负责把原始 SSE/content block 转成 ``ModelChunk``；query loop 不再
读取厂商字段。这里做最后一层结构校验，避免半截 JSON、空 tool identity 或
非对象参数进入 ToolCoordinator。校验失败是执行层协议错误，不生成模型提示。
"""

from __future__ import annotations

from typing import Any

from model.chunks import ModelChunk, ModelEvent


class ModelProtocolError(ValueError):
	"""provider 已越过 adapter 却仍产出不合法的统一事件。"""


def normalize_model_event(value: Any) -> ModelEvent:
	if not isinstance(value, ModelChunk):
		raise ModelProtocolError("provider emitted a non-ModelEvent")
	kind = str(value.kind or "")
	if kind not in {"text_delta", "reasoning_delta", "reasoning_block", "tool_use"}:
		raise ModelProtocolError(f"unknown model event kind: {kind}")
	if kind == "reasoning_block":
		from engine.reasoning_blocks import validate_reasoning_block

		validate_reasoning_block(value.block)
		if value.text or value.tool_use is not None:
			raise ModelProtocolError("reasoning_block cannot carry text or tool_use")
		return value
	if value.block is not None:
		raise ModelProtocolError(f"{kind} cannot carry a reasoning block")
	if kind in {"text_delta", "reasoning_delta"}:
		if not isinstance(value.text, str):
			raise ModelProtocolError(f"{kind} text must be a string")
		if value.tool_use is not None:
			raise ModelProtocolError(f"{kind} cannot carry tool_use")
		return value
	tool_use = value.tool_use
	if tool_use is None:
		raise ModelProtocolError("tool_use event is missing tool_use")
	if not str(tool_use.id or "").strip():
		raise ModelProtocolError("tool_use event is missing id")
	if not str(tool_use.name or "").strip():
		raise ModelProtocolError("tool_use event is missing name")
	if not isinstance(tool_use.input, dict):
		raise ModelProtocolError("tool_use arguments must be an object")
	if value.text:
		raise ModelProtocolError("tool_use event cannot carry text")
	return value


__all__ = ["ModelProtocolError", "normalize_model_event"]
