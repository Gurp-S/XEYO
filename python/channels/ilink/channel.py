"""iLink Channel：入站入队，出站终稿文本/图片/文件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from channels.base import Channel, InboundMessage
from channels.filehelper.prefix import is_own_reply, xeyo_reply
from channels.ilink import SESSION_ID
from channels.jobs import JobRecord
from channels.runner import FinalOnlyRunner
from common.errors import safe_error_text


class OutboundILink(Protocol):
	async def send_text(
		self,
		text: str,
		*,
		to_user_id: str | None = None,
		context_token: str | None = None,
	) -> None: ...
	async def send_image(self, path: Path) -> None: ...
	async def send_file(self, path: Path) -> None: ...


class ILinkChannel(Channel):
	name = "ilink"

	def __init__(self, runner: FinalOnlyRunner, bridge: OutboundILink) -> None:
		self._runner = runner
		self._bridge = bridge

	async def handle_inbound(self, message: InboundMessage) -> str:
		sid = (message.session_id or "").strip() or SESSION_ID
		text = (message.text or "").strip()
		if is_own_reply(text):
			return ""
		images = list(message.images or ())
		raw = message.raw if isinstance(message.raw, dict) else {}
		peer = (
			(message.sender_id or "").strip()
			or str(getattr(self._bridge, "peer_id", "") or "").strip()
			or None
		)
		ctx = (
			str(raw.get("ctx") or "").strip()
			or str(getattr(self._bridge, "context_token", "") or "").strip()
			or None
		)
		try:
			return self._runner.enqueue(
				session_id=sid,
				text=text,
				images=images or None,
				reply_peer=peer,
				reply_ctx=ctx,
			)
		except TypeError:
			return self._runner.enqueue(
				session_id=sid, text=text, images=images or None
			)

	async def send_final(
		self,
		*,
		session_id: str,
		text: str,
		meta: dict[str, Any] | None = None,
	) -> None:
		body = xeyo_reply(text)
		if not body:
			return
		meta = meta or {}
		await self._bridge.send_text(
			body,
			to_user_id=str(meta.get("peer") or "") or None,
			context_token=str(meta.get("ctx") or "") or None,
		)

	async def send_job_result(self, rec: JobRecord) -> None:
		if not rec.session_id.startswith("ilink:"):
			return
		meta = {"peer": rec.reply_peer or "", "ctx": rec.reply_ctx or ""}
		if rec.status == "done":
			await self.send_final(
				session_id=rec.session_id, text=rec.final_text or "", meta=meta
			)
			return
		if rec.status == "error":
			await self.send_final(
				session_id=rec.session_id,
				# T34：错误回帖经安全过滤，内部异常痕迹不出通道。
				text=safe_error_text(rec.error or "", fallback="unknown error"),
				meta=meta,
			)
