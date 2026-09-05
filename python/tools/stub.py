"""工具脚手架共享辅助函数（尚未实现）。"""

from __future__ import annotations

from tools.base_tool import ToolResult


def not_implemented(tool_name: str) -> ToolResult:
	return ToolResult(
		content=f"{tool_name}: not implemented yet",
		is_error=True,
	)
