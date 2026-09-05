"""写门禁冲突归因：line-range 摘要 + 外部会话写入提示。

把"File has been modified since read"这种模糊拒绝，升级为两条可行动信息：
1. 你的快照与磁盘版本在哪些行有差异（让模型知道要先 re-read 哪些区域）；
2. 是否疑似被其他聊天会话写入（归因，有助于决定是重读重放还是直接放弃）。

本模块只做文本拼装，不触碰磁盘；跨会话归因数据来自 session_presence。
"""

from __future__ import annotations

import difflib
import time
from typing import Optional

from engine.session_presence import (
	default_session_presence,
	session_tree_root,
)


def line_range_summary(snapshot: str, current: str) -> str:
	"""返回快照 vs 磁盘的差异行范围摘要；无差异返回 ""。"""
	a = (snapshot or "").splitlines()
	b = (current or "").splitlines()
	matcher = difflib.SequenceMatcher(None, a, b)
	spans: list[str] = []
	for tag, i1, i2, j1, j2 in matcher.get_opcodes():
		if tag == "equal":
			continue
		# 用行号区间描述差异所在的"磁盘版本"行（模型将要 read 到的行）。
		if j1 == j2:
			span = f"line {j1 + 1}"
		else:
			span = f"lines {j1 + 1}-{j2}"
		if tag == "replace":
			spans.append(f"{span} (changed)")
		elif tag == "delete":
			spans.append(f"{span} (removed in disk)")
		else:  # insert
			spans.append(f"{span} (added on disk)")
	if not spans:
		return ""
	# 合并相邻并限幅，避免长 diff 刷屏。
	merged: list[str] = []
	for s in spans:
		if merged and merged[-1].split()[0] == s.split()[0]:
			merged[-1] = s
		else:
			merged.append(s)
	shown = merged[:6]
	suffix = "" if len(merged) <= 6 else f" (+{len(merged) - 6} more sections)"
	return "Your snapshot differs from disk at " + ", ".join(shown) + suffix + "."


def _time_hhmm(ts: float) -> str:
	try:
		return time.strftime("%H:%M", time.localtime(ts))
	except Exception:  # noqa: BLE001
		return ""


def external_attribution(
	cwd: str,
	abs_path: str,
	self_session_id: str,
	*,
	exclude_tree_roots: bool = True,
) -> str:
	"""若文件被**另一个会话树**最近写入，返回归因短语；否则 ""。"""
	sid = (self_session_id or "").strip()
	if not cwd or not abs_path or not sid:
		return ""
	try:
		reg = default_session_presence()
		owner = reg.owner_of(cwd, abs_path, exclude_session=sid)
	except Exception:  # noqa: BLE001
		return ""
	if owner is None:
		return ""
	if exclude_tree_roots and session_tree_root(owner.session_id) == session_tree_root(
		sid
	):
		# 同一会话树（含本会话子 agent）写入：不算外部，交旧提示兜底。
		return ""
	label = owner.title or owner.session_id[-8:]
	return (
		f" Suspicious: another session「{label}」wrote this file recently"
		f" ({_time_hhmm(next(iter(owner.owned_files.values()), 0))})."
	)


def build_stale_message(
	base: str,
	cwd: str,
	abs_path: str,
	self_session_id: str,
	snapshot: str,
	current: str,
) -> str:
	"""组装完整拒绝消息：base + 行范围摘要 + 外部归因 + 重放指令。"""
	parts = [base]
	line_hint = line_range_summary(snapshot, current)
	if line_hint:
		parts.append(line_hint)
	attr = external_attribution(cwd, abs_path, self_session_id)
	if attr:
		parts.append(attr.strip())
	parts.append("Read the file again, then re-apply your intended change onto the current content.")
	return "\n".join(parts)


__all__ = [
	"build_stale_message",
	"external_attribution",
	"line_range_summary",
]
