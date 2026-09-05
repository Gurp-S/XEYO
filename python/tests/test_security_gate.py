"""T33 安全边界测试：chat/sessions/rewind 仅 loopback；通道 loopback-or-token。

审计基线（ship blocker）：此前 chat/sessions/rewind 不设闸，LAN 或 0.0.0.0 暴露
可直接驱动 Agent / 改写 transcript；filehelper/ilink 管理面完全开放。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import app

# 非 loopback 测试地址（TEST-NET-3，保留作文档示例）。
_LAN = ("203.0.113.7", 55555)


def _lan_client() -> TestClient:
	return TestClient(app, client=_LAN)


def _local_client() -> TestClient:
	return TestClient(app)


# ---------- 数据面（chat / sessions / rewind）：LAN 一律 403 ----------


def test_sessions_list_rejected_from_lan() -> None:
	with _lan_client() as c:
		assert c.get("/v1/sessions").status_code == 403


def test_sessions_list_allowed_from_loopback() -> None:
	with _local_client() as c:
		assert c.get("/v1/sessions").status_code == 200


def test_rewind_route_rejected_from_lan() -> None:
	with _lan_client() as c:
		r = c.get("/v1/sessions/some-sid/rewind")
		assert r.status_code == 403


def test_legacy_chat_rejected_from_lan() -> None:
	with _lan_client() as c:
		r = c.post("/api/chat", json={"sessionId": "s", "text": "hi"})
		assert r.status_code == 403


def test_legacy_chat_body_api_key_ignored() -> None:
	# T33：body 不再接受 api_key（密钥只走 Authorization header / env / config）。
	# 错误 Key 经 header 注入时 legacy 垫片会带上去——这里只验证 body 字段
	# 不再改变行为：无 header 时按无 Key 处理（本地测试 provider 占位逻辑之外）。
	with _local_client() as c:
		r = c.post(
			"/api/chat",
			json={"sessionId": "s", "text": "hi", "api_key": "sk-should-be-ignored"},
		)
		# 允许 4xx（无 Key 被拒）但绝不能把 body key 当有效凭证放行到上游成功流；
		# 具体状态码取决于 provider 校验，只要不是 200 全量成功流即可。
		assert r.status_code != 200 or "data:" not in r.text


def test_lan_allowed_with_remote_control_escape(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_ALLOW_REMOTE_CONTROL", "1")
	with _lan_client() as c:
		assert c.get("/v1/sessions").status_code == 200


# ---------- 通道管理面（filehelper/ilink）：loopback 或 token ----------


def test_filehelper_status_lan_without_token_rejected(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	monkeypatch.setenv("XEYO_REMOTE_TOKEN", "tok-123")
	with _lan_client() as c:
		assert c.get("/v1/filehelper/status").status_code == 401


def test_filehelper_status_lan_with_token_allowed(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	monkeypatch.setenv("XEYO_REMOTE_TOKEN", "tok-123")
	with _lan_client() as c:
		r = c.get("/v1/filehelper/status", headers={"X-Remote-Token": "tok-123"})
		assert r.status_code == 200


def test_filehelper_status_loopback_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_REMOTE_TOKEN", "tok-123")
	with _local_client() as c:
		assert c.get("/v1/filehelper/status").status_code == 200


def test_filehelper_lan_token_disabled_503(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_REMOTE_TOKEN", raising=False)
	with _lan_client() as c:
		assert c.get("/v1/filehelper/status").status_code == 503


def test_ilink_status_lan_without_token_rejected(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	monkeypatch.setenv("XEYO_REMOTE_TOKEN", "tok-123")
	with _lan_client() as c:
		assert c.get("/v1/ilink/status").status_code == 401
