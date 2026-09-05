from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from msgtypes.message import ToolUse

# 模型输出块

@dataclass
class ModelChunk:
	kind: Literal["text_delta", "reasoning_delta", "tool_use"] # 块类型
	text: str = "" # 文本
	tool_use: ToolUse | None = None # 使用的工具
