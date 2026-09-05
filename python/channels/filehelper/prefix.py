"""XEYO 回复前缀。"""

from __future__ import annotations

REPLY_PREFIX = "[XEYO]"
REMOTE_PREFIX = "[远程]"


def xeyo_reply(text: str) -> str:
	t = (text or "").strip()
	if not t:
		return ""
	if t.startswith(REPLY_PREFIX):
		return t
	return f"{REPLY_PREFIX}\n{t}"


def is_own_reply(text: str) -> bool:
	"""微信会把我们发出的气泡再读回来；凡带 [XEYO] 前缀的都视为回声。"""
	t = (text or "").strip()
	if not t:
		return False
	if t.startswith(REPLY_PREFIX):
		return True
	return any(ln.strip().startswith(REPLY_PREFIX) for ln in t.splitlines())
