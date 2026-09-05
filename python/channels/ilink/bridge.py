"""iLink 通道桥：UI 状态、登录凭证、发送文本/图片/文件、打字状态。

从 service.py 拆出：桥只关心「与微信侧的单条连接」，轮询/入站/镜像由
service / polling / inbound 模块编排。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from channels.ilink.client import ILinkClient, rpc_ok

log = logging.getLogger("xeyo.ilink")


async def _silent_typing(
	client: ILinkClient,
	token: str,
	user_id: str,
	ticket: str,
	status: int,
) -> None:
	try:
		await client.sendtyping(
			token, user_id=user_id, typing_ticket=ticket, status=status
		)
	except Exception:
		pass


class ILinkBridge:
	"""UI 状态 + 当前会话上下文（发消息需要 context_token）。"""

	def __init__(self) -> None:
		self.state = "stopped"
		self.error: str | None = None
		self.hint: str | None = None
		self._qr: bytes | None = None
		self._qr_rev = 0
		self._qr_mime = "image/png"
		self.peer_id = ""
		self.context_token = ""
		self._client: ILinkClient | None = None
		self._token = ""
		self._buf = ""
		self._typing: dict[str, str] = {}
		# asyncio 原语不在此创建（模块 import 时无 loop；跨 loop 复用会挂死）。
		# _run() 在运行中的 loop 里重建 _stop。
		self._stop: asyncio.Event | None = None
		self._loop_task: asyncio.Task[None] | None = None
		self._on_inbound = None
		self.last_poll_ret: object = None
		self.last_poll_msgs = 0
		self.last_poll_error: str | None = None
		self.poll_ok_at = 0.0
		self.poll_started_at = 0.0
		self.poll_timeouts = 0
		self.hold_ms = 35_000
		self.last_inbound: dict[str, Any] | None = None

	def _stop_event(self) -> asyncio.Event:
		"""惰性创建 _stop（绑定当前运行 loop）；start 路径由 _run 重建。"""
		if self._stop is None:
			self._stop = asyncio.Event()
		return self._stop

	@property
	def logged_in(self) -> bool:
		return self.state == "logged_in"

	@property
	def qr_rev(self) -> int:
		return self._qr_rev

	def qr_png(self) -> bytes | None:
		return self._qr

	def qr_mime(self) -> str:
		return self._qr_mime

	def _set_qr(self, blob: bytes | None, *, mime: str = "image/png") -> None:
		if blob == self._qr:
			return
		self._qr = blob
		self._qr_mime = mime
		if blob is not None:
			self._qr_rev += 1

	def set_inbound_handler(self, handler) -> None:
		self._on_inbound = handler

	async def send_text(
		self,
		text: str,
		*,
		to_user_id: str | None = None,
		context_token: str | None = None,
	) -> None:
		await self._send_items(
			[{"type": 1, "text_item": {"text": text}}],
			peer=to_user_id,
			ctx=context_token,
		)

	async def send_image(self, path: Path) -> None:
		from channels.ilink.media import MEDIA_IMAGE, image_item

		await self._send_uploaded(path, MEDIA_IMAGE, image_item)

	async def send_file(self, path: Path) -> None:
		from channels.ilink.media import MEDIA_FILE, file_item

		await self._send_uploaded(path, MEDIA_FILE, file_item)

	async def _send_uploaded(self, path: Path, media_type: int, wrap) -> None:  # noqa: ANN001
		from channels.ilink.media import upload_local

		client, token, peer, ctx = self._send_ready()
		info = await upload_local(client, token, peer, path, media_type=media_type)
		await self._send_items([wrap(info)], client=client, token=token, peer=peer, ctx=ctx)

	def _send_ready(self, *, peer: str | None = None, ctx: str | None = None):
		client = self._client
		token = self._token
		to = (peer or self.peer_id or "").strip()
		ticket = (ctx or self.context_token or "").strip()
		missing: list[str] = []
		if not client:
			missing.append("client")
		if not token:
			missing.append("token")
		if not to:
			missing.append("peer")
		if not ticket:
			missing.append("context_token")
		if missing:
			raise RuntimeError("ilink not ready to send (" + ",".join(missing) + ")")
		return client, token, to, ticket

	async def _send_items(
		self,
		items: list[dict[str, Any]],
		*,
		client: ILinkClient | None = None,
		token: str | None = None,
		peer: str | None = None,
		ctx: str | None = None,
	) -> None:
		if client is None or token is None or not (peer or "").strip() or not (ctx or "").strip():
			client, token, peer, ctx = self._send_ready(peer=peer, ctx=ctx)
		ticket = self._typing.get(peer, "")
		if ticket:
			asyncio.create_task(
				_silent_typing(client, token, peer, ticket, 1)
			)
		res = await client.sendmessage(
			token, to_user_id=peer, context_token=ctx, items=items, timeout=12.0
		)
		if ticket:
			asyncio.create_task(
				_silent_typing(client, token, peer, ticket, 2)
			)
		if not rpc_ok(res):
			raise RuntimeError(res.get("errmsg") or f"sendmessage failed: {res}")

	async def stop(self) -> None:
		self._stop_event().set()
		task = self._loop_task
		self._loop_task = None
		if task is not None:
			task.cancel()
			try:
				await task
			except (asyncio.CancelledError, Exception):
				pass
		if self._client is not None:
			await self._client.aclose()
			self._client = None
		self._token = ""
		self._buf = ""
		self._typing.clear()
		self.peer_id = ""
		self.context_token = ""
		self._set_qr(None)
		self.state = "stopped"
		self.error = None
		self.hint = None
		self._on_inbound = None
		self.last_poll_ret = None
		self.last_poll_msgs = 0
		self.last_poll_error = None
		self.poll_ok_at = 0.0
		self.poll_started_at = 0.0
		self.poll_timeouts = 0
		self.hold_ms = 35_000
		self.last_inbound = None


__all__ = ["ILinkBridge", "_silent_typing"]