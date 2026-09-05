"""diff 行号 ∩ 符号大纲 → touched 列表（GitNexus detect_changes 精简版）。

零持久索引：复用 codeindex.outline 的按需哈希缓存。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from codeindex.symbols import CODE_EXTENSIONS, outline

MAX_FILES = 20
MAX_SYMBOLS = 80


@dataclass(frozen=True)
class TouchedSymbol:
	path: str
	kind: str
	name: str
	parent: str | None
	start: int
	end: int

	def label(self) -> str:
		qual = f"{self.parent}.{self.name}" if self.parent else self.name
		return f"{self.path}:{self.start} {self.kind} {qual}"


def symbols_touched_by_hunks(
	cwd: str,
	hunks_by_file: dict[str, list[tuple[int, int]]],
	*,
	max_files: int = MAX_FILES,
	max_symbols: int = MAX_SYMBOLS,
) -> list[TouchedSymbol]:
	"""hunks_by_file: rel_path → [(start_line, end_line), ...]（1-indexed, 含）。"""
	root = os.path.abspath(cwd)
	out: list[TouchedSymbol] = []
	seen: set[tuple[str, int, str]] = set()

	for i, (rel, ranges) in enumerate(hunks_by_file.items()):
		if i >= max_files or len(out) >= max_symbols:
			break
		ext = os.path.splitext(rel)[1].lower()
		if ext not in CODE_EXTENSIONS:
			continue
		abs_path = os.path.normpath(os.path.join(root, rel.replace("/", os.sep)))
		try:
			syms = outline(abs_path)
		except Exception:
			continue
		if not syms or not ranges:
			continue
		for s in syms:
			if len(out) >= max_symbols:
				break
			if not _overlaps(s.start, s.end, ranges):
				continue
			key = (rel, s.start, s.name)
			if key in seen:
				continue
			seen.add(key)
			out.append(
				TouchedSymbol(
					path=rel.replace("\\", "/"),
					kind=s.kind,
					name=s.name,
					parent=s.parent,
					start=s.start,
					end=s.end,
				)
			)
	return out


def _overlaps(start: int, end: int, ranges: Iterable[tuple[int, int]]) -> bool:
	for a, b in ranges:
		if a > b:
			a, b = b, a
		if not (end < a or start > b):
			return True
	return False


def format_touched_section(touched: list[TouchedSymbol], *, untracked: list[str] | None = None) -> str:
	lines = ["touched:"]
	if not touched and not untracked:
		return ""
	for t in touched:
		lines.append(f"  {t.label()}")
	if untracked:
		for p in untracked[:20]:
			lines.append(f"  {p} (untracked)")
		if len(untracked) > 20:
			lines.append(f"  … +{len(untracked) - 20} more untracked")
	return "\n".join(lines)
