from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from typing import Any

from msgtypes.message import ToolUse

# 模型输出块

@dataclass
class ModelChunk:
	kind: Literal["text_delta", "reasoning_delta", "reasoning_block", "tool_use"] # 块类型
	text: str = "" # 文本
	tool_use: ToolUse | None = None # 使用的工具
	block: dict[str, Any] | None = None # 完整原生思考块；显示增量不承担回放身份


# provider adapter 的兼容名称；核心 runtime 只把它当作统一 ModelEvent。
ModelEvent = ModelChunk


__all__ = ["ModelChunk", "ModelEvent"]
