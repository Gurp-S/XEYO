"""P3-13/14/12: Bash 权限门禁接入、local provider 环境门禁、CORS 收窄。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from server.app import app
from tools.bash_tool.bash_tool import BashInput, BashTool


def test_bash_check_permissions_allows_benign(monkeypatch):
	"""T26 后出厂默认 bash=ask：工具级 check 在 preapproved 时放行，
	否则交回 registry 三态（不再自行 ALLOW）。"""
	from permissions.filesystem import mark_permission_preapproved

	t = BashTool(cwd=".")
	with mark_permission_preapproved(True):
		assert t.check_permissions(BashInput(command="echo hi")) is True


def test_bash_check_permissions_denies_blacklist():
	t = BashTool(cwd=".")
	assert t.check_permissions(BashInput(command="shutdown /s")) is False
	assert t.check_permissions(BashInput(command="shutdown -h now")) is False
	assert t.check_permissions(BashInput(command="rm -rf /")) is False
	assert t.check_permissions(BashInput(command="format c:")) is False


def _client() -> TestClient:
	return TestClient(app)


def test_local_provider_disabled_by_default(monkeypatch):
	monkeypatch.delenv("XEYO_ALLOW_LOCAL_MODEL", raising=False)
	c = _client()
	r = c.post(
		"/v1/chat/completions",
		json={
			"model": "llama",
			"messages": [{"role": "user", "content": "hi"}],
			"stream": False,
			"provider": "local",
		},
	)
	assert r.status_code == 400, r.text
	assert "unsupported provider" in r.json()["error"]["message"]


def test_local_provider_enabled_opt_in(monkeypatch):
	monkeypatch.setenv("XEYO_ALLOW_LOCAL_MODEL", "1")
	c = _client()
	# 开启后免 key 放行鉴权；连接不可达地址 → 502 模型错误（证明已通过门禁）。
	r = c.post(
		"/v1/chat/completions",
		json={
			"model": "llama",
			"messages": [{"role": "user", "content": "hi"}],
			"stream": False,
			"provider": "local",
			"base_url": "http://127.0.0.1:9/v1",
			"session_id": "gate-test-local",
		},
	)
	assert r.status_code in (502, 500), r.text


def test_side_chat_local_provider_disabled(monkeypatch):
	"""侧聊已并入主链路（body.side）；local 门禁在主路由同样拦截。"""
	monkeypatch.delenv("XEYO_ALLOW_LOCAL_MODEL", raising=False)
	c = _client()
	r = c.post(
		"/v1/chat/completions",
		headers={"X-Provider": "local"},
		json={
			"model": "llama",
			"messages": [{"role": "user", "content": "hi"}],
			"stream": False,
			"provider": "local",
			"side": True,
		},
	)
	assert r.status_code == 400, r.text


def test_cors_blocks_unknown_origin():
	c = _client()
	r = c.options(
		"/health",
		headers={
			"Origin": "http://evil.example",
			"Access-Control-Request-Method": "GET",
		},
	)
	assert r.headers.get("access-control-allow-origin") is None


def test_cors_allows_local_dev_origin():
	c = _client()
	r = c.options(
		"/health",
		headers={
			"Origin": "http://localhost:5173",
			"Access-Control-Request-Method": "GET",
		},
	)
	assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_env_override(monkeypatch):
	monkeypatch.setenv("XEYO_CORS_ORIGINS", "https://my.example")
	import importlib

	from server import app as app_mod

	importlib.reload(app_mod)
	try:
		c = TestClient(app_mod.app)
		r = c.options(
			"/health",
			headers={
				"Origin": "https://my.example",
				"Access-Control-Request-Method": "GET",
			},
		)
		assert r.headers.get("access-control-allow-origin") == "https://my.example"
	finally:
		importlib.reload(app_mod)


@pytest.fixture(autouse=True)
def _no_local_env(monkeypatch):
	monkeypatch.delenv("XEYO_ALLOW_LOCAL_MODEL", raising=False)
	yield