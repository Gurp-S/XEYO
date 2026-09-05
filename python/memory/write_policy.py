"""Memory 写入内容门禁：模型不遵守时的工具层兜底。

禁止把目录树 / 一次性临时计划写成长期笔记。纯启发式，无 I/O、不调模型。
"""

from __future__ import annotations

import re

# tree / ls 风格：多行缩进 + 路径分隔或常见 tree 字符
_TREE_LINE = re.compile(
	r"^[\s|]*[├└│\-+`]{1,3}\s*\S+"
	r"|^(?:[|\\/\s]{0,8})(?:[A-Za-z]:\\|/)[^\n]{2,}",
	re.M,
)
_PATHISH_LINES = re.compile(
	r"^[\t ]{0,4}(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\s*$",
	re.M,
)
# 一次性计划 / 目录树意图（中英）
_EPHEMERAL = re.compile(
	r"("
	r"one[\s-]?off\s+plan|temporary\s+plan|today'?s?\s+(temp\s+)?plan|"
	r"directory\s+tree|folder\s+tree|repo\s+tree|project\s+tree|"
	r"临时计划|今日计划|今天的临时|目录树|文件夹树|当前目录树|"
	r"tree\s*/[fFaA]|`tree`|\btree\b.*\b/F\b"
	r")",
	re.I,
)


def refuse_reason(title: str = "", content: str = "") -> str | None:
	"""若不应写入长期记忆，返回拒绝原因；否则 None。"""
	title = (title or "").strip()
	content = (content or "").strip()
	blob = f"{title}\n{content}".strip()
	if not content:
		return None

	if _EPHEMERAL.search(blob):
		return (
			"refused: do not store directory trees or one-off/temporary plans; "
			"write only durable facts the user confirmed"
		)

	lines = [ln for ln in content.splitlines() if ln.strip()]
	if len(lines) >= 6:
		treeish = sum(1 for ln in lines if _TREE_LINE.search(ln) or _PATHISH_LINES.match(ln))
		if treeish >= 4 or (treeish >= 3 and treeish / len(lines) >= 0.4):
			return (
				"refused: content looks like a directory listing/tree; "
				"not a durable memory fact"
			)

	# 超长纯路径堆砌
	if len(content) >= 800 and content.count("/") + content.count("\\") >= 40:
		return "refused: content looks like a bulk path dump, not a durable fact"

	return None
