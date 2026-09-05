"""入站消息去重：忽略历史、自己发出的回复，避免回声循环。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from channels.filehelper.prefix import REPLY_PREFIX, is_own_reply

# 文件传输助手聊天区里夹在气泡旁的时间/星期，不能当作用户指令。
_CHROME = re.compile(
	r"^(?:上午|下午|凌晨|早上|晚上)?\s*\d{1,2}:\d{2}$"
	r"|^\d{1,2}月\d{1,2}日(?:\s*(?:上午|下午|凌晨|早上|晚上)?\s*\d{1,2}:\d{2})?$"
	r"|^\d{4}年\d{1,2}月\d{1,2}日$"
	r"|^星期[一二三四五六日天]$"
	r"|^(?:昨天|刚刚|今天|周一|周二|周三|周四|周五|周六|周日)$"
)


def _norm(text: str) -> str:
	return " ".join((text or "").split())


# 微信「文件传输助手」内置欢迎语，不是用户指令。
_HELPER_SLOGAN = re.compile(
	r"使用文件传输助手.{0,20}互传文件|手机电脑轻松互传"
)


def _is_chrome(text: str) -> bool:
	t = (text or "").strip()
	if not t:
		return True
	return all(bool(_CHROME.match(ln.strip())) for ln in t.splitlines() if ln.strip())


def _is_helper_noise(text: str) -> bool:
	t = " ".join((text or "").split())
	if not t:
		return True
	if len(t) > 80:
		return False
	return _HELPER_SLOGAN.search(t) is not None


def _strip_chrome_lines(text: str) -> str:
	lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
	while lines and _CHROME.match(lines[0]):
		lines.pop(0)
	while lines and _CHROME.match(lines[-1]):
		lines.pop()
	return "\n".join(lines)


def peel_own_reply(text: str) -> str:
	"""去掉 [XEYO] 及其后的回声正文，留下可能的用户原文。"""
	lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
	if not lines:
		return ""
	for i, ln in enumerate(lines):
		if ln.startswith(REPLY_PREFIX):
			return _strip_chrome_lines("\n".join(lines[:i]))
	if (text or "").strip().startswith(REPLY_PREFIX):
		return ""
	return _strip_chrome_lines((text or "").strip())


class SeenIndex:
	def __init__(self) -> None:
		self._seen: set[str] = set()
		self._outbound: set[str] = set()

	def _mark(self, text: str, *, outbound: bool = False) -> None:
		t = (text or "").strip()
		if not t:
			return
		self._seen.add(t)
		n = _norm(t)
		if n:
			self._seen.add(n)
		if outbound:
			self._outbound.add(t)
			if n:
				self._outbound.add(n)

	def remember_outbound(self, text: str) -> None:
		t = (text or "").strip()
		if not t:
			return
		self._mark(t, outbound=True)
		self._mark(_norm(t), outbound=True)
		for line in t.splitlines():
			s = line.strip()
			if s:
				self._mark(s, outbound=True)

	def seed(self, texts: list[str]) -> None:
		for t in texts:
			self._mark((t or "").strip())

	def _is_echo(self, text: str) -> bool:
		t = (text or "").strip()
		if not t:
			return True
		if is_own_reply(t):
			return True
		n = _norm(t)
		if t in self._outbound or n in self._outbound:
			return True
		if t in self._seen or n in self._seen:
			return True
		if len(n) >= 12:
			for o in self._outbound:
				on = _norm(o)
				if len(on) >= 12 and (n in on or on in n):
					return True
		return False

	def take_inbound(self, texts: list[str]) -> list[str]:
		fresh: list[str] = []
		for raw in texts:
			t = (raw or "").strip()
			if not t:
				continue
			leftover = peel_own_reply(t)
			if leftover != t:
				self._mark(t, outbound=True)
			if not leftover or _is_chrome(leftover) or _is_helper_noise(leftover):
				self._mark(t)
				continue
			if self._is_echo(leftover):
				self._mark(leftover)
				continue
			self._mark(leftover)
			fresh.append(leftover)
		return fresh

	def save(self, path: Path) -> None:
		try:
			path.parent.mkdir(parents=True, exist_ok=True)
			data = {
				"seen": list(self._seen)[-600:],
				"outbound": list(self._outbound)[-240:],
			}
			path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
		except OSError:
			pass

	def load(self, path: Path) -> None:
		if not path.is_file():
			return
		try:
			raw = json.loads(path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			return
		if not isinstance(raw, dict):
			return
		for key, outbound in (("seen", False), ("outbound", True)):
			items = raw.get(key)
			if not isinstance(items, list):
				continue
			for item in items:
				if isinstance(item, str) and item.strip():
					self._mark(item.strip(), outbound=outbound)


def seen_store_path(profile: Path) -> Path:
	return profile / "seen_index.json"


def added_messages(old: str, new: str) -> list[str]:
	"""从聊天区 innerText 快照算出新增片段。首次（old 空）视为种子，不产出入站。"""
	old = old or ""
	new = new or ""
	if not old:
		return []
	if new == old:
		return []
	if new.startswith(old):
		delta = new[len(old) :].strip()
		return [delta] if delta else []
	old_lines = {x.strip() for x in old.splitlines() if x.strip()}
	return [x.strip() for x in new.splitlines() if x.strip() and x.strip() not in old_lines]
