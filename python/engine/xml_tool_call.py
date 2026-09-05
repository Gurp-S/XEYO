"""从模型纯文本中回收 XML 风格 tool_call（部分厂商/模型会这么吐）。

常见形态（glm 等）::

    <tool_call>Read
    <arg_key>file_path</arg_key>
    <arg_value>/path/to/file</arg_value>
    <arg_key>limit</arg_key>
    <arg_value>20</arg_value>
    </tool_call>

解析成功后从原文剥离，交给 query_loop 当正规 tool_use 执行。
流式：``XmlToolCallBuffer.feed`` 在 ``</tool_call>`` 闭合时立刻吐出 ToolUse。
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from msgtypes.message import ToolUse

_TOOL_CALL_RE = re.compile(
	r"<tool_call>\s*([A-Za-z_][\w.-]*)\s*(.*?)</tool_call>",
	re.DOTALL | re.IGNORECASE,
)
_ARG_RE = re.compile(
	r"<arg_key>\s*([^<]+?)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>",
	re.DOTALL | re.IGNORECASE,
)


def looks_like_raw_tool_markup(text: str) -> bool:
	"""结论文本是否基本是未执行的 XML tool_call（不应当摘要展示）。"""
	s = (text or "").strip()
	if not s:
		return False
	low = s.lower()
	if "<tool_call>" in low and "</tool_call>" in low:
		# 去掉 tool_call 块后几乎无正文 → 视为纯 markup
		stripped = _TOOL_CALL_RE.sub("", s).strip()
		return len(stripped) < 24
	return False


def _parse_tool_call_match(match: re.Match[str]) -> ToolUse | None:
	name = (match.group(1) or "").strip()
	body = match.group(2) or ""
	if not name:
		return None
	args: dict[str, Any] = {}
	for am in _ARG_RE.finditer(body):
		key = (am.group(1) or "").strip()
		val = (am.group(2) or "").strip()
		if not key:
			continue
		args[key] = _coerce_arg(val)
	return ToolUse(
		id=f"call_{uuid4().hex[:16]}",
		name=name,
		input=args,
	)


def extract_xml_tool_calls(text: str) -> tuple[list[ToolUse], str]:
	"""从纯文本抽出 XML tool_call；返回 (tool_uses, 清理后文本)。

	无匹配时返回 ``([], 原文)``。
	"""
	raw = text or ""
	if "<tool_call>" not in raw.lower():
		return [], raw

	uses: list[ToolUse] = []

	def _repl(match: re.Match[str]) -> str:
		tu = _parse_tool_call_match(match)
		if tu is None:
			return match.group(0)
		uses.append(tu)
		return ""

	cleaned = _TOOL_CALL_RE.sub(_repl, raw)
	cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
	if not uses:
		return [], raw
	return uses, cleaned


class XmlToolCallBuffer:
	"""流式缓冲：每闭合一个 ``</tool_call>`` 就吐出对应 ToolUse。"""

	__slots__ = ("_buf",)

	def __init__(self) -> None:
		self._buf = ""

	def feed(self, delta: str) -> list[ToolUse]:
		if not delta:
			return []
		self._buf += delta
		if "</tool_call>" not in self._buf.lower():
			return []
		uses: list[ToolUse] = []
		while True:
			m = _TOOL_CALL_RE.search(self._buf)
			if not m:
				break
			tu = _parse_tool_call_match(m)
			if tu is not None:
				uses.append(tu)
			self._buf = self._buf[: m.start()] + self._buf[m.end() :]
		return uses

	@property
	def buffer(self) -> str:
		return self._buf

	def take_remainder(self) -> str:
		out = self._buf
		self._buf = ""
		return out


def _coerce_arg(val: str) -> Any:
	s = (val or "").strip()
	if not s:
		return ""
	low = s.lower()
	if low == "true":
		return True
	if low == "false":
		return False
	if low in ("null", "none"):
		return None
	try:
		if s.startswith("-") or s.isdigit():
			return int(s)
	except ValueError:
		pass
	try:
		if "." in s:
			return float(s)
	except ValueError:
		pass
	return s


__all__ = [
	"XmlToolCallBuffer",
	"extract_xml_tool_calls",
	"looks_like_raw_tool_markup",
]
