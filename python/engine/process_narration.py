"""过程旁白：工作中可展示，工具轮落盘时剥掉（完成后不留痕迹）。

流式：旁白照常 yield，agent 进行中 UI 能看到「让我看看…」。
落盘：本轮有 tool_use 时 strip，transcript / 刷新后不再出现。
"""

from __future__ import annotations

import re

# 整句/整段过程旁白（中英）。允许末尾冒号、省略号、句号。
_NARRATION_LINE = re.compile(
	r"""
	^\s*
	(?:(?:好的|嗯|哦|行|可以|OK|Alright)[，,。!\s]*)?
	(?:
		让我(?:来|先|再|重新)?(?:仔细)?
		(?:看(?:看|一下|下)?|查看|检查|搜索|搜一下|找(?:一下)?|
			读(?:取|一下)?|打开|确认|分析|试试|试着|处理|改(?:一下)?|
			写|运行|执行|浏览|翻看|排查|定位|理解|梳理|总结|调研)
		|
		我(?:来|先|再)(?:仔细)?
		(?:看(?:看|一下|下)?|查看|检查|搜索|搜一下|找(?:一下)?|
			读(?:取|一下)?|打开|确认|分析|试试|处理|排查|定位)
		|
		(?:接下来|现在)(?:我)?(?:来|先)?(?:看|查|搜|读|打开|检查|分析|处理)
		|
		(?:Let\s+me|I(?:'ll| will)|I(?:'m| am)\s+going\s+to)\s+
		(?:just\s+)?(?:look|check|search|read|open|try|run|examine|
			inspect|find|see|review|verify|dig|explore|scan|investigate)
		\b
	)
	.{0,160}?
	[。．\.！!？?\s…:：]*
	$
	""",
	re.IGNORECASE | re.VERBOSE,
)


# 尚未成句时的旁白前缀（用于流式暂存判定）。
_NARRATION_OPENER = re.compile(
	r"""
	^\s*
	(?:(?:好的|嗯|哦|行|可以|OK|Alright)[，,。!\s]*)?
	(?:
		我来帮你|
		让我|
		我先|
		现在让我|
		接下来我?来?|
		Let\s+me\b|
		I(?:'ll| will)\b|
		I(?:'m| am)\s+going\s+to\b
	)
	""",
	re.IGNORECASE | re.VERBOSE,
)


def is_process_narration(text: str) -> bool:
	"""整段是否只是过程旁白（可含多行，每行都是旁白或空行）。"""
	raw = str(text or "").strip()
	if not raw:
		return False
	if (
		raw.startswith("#")
		or "文件位置" in raw
		or "代码行数" in raw
		or len(raw) > 280
	):
		return False
	if _NARRATION_OPENER.match(raw):
		return True
	parts = re.split(r"\n+", raw)
	saw = False
	for part in parts:
		line = part.strip()
		if not line:
			continue
		if not _NARRATION_LINE.match(line):
			return False
		saw = True
	return saw


def split_process_narration(text: str) -> tuple[str, str]:
	"""拆出 (正文, 旁白)——T28：旁白不再丢弃，落盘时带 background-only 标注。"""
	raw = str(text or "")
	if not raw.strip():
		return "", ""
	out: list[str] = []
	narration: list[str] = []
	for part in re.split(r"(\n+)", raw):
		if not part:
			continue
		if part[0] == "\n":
			if out and not out[-1].endswith("\n"):
				out.append(part)
			elif out:
				out.append(part)
			if narration and not narration[-1].endswith("\n"):
				narration.append(part)
			continue
		if is_process_narration(part.strip()):
			narration.append(part)
			continue
		out.append(part)
	cleaned = re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()
	narr = re.sub(r"\n{3,}", "\n\n", "".join(narration)).strip()
	return cleaned, narr


def strip_process_narration(text: str) -> str:
	"""去掉过程旁白行，保留其余正文。"""
	return split_process_narration(text)[0]


class StreamNarrationGate:
	"""流式直通；finish(has_tools=True) 时拆出旁白供落盘标注（T28）。"""

	__slots__ = ("parts", "narration")

	def __init__(self) -> None:
		self.parts: list[str] = []
		self.narration: str = ""

	def on_delta(self, text: str) -> list[str]:
		piece = str(text or "")
		if not piece:
			return []
		self.parts.append(piece)
		return [piece]

	def on_tool_use(self) -> None:
		return

	def finish(self, *, has_tools: bool) -> tuple[str, list[str]]:
		joined = "".join(self.parts)
		if has_tools:
			body, narr = split_process_narration(joined)
			self.narration = narr
			return body, []
		self.narration = ""
		return joined, []

	def drain_narration(self) -> str:
		"""取走本轮旁白（T28：调用方随 assistant 消息落盘标注）。"""
		n = self.narration
		self.narration = ""
		return n
