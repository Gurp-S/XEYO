"""P0-2: usage 端点 base_url 的 SSRF 门。

背景：`/v1/models`、`/v1/usage`、`/v1/usage/balance` 接受 `X-Base-Url` 请求头，
此前**原样透传**——本机任意进程都能让服务端带着用户的 API key 请求任意地址
（凭据外泄 + 内网/metadata 探测）。

本测试锁定修复后的口径：
  ① 官方 preset 放行；
  ② 用户在设置里显式保存过的 base_url 放行（含本地推理环回地址）；
  ③ 私网 / 环回 / link-local / 云 metadata / 非法 scheme 一律拒绝。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from server.deps import (
	_is_user_configured_base_url,
	_iter_configured_base_urls,
	_resolve_base_url,
)


# ---------- ① 官方 preset ----------


def test_preset_base_url_allowed() -> None:
	"""不传 base_url 时回落到厂商 preset。"""
	assert _resolve_base_url("deepseek", None) == "https://api.deepseek.com/v1"


def test_official_base_url_allowed() -> None:
	"""显式传入官方地址等价于 preset，放行。"""
	got = _resolve_base_url("deepseek", "https://api.deepseek.com/v1")
	assert got == "https://api.deepseek.com/v1"


def test_openai_official_allowed() -> None:
	assert _resolve_base_url("openai", "https://api.openai.com/v1") == (
		"https://api.openai.com/v1"
	)


# ---------- ③ 危险地址必须拒绝 ----------


@pytest.mark.parametrize(
	("url", "reason_fragment"),
	[
		("http://169.254.169.254/", "private_ip"),
		("http://127.0.0.1:8080/v1", "private_ip"),
		("http://localhost:8080/v1", "private_host"),
		("http://192.168.1.1/v1", "private_ip"),
		("http://10.0.0.1/v1", "private_ip"),
		("http://[::1]:8080/v1", "private_ip"),
		("file:///etc/passwd", "scheme_not_allowed"),
		("gopher://example.com/", "scheme_not_allowed"),
	],
)
def test_dangerous_base_url_rejected(url: str, reason_fragment: str) -> None:
	with pytest.raises(HTTPException) as exc:
		_resolve_base_url("deepseek", url)
	assert exc.value.status_code == 403
	detail = exc.value.detail
	msg = detail.get("message") if isinstance(detail, dict) else str(detail)
	assert reason_fragment in msg, msg


def test_metadata_endpoint_rejected() -> None:
	"""云元数据探针是 SSRF 的经典目标，必须挡住。"""
	with pytest.raises(HTTPException) as exc:
		_resolve_base_url("deepseek", "http://metadata.google.internal/")
	assert exc.value.status_code == 403


# ---------- ② 用户显式配置过的地址放行 ----------


def test_configured_base_url_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""用户在 home 级 settings.json 里保存过的地址（含自建中转）放行。"""
	home = tmp_path / "home"
	(home / ".xeyo").mkdir(parents=True)
	(home / ".xeyo" / "settings.json").write_text(
		json.dumps({"providers": {"custom": {"base_url": "http://10.0.0.9:3000/v1"}}}),
		encoding="utf-8",
	)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.chdir(tmp_path)

	assert _is_user_configured_base_url("custom", "http://10.0.0.9:3000/v1")
	# 走完整解析链也应放行（用户在设置里显式授权过该地址）
	assert _resolve_base_url("custom", "http://10.0.0.9:3000/v1") == (
		"http://10.0.0.9:3000/v1"
	)


def test_unconfigured_private_url_still_rejected(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""没在设置里登记过的私网地址仍然拒绝——白名单不是"私网全放行"。"""
	home = tmp_path / "home"
	(home / ".xeyo").mkdir(parents=True)
	(home / ".xeyo" / "settings.json").write_text(
		json.dumps({"providers": {"custom": {"base_url": "http://10.0.0.9:3000/v1"}}}),
		encoding="utf-8",
	)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.chdir(tmp_path)

	with pytest.raises(HTTPException) as exc:
		_resolve_base_url("custom", "http://10.0.0.99:9999/v1")
	assert exc.value.status_code == 403


def test_local_provider_allowed_when_enabled(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""provider=local + 显式开启本地模型档时，环回地址放行（llama.cpp 场景）。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "empty-home"))
	monkeypatch.chdir(tmp_path)
	monkeypatch.setenv("XEYO_ALLOW_LOCAL_MODEL", "1")

	got = _resolve_base_url("local", "http://127.0.0.1:8080/v1")
	assert got == "http://127.0.0.1:8080/v1"


def test_local_provider_rejected_when_disabled(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""未开启本地模型档时，环回地址不放行。"""
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "empty-home"))
	monkeypatch.chdir(tmp_path)
	monkeypatch.delenv("XEYO_ALLOW_LOCAL_MODEL", raising=False)

	with pytest.raises(HTTPException):
		_resolve_base_url("local", "http://127.0.0.1:8080/v1")


# ---------- 设置树遍历 ----------


def test_iter_configured_base_urls_nested() -> None:
	"""递归收集：嵌套 dict / list 里的 base_url 都要被发现。"""
	raw = {
		"providers": {"a": {"base_url": "https://a.example.com/v1"}},
		"profiles": [
			{"base_url": "https://b.example.com/v1"},
			{"nested": {"base_url": "https://c.example.com/v1"}},
		],
	}
	found = set(_iter_configured_base_urls(raw))
	assert found == {
		"https://a.example.com/v1",
		"https://b.example.com/v1",
		"https://c.example.com/v1",
	}


def test_broken_settings_file_fails_closed(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""坏 JSON 视为"未配置"，不得因此放行任意地址（fail-closed）。"""
	home = tmp_path / "home"
	(home / ".xeyo").mkdir(parents=True)
	(home / ".xeyo" / "settings.json").write_text("{ not json", encoding="utf-8")
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.chdir(tmp_path)

	assert _is_user_configured_base_url("custom", "http://10.0.0.9:3000/v1") is False
