from __future__ import annotations

import time
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.get_time.prompt import DESCRIPTION


class GetTimeTool:
	name = "getTime"

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		self.false_ = {
			"name": "getTime",
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"properties": {},
				"additionalProperties": False,
			},
		}
		return self.false_

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
		return ToolResult(content=now)
