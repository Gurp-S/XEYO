"""File Helper Channel：入站入队，出站只发最终文本/文件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from channels.base import Channel, InboundMessage
from channels.filehelper import SESSION_ID
from channels.filehelper.prefix import is_own_reply, xeyo_reply
from channels.jobs import JobRecord
from channels.runner import FinalOnlyRunner
from common.errors import safe_error_text


class OutboundBridge(Protocol):
	async def send_text(self, text: str) -> None: ...
	async def send_file(self, path: Path) -> None: ...


class FileHelperChannel(Channel):
	name = "filehelper"

	def __init__(self, runner: FinalOnlyRunner, bridge: OutboundBridge) -> None:
		self._runner = runner
		self._bridge = bridge

	async def handle_inbound(self, message: InboundMessage) -> str:
		sid = (message.session_id or "").strip() or SESSION_ID
		text = (message.text or "").strip()
		if is_own_reply(text):
			return ""
		return self._runner.enqueue(session_id=sid, text=text)

	async def send_final(
		self,
		*,
		session_id: str,
		text: str,
		meta: dict[str, Any] | None = None,
	) -> None:
		body = xeyo_reply(text)
		if body:
			await self._bridge.send_text(body)

	async def send_job_result(self, rec: JobRecord) -> None:
		if not rec.session_id.startswith("filehelper:"):
			return
		if rec.status == "done":
			await self.send_final(session_id=rec.session_id, text=rec.final_text or "")
			return
		if rec.status == "error":
			await self.send_final(
				session_id=rec.session_id,
				# T34：错误回帖经安全过滤，内部异常痕迹不出通道。
				text=safe_error_text(rec.error or "", fallback="unknown error"),
			)
