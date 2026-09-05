"""微信 ClawBot / iLink 官方 Bot HTTP 通道（私聊文本 + 图片/文件）。"""

from __future__ import annotations

SESSION_ID = "ilink:default"
ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
CHANNEL_VERSION = "2.4.3"
BOT_AGENT = "XEYO/0.1"
# 2.4.3 → (2 << 16) | (4 << 8) | 3
APP_CLIENT_VERSION = "132099"


def session_id_for(from_user_id: str | None) -> str:
	"""微信 userId → 会话键。空则回退 ``ilink:default``。"""
	uid = (from_user_id or "").strip()
	if not uid:
		return SESSION_ID
	if uid.startswith("ilink:"):
		return uid
	return f"ilink:{uid}"


__all__ = [
	"SESSION_ID",
	"ILINK_BASE_URL",
	"CDN_BASE_URL",
	"CHANNEL_VERSION",
	"BOT_AGENT",
	"APP_CLIENT_VERSION",
	"session_id_for",
]
