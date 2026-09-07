"""本机控制面门禁：权限确认 / 终端等敏感路由仅允许 localhost。"""

from __future__ import annotations

import os

from fastapi import Header, Request

from server.deps import api_error

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _client_host(request: Request) -> str:
	client = getattr(request, "client", None)
	host = getattr(client, "host", None) if client is not None else None
	return str(host or "").strip().lower()


def require_loopback(request: Request) -> None:
	"""非本机客户端拒绝。测试可用 XEYO_ALLOW_REMOTE_CONTROL=1 放开。"""
	if os.environ.get("XEYO_ALLOW_REMOTE_CONTROL", "").strip() == "1":
		return
	host = _client_host(request)
	if host in _LOOPBACK:
		return
	# 部分反向代理会把真实 peer 放在 X-Forwarded-For；默认仍拒——本地桌面不该经公网代理。
	raise api_error(
		403,
		"control endpoints are localhost-only",
		"permission_error",
	)




async def loopback_or_remote_token(
	request: Request,
	authorization: str | None = Header(default=None),
	x_remote_token: str | None = Header(default=None, alias="X-Remote-Token"),
) -> None:
	"""通道管理面门禁（T33）：本机放行；非本机须携带 XEYO_REMOTE_TOKEN。

	用于 filehelper/ilink 的 start/stop/qr/status/events——GUI 从 loopback
	轮询不受影响；LAN 直连（0.0.0.0 暴露）必须持 token。远程隧道场景流量
	经 cloudflared 落到 loopback，仍受隧道侧认证保护。
	"""
	if os.environ.get("XEYO_ALLOW_REMOTE_CONTROL", "").strip() == "1":
		return
	if _client_host(request) in _LOOPBACK:
		return
	from channels.auth import verify_remote_token

	try:
		verify_remote_token(authorization, x_remote_token)
	except ValueError as e:
		code = str(e)
		if code == "disabled":
			raise api_error(
				503,
				"remote channel disabled; set XEYO_REMOTE_TOKEN",
				"permission_error",
			) from e
		raise api_error(401, "invalid or missing remote token", "permission_error") from e
