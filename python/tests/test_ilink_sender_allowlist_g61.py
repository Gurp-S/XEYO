"""G61: ilink 发送者白名单——名单外微信用户不得驱动 bot / 执行远程命令。"""

from __future__ import annotations

import pytest

import channels.ilink.service as svc


def _msg(from_id: str, msg_type: int = 1) -> dict:
	return {
		"from_user_id": from_id,
		"message_type": msg_type,
		"item_list": [],
	}


def test_approval_helper_configured(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_CHANNEL_ALLOWED_USERS", "wxid_owner1, other@im.wechat")
	assert svc._is_approved_sender("wxid_owner1@im.wechat")
	assert svc._is_approved_sender("other@im.wechat")
	assert not svc._is_approved_sender("wxid_owner1@im.wechat".upper() + "x") or svc._is_approved_sender("WXID_OWNER1@im.wechat")
	assert not svc._is_approved_sender("stranger@im.wechat")
	assert not svc._is_approved_sender("")


def test_approval_helper_legacy_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_CHANNEL_ALLOWED_USERS", raising=False)
	monkeypatch.delenv("XEYO_ILINK_ALLOWED_USERS", raising=False)
	assert svc._is_approved_sender("anyone@im.wechat") is True


@pytest.mark.asyncio
async def test_unapproved_sender_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_CHANNEL_ALLOWED_USERS", "owner@im.wechat")
	seen: dict = {}
	monkeypatch.setattr(svc, "_note_inbound", lambda msg, **kw: seen.update(kw or {}))
	monkeypatch.setattr(svc, "_bridge", type("B", (), {})())

	def boom(*a, **k):
		raise AssertionError("unapproved sender reached agent/command path")

	monkeypatch.setattr(svc, "_push_event", boom)
	await svc._handle_user_msg(
		_msg("evil@im.wechat"), channel=None, runner=None  # type: ignore[arg-type]
	)
	assert seen.get("skip") == "sender_not_approved"


@pytest.mark.asyncio
async def test_approved_sender_passes_gate(monkeypatch: pytest.MonkeyPatch) -> None:
	"""owner 发来的消息能过白名单闸门,不会收到 sender_not_approved 拒绝。"""
	monkeypatch.setenv("XEYO_CHANNEL_ALLOWED_USERS", "owner@im.wechat")
	skips: list[str] = []
	monkeypatch.setattr(svc, "_note_inbound", lambda msg, **kw: skips.append(kw.get("skip", "")))
	monkeypatch.setattr(svc, "_is_approved_sender", lambda f: True)
	monkeypatch.setattr(svc, "_bridge", type("B", (), {}))
	assert svc._is_user_sender("owner@im.wechat") and svc._is_approved_sender("owner@im.wechat")
