from __future__ import annotations

from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.echo.prompt import DESCRIPTION

# 定义一个简单的Echo工具，它将输入的文本原样返回

class EchoTool:
	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	name = "echo"

	def schema(self) -> dict[str, Any]:
		return {
			"name": "echo",
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"properties": {"text": {"type": "string"}},
				"required": ["text"],
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = input if isinstance(input, dict) else {}
		return ToolResult(content=str(raw.get("text", "")))
