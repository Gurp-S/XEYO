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
	monkeypatch.setenv("XEYO_ALLOW_LAN", "1")

	def fake_main():
		raise RuntimeError("reached server")

	monkeypatch.setattr("cli.serve_cmd.os.environ.setdefault", lambda k, v: None)
	import cli.serve_cmd as m

	monkeypatch.setattr(m, "server_main", fake_main)  # type: ignore[attr-defined]
	with pytest.raises(RuntimeError, match="reached server"):
		run_serve(host="0.0.0.0", port=8113, cwd=str(tmp_path))
