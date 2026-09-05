"""L1.3 错误人话：friendly_error / provider_error_message 映射。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.error import URLError

from common.errors import (
	NetworkError,
	ProviderError,
	friendly_error,
	provider_error_message,
	sanitize_agent_prose,
	sanitize_user_facing_text,
)


def test_provider_401_429_are_human():
	assert "API Key" in provider_error_message(401)
	assert "429" in provider_error_message(429)
	assert "余额" in provider_error_message(402)
	assert "权限" in provider_error_message(403)
	assert "模型不存在" in provider_error_message(404)
	assert "稍后重试" in provider_error_message(500)
	assert "504" in provider_error_message(504)


def test_html_gateway_timeout_is_sanitized():
	html = "<html><head><title>504 Gateway Time-out</title></head><body><h1>504 Gateway Time-out</h1></body></html>"
	msg = provider_error_message(504, html)
	assert "504" in msg
	assert "<html" not in msg
	assert "网关超时" in sanitize_user_facing_text(html)
	assert "504" in friendly_error(ProviderError(html, status_code=504))
	assert "504" in friendly_error(RuntimeError(f"error: {html}"))


def test_provider_error_exception_carries_status():
	e = ProviderError('{"error": "bad key"}', status_code=401)
	msg = friendly_error(e)
	assert "401" in msg and "API Key" in msg


def test_unknown_status_falls_back():
	msg = provider_error_message(418, "teapot")
	assert "418" in msg and "teapot" in msg


def test_network_error_is_human():
	assert "网络" in friendly_error(NetworkError("timed out"))
	assert "网络" in friendly_error(URLError("conn refused"))


def test_rg_missing_is_human():
	msg = friendly_error(RuntimeError("tool running error,check ripgrep"))
	assert "rg" in msg and "ripgrep" in msg


def test_busy_is_human():
	assert "正忙" in friendly_error(RuntimeError("session busy"))


def test_wechat_disconnect_is_human():
	msg = friendly_error(RuntimeError("Target page, context or browser has been closed"))
	assert "微信" in msg


def test_wechat_launch_failure_is_human():
	msg = friendly_error(RuntimeError("unable to launch browser (chromium: timeout)"))
	assert "微信" in msg and "启动" in msg


def test_unknown_error_keeps_text():
	assert friendly_error(RuntimeError("boom")) == "boom"
	assert friendly_error(ValueError("boom")) == "boom"


def test_sanitize_agent_prose_keeps_multiline():
	text = "第一行\n第二行\nMEMORY_CANDIDATE: Wave6 live 验证"
	out = sanitize_agent_prose(text, limit=4096)
	assert "第一行" in out and "第二行" in out and "MEMORY_CANDIDATE" in out


def test_sanitize_agent_prose_html_still_sanitized():
	html = "<html><head><title>504 Gateway Time-out</title></head></html>"
	out = sanitize_agent_prose(html, limit=4096)
	assert "504" in out
	assert "<html" not in out
