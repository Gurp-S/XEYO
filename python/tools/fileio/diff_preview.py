"""带长度上限的统一 diff 预览，用于聊天 UI。"""

from __future__ import annotations

import difflib
from pathlib import PurePosixPath

# 保持 SSE / 聊天载荷轻量，同时仍展示有用的 hunk。
MAX_DIFF_LINES = 80


def basename(path: str) -> str:
	norm = path.replace("\\", "/")
	return PurePosixPath(norm).name or path


def format_capped_unified_diff(
	old: str,
	new: str,
	*,
	file_path: str,
	max_lines: int = MAX_DIFF_LINES,
) -> str:
	"""返回统一 diff 正文（无围栏），超出上限时截断并附省略说明。"""
	a = old.splitlines(keepends=True)
	b = new.splitlines(keepends=True)
	name = basename(file_path)
	# 旧内容为空 → 创建；为可读性使用 /dev/null 风格头部。
	from_file = "/dev/null" if not old else f"a/{name}"
	to_file = f"b/{name}"
	lines = list(
		difflib.unified_diff(
			a,
			b,
			fromfile=from_file,
			tofile=to_file,
			lineterm="\n",
			n=3,
		)
	)
	if not lines:
		return ""
	# 聊天展示时统一为 \n。
	normed = [ln if ln.endswith("\n") else ln + "\n" for ln in lines]
	if len(normed) <= max_lines:
		return "".join(normed).rstrip("\n")
	kept = normed[:max_lines]
	omitted = len(normed) - max_lines
	kept.append(f"\n… [{omitted} more diff lines omitted]\n")
	return "".join(kept).rstrip("\n")


def append_diff_fence(message: str, diff_body: str) -> str:
	if not diff_body.strip():
		return message
	return f"{message}\n\n```diff\n{diff_body}\n```"
