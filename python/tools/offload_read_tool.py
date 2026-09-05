"""offload_read — L3 外部化的按需读取工具（hidden-but-registered）。

被外部化的超长工具结果（memory.offload）存为 `.xeyo_offload/*.tool.txt`。
模型看到引用后，用本工具按行区间读回。exposure=hidden：不撑 schema（tools 数组冻结红线），
注册但保留可用性（幻觉/按需调用仍经 run() 权限三态，fail-safe）。
"""
from __future__ import annotations

from typing import Any
from pathlib import Path

from engine.abort import AbortController
from tools.base_tool import ToolResult


class OffloadReadTool:
	name = "offload_read"

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	#: exposure 由 tools.meta 的 offload_read 条目决定（默认 hidden）。
	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": (
				"按行区间读取一个被外部化的工具结果文件（memory.offload 引用所指向）。"
				"当投影里出现 [tool offloaded: <path> ...] 引用且你需要细节时，用本工具读取。"
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"path": {"type": "string", "description": "外部化工具结果文件路径"},
					"start": {"type": "integer", "description": "起始行(含，1 起)"},
					"end": {"type": "integer", "description": "结束行(含)"},
				},
				"required": ["path"],
			},
		}

	async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
		abort.raise_if_aborted()
		p = Path(str((input or {}).get("path") or "")).expanduser()
		if not p.is_file():
			return ToolResult(content=f"(offload 文件不存在: {p})", is_error=True)
		try:
			text = p.read_text(encoding="utf-8")
		except OSError as e:
			return ToolResult(content=f"(读取失败: {e})", is_error=True)
		start = int(input.get("start") or 1)
		end = int(input.get("end") or 0) or None
		lines = text.split("\n")
		if end:
			body = "\n".join(lines[max(0, start - 1):end])
		else:
			body = "\n".join(lines[max(0, start - 1):])
		return ToolResult(content=body)
