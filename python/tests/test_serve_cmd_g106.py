"""G106: serve 拒绝非 loopback 绑定(无独立服务端凭据,禁止裸奔 LAN)。"""

from __future__ import annotations

import pytest

from cli.serve_cmd import run_serve


def test_serve_rejects_lan_host_without_flag(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
	monkeypatch.delenv("XEYO_ALLOW_LAN", raising=False)
	monkeypatch.delenv("XEYO_HTTP_HOST", raising=False)
	with pytest.raises(SystemExit) as ei:
		run_serve(host="0.0.0.0", port=8111, cwd=str(tmp_path))
	assert ei.value.code == 2


def test_serve_rejects_lan_env_host(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
	monkeypatch.delenv("XEYO_ALLOW_LAN", raising=False)
	monkeypatch.setenv("XEYO_HTTP_HOST", "0.0.0.0")
	with pytest.raises(SystemExit) as ei:
		run_serve(port=8112, cwd=str(tmp_path))
	assert ei.value.code == 2


def test_serve_allows_lan_with_explicit_flag(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
	"""G106 的正半段：显式 XEYO_ALLOW_LAN=1 时必须一路走到启动调用。

	旧写法 `monkeypatch.setattr(m, "server_main", …)` 永远打不中——`server_main` 是
	`run_serve` 内部的函数级 import（`from server.__main__ import main as server_main`），
	不是模块属性；要拦就得钉 `server.__main__.main` 本身。
	"""
	import server.__main__ as server_main_mod

	def fake_main() -> None:
		raise RuntimeError("reached server")

	monkeypatch.setenv("XEYO_ALLOW_LAN", "1")
	monkeypatch.setattr(server_main_mod, "main", fake_main)
	with pytest.raises(RuntimeError, match="reached server"):
		run_serve(host="0.0.0.0", port=8113, cwd=str(tmp_path))
