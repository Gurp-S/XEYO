"""SendToWeChat — 把本地文件/图片发到已登录的微信远程。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.send_to_wechat_tool.prompt import DESCRIPTION

SEND_TO_WECHAT_TOOL_NAME = "SendToWeChat"


class SendToWeChatTool:
	name = SEND_TO_WECHAT_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		# 外发副作用：不可标只读（ask/plan 白名单也不应包含本工具）。
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def __init__(self, cwd: str = ".") -> None:
		self._cwd = cwd

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"properties": {
					"path": {
						"type": "string",
						"description": "Absolute or workspace-relative file path.",
					}
				},
				"required": ["path"],
				"additionalProperties": False,
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = str((input or {}).get("path") or "").strip()
		if not raw:
			return ToolResult(content="path is required", is_error=True)
		p = Path(raw)
		if not p.is_absolute():
			p = Path(self._cwd) / p
		p = p.resolve()
		from channels.remote_deliver import send_remote_file

		try:
			note = await send_remote_file(p)
		except Exception as e:  # noqa: BLE001
			return ToolResult(
				content=f"SendToWeChat failed: {type(e).__name__}: {e}",
				is_error=True,
			)
		return ToolResult(content=note)
