"""xeyo serve — thin wrapper around `python -m server`."""

from __future__ import annotations

import os
from typing import NoReturn

from rich.console import Console

from cli.cwdutil import ensure_utf8_stdio, resolve_cwd

console = Console(stderr=True)


def run_serve(
	*,
	host: str | None = None,
	port: int | None = None,
	cwd: str | None = None,
) -> NoReturn:
	ensure_utf8_stdio()
	# 硬性守卫：绝不以 python/ 包根作为工作区启动。
	if cwd:
		os.environ["XEYO_CWD"] = resolve_cwd(cwd)
	else:
		os.environ["XEYO_CWD"] = resolve_cwd(None)
	if host:
		os.environ["XEYO_HTTP_HOST"] = host
	if port is not None:
		os.environ["XEYO_HTTP_PORT"] = str(port)
	# G106: 非 loopback 监听即裸奔到 LAN(无服务端鉴权中间件,Bearer 即供应商 key)。
	# 默认禁止;仅显式 XEYO_ALLOW_LAN=1 可放开(且应另配反向代理鉴权)。
	_http_host = (host or os.environ.get("XEYO_HTTP_HOST", "127.0.0.1")).strip().lower()
	_loopback_hosts = {"127.0.0.1", "::1", "localhost", "[::1]"}
	if _http_host not in _loopback_hosts and os.environ.get("XEYO_ALLOW_LAN", "").strip() != "1":
		console.print(
			f"[red]refusing to serve on non-loopback host '{_http_host}': "
			"server has no service-side credentials (Bearer doubles as provider key). "
			"Bind 127.0.0.1, or set XEYO_ALLOW_LAN=1 with an auth proxy.[/red]"
		)
		raise SystemExit(2)
	os.environ.setdefault("XEYO_REWIND_ENABLED", "1")
	h = os.environ.get("XEYO_HTTP_HOST", "127.0.0.1")
	p = os.environ.get("XEYO_HTTP_PORT", "8000")
	console.print(
		f"[dim]starting server http://{h}:{p} cwd={os.environ.get('XEYO_CWD')}[/dim]"
	)
	from server.__main__ import main as server_main

	server_main()
	raise SystemExit(0)
