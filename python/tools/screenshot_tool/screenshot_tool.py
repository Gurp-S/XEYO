"""Screenshot — 抓主显示器，供模型查看桌面。"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.screenshot_tool.prompt import DESCRIPTION

SCREENSHOT_TOOL_NAME = "Screenshot"


def _wechat_copy_path(path: Path) -> Path:
	"""优先发缩小预览，避免原图 CDN 上传拖很久。"""
	preview = path.with_name(path.stem + ".preview.png")
	return preview if preview.is_file() else path


def _wants_image(raw: Any) -> bool:
	if isinstance(raw, bool):
		return raw
	if isinstance(raw, str):
		return raw.strip().lower() in {"1", "true", "yes", "y"}
	return bool(raw)


class ScreenshotTool:
	name = SCREENSHOT_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		# 抓屏 + 可选微信外发：有副作用，ask/plan 不得放行。
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		return {
			"name": SCREENSHOT_TOOL_NAME,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"properties": {
					"monitor": {
						"type": "integer",
						"description": "1-based monitor index. Default 1 (primary).",
					},
					"view": {
						"type": "boolean",
						"description": (
							"Set true to attach the screenshot image for visual "
							"inspection. Default false: returns only the saved path."
						),
					},
				},
				"additionalProperties": False,
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = (input or {}).get("monitor", 1)
		try:
			monitor = int(raw)
		except (TypeError, ValueError):
			monitor = 1
		if monitor < 1:
			monitor = 1

		from channels.filehelper.screenshot import capture_primary, preview_png

		try:
			path = await asyncio.to_thread(capture_primary, monitor=monitor)
		except Exception as e:  # noqa: BLE001
			return ToolResult(
				content=f"Screenshot failed: {type(e).__name__}: {e}",
				is_error=True,
			)

		from channels.remote_deliver import schedule_send_remote_file, wechat_remote_ready

		# 先丢后台发微信，再按需编码给模型看的附件，两者并行。
		ready = wechat_remote_ready()
		if ready:
			schedule_send_remote_file(_wechat_copy_path(path), as_image=True)

		images: list[str] | None = None
		if _wants_image((input or {}).get("view")):
			embed = await asyncio.to_thread(preview_png, path)
			if embed:
				b64 = base64.b64encode(embed).decode("ascii")
				images = [f"data:image/png;base64,{b64}"]
		if images:
			note = (
				f"Captured primary display.\nSaved: {path}\n"
				"The screenshot image is attached for you to inspect."
			)
		elif (input or {}).get("view"):
			note = (
				f"Captured primary display.\nSaved: {path}\n"
				"(Image too large to attach; open the file if needed.)"
			)
		else:
			note = (
				f"Captured primary display.\nSaved: {path}\n"
				"(Image not attached; call again with view=true to inspect it.)"
			)
		if ready:
			note = f"{note}\nWeChat copy is sending in the background."
		return ToolResult(content=note, images=images)
