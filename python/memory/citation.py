"""citation — 记忆引用锚点（Codex ``memories/read/src/citations.rs`` 落地）。

Codex 用 ``path:line_start-line_end|note=[...]`` + ``<rollout_ids>`` 给记忆条目加
可追溯引用：一条事实能定位到它来自哪个文件、哪几行、以及哪个 rollout(thread/session)。
XEYO 借鉴同一格式（只读/纯函数，无 I/O），把「压缩摘要行 → 原消息」和
「检索命中 → 原 note 文件行」都变成可定位的引用：

- ``CitationEntry``：path / line_start / line_end / note。单行格式
  ``path:start-end|note=[note]``（对齐 Codex ``parse_memory_citation_entry``）。
- ``CitationBlock``：entries + rollout_ids。块格式
  ``<citation_entries>...</citation_entries>`` + ``<rollout_ids>...</rollout_ids>``。

红线：本模块不写任何文件，不改变索引/JSONL；只生成用于展示与追溯的引用文本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CitationEntry:
	"""一条引用：路径 + 可选行号区间 + 短注释。"""

	path: str
	line_start: int | None = None
	line_end: int | None = None
	note: str = ""

	def __post_init__(self) -> None:
		if self.line_start is not None and self.line_end is not None:
			if self.line_end < self.line_start:
				object.__setattr__(self, "line_end", self.line_start)


@dataclass
class CitationBlock:
	"""一批引用 + 它的来源 rollout(session) id 列表。"""

	entries: list[CitationEntry] = field(default_factory=list)
	rollout_ids: list[str] = field(default_factory=list)

	def is_empty(self) -> bool:
		return not self.entries and not self.rollout_ids


# --------------------------------------------------------------------------- #
# 单行：path:start-end|note=[...] （对齐 Codex parse_memory_citation_entry）
# --------------------------------------------------------------------------- #


def entry_line(entry: CitationEntry) -> str:
	"""把一条引用编成 Codex 单行格式。"""
	path = entry.path.strip()
	if entry.line_start is not None and entry.line_end is not None:
		loc = f"{path}:{entry.line_start}-{entry.line_end}"
	elif entry.line_start is not None:
		loc = f"{path}:{entry.line_start}"
	else:
		loc = path
	note = (entry.note or "").strip()
	return f"{loc}|note=[{note}]" if note else loc


def parse_entry_line(line: str) -> CitationEntry | None:
	"""解析 Codex 单行引用；格式不合法返回 None（对齐 strict 失败的 fail-safe）。"""
	raw = (line or "").strip()
	if not raw:
		return None
	# split note 段（rsplit_once 只取最后一个 |note=[...]）
	idx = raw.rfind("|note=[")
	if idx >= 0:
		rest = raw[idx + len("|note=[") :]
		note = rest[:-1].strip() if rest.endswith("]") else ""
		loc = raw[:idx]
	else:
		note = ""
		loc = raw
	# split 行号段（rsplit_once ':' 取最后一个冒号，避免 Windows/path 冒号误切）
	cidx = loc.rfind(":")
	if cidx >= 0:
		path = loc[:cidx].strip()
		line_text = loc[cidx + 1 :].strip()
	else:
		path = loc.strip()
		line_text = ""
	ls = le = None
	if line_text:
		if "-" in line_text:
			a, _, b = line_text.partition("-")
			try:
				ls = int(a.strip())
				le = int(b.strip())
			except ValueError:
				ls = le = None
		else:
			try:
				ls = int(line_text)
			except ValueError:
				ls = None
	if not path:
		return None
	return CitationEntry(path=path, line_start=ls, line_end=le, note=note)


# --------------------------------------------------------------------------- #
# 块：<citation_entries>…</citation_entries> + <rollout_ids>…</rollout_ids>
# --------------------------------------------------------------------------- #


def render_block(block: CitationBlock) -> str:
	"""把一批引用编成模型可见的引用块（空块返回空串）。"""
	if block.is_empty():
		return ""
	parts: list[str] = []
	if block.entries:
		body = "\n".join(entry_line(e) for e in block.entries)
		parts.append(f"<citation_entries>\n{body}\n</citation_entries>")
	if block.rollout_ids:
		body = "\n".join(dict.fromkeys(str(i) for i in block.rollout_ids if i))
		parts.append(f"<rollout_ids>\n{body}\n</rollout_ids>")
	return "\n".join(parts)


def _extract_block(text: str, open_tag: str, close_tag: str) -> list[str]:
	"""取所有 ``open…close`` 之间内容（Codex extract_block 的多次命中版）。"""
	out: list[str] = []
	rest = text or ""
	while True:
		start = rest.find(open_tag)
		if start < 0:
			break
		body_start = start + len(open_tag)
		end = rest.find(close_tag, body_start)
		if end < 0:
			break
		out.append(rest[body_start:end])
		rest = rest[end + len(close_tag) :]
	return out


def parse_block(text: str) -> CitationBlock:
	"""解析引用块：合并多组 citation_entries / rollout_ids，去重 rollout id。"""
	block = CitationBlock()
	for body in _extract_block(text, "<citation_entries>", "</citation_entries>"):
		for line in body.splitlines():
			entry = parse_entry_line(line)
			if entry is not None:
				block.entries.append(entry)
	for tag in ("<rollout_ids>", "<thread_ids>"):
		for body in _extract_block(text, tag, tag.replace("<", "</").replace(">", ">")):
			for line in body.splitlines():
				sid = line.strip()
				if sid and sid not in block.rollout_ids:
					block.rollout_ids.append(sid)
	return block


# --------------------------------------------------------------------------- #
# XEYO 语义锚点：压缩行 / 检索命中
# --------------------------------------------------------------------------- #


def message_citation(index: int, kind: str = "") -> CitationEntry:
	"""压缩摘要行的引用锚：定位到被压缩消息（会话内第 index 条）。

	Codex 的 ``path:lines`` 是文件坐标；XEYO 压缩态的「文件坐标」即转录里的
	消息序号，因此用 ``notes:msg:<index>`` 作为 path。kind 进 note，便于人工辨认。
	"""
	kind = (kind or "msg").strip() or "msg"
	return CitationEntry(path=f"notes:msg:{int(index)}", note=kind)


def note_file_citation(
	file_path: str,
	*,
	line_start: int | None = None,
	line_end: int | None = None,
	note: str = "",
) -> CitationEntry:
	"""检索命中的引用锚：定位到 memdir note 文件（topics/<slug>.md）及内容行区间。"""
	return CitationEntry(
		path=file_path,
		line_start=line_start,
		line_end=line_end,
		note=note,
	)


def rollout_id_from_source(source: dict | None) -> str:
	"""从 Note.source 取 rollout(session) id；无则空串。"""
	if not isinstance(source, dict):
		return ""
	return str(source.get("session_id") or "").strip()


def block_for_entries(
	entries: Iterable[CitationEntry],
	*,
	rollout_ids: Iterable[str] = (),
) -> CitationBlock:
	"""组装块：去重 rollout id（保留首次顺序），过滤空。"""
	block = CitationBlock(entries=list(entries))
	for sid in rollout_ids:
		s = (sid or "").strip()
		if s and s not in block.rollout_ids:
			block.rollout_ids.append(s)
	return block
