"""把本地文件发到当前已登录的微信远程通道（iLink）。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("xeyo.remote_deliver")

_IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_bg_sends: set[asyncio.Task[Any]] = set()


def looks_like_image(path: Path) -> bool:
	return path.suffix.lower() in _IMAGE_SUFFIX


def wechat_remote_ready() -> bool:
	"""已登录且未在关闭：可投递。失败当未就绪，不抛。"""
	try:
		from channels.ilink.service import get_bridge as il_bridge
		from channels.ilink.service import is_running as il_running

		if il_running():
			il = il_bridge()
			if il.state == "logged_in" and not il._stop.is_set():
				return True
		return False
	except Exception:
		return False


def schedule_send_remote_file(path: Path, *, as_image: bool | None = None) -> None:
	"""后台投递微信，不阻塞调用方（截图不要等 CDN）。"""

	async def _run() -> None:
		try:
			await send_remote_file(path, as_image=as_image)
		except Exception:
			log.warning("background WeChat send failed: %s", path, exc_info=True)

	try:
		loop = asyncio.get_running_loop()
	except RuntimeError:
		log.warning("no event loop; skip WeChat send of %s", path)
		return
	task = loop.create_task(_run())
	_bg_sends.add(task)
	task.add_done_callback(_bg_sends.discard)


async def send_remote_file(path: Path, *, as_image: bool | None = None) -> str:
	"""成功返回短说明；未登录、正在关闭或失败则抛错。"""
	p = path.expanduser()
	if not p.is_file():
		raise RuntimeError(f"file not found: {p}")
	want_image = looks_like_image(p) if as_image is None else as_image

	from channels.ilink.service import get_bridge as il_bridge
	from channels.ilink.service import is_running as il_running

	if il_running():
		il = il_bridge()
		if il.state == "logged_in" and not il._stop.is_set():
			if want_image:
				await il.send_image(p)
				return f"sent image to WeChat (iLink): {p.name}"
			await il.send_file(p)
			return f"sent file to WeChat (iLink): {p.name}"

	raise RuntimeError("iLink is not logged in")
