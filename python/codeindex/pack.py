"""同文件符号上下文包（ast-bro context / hermes capsule 精简版）。

围绕目标符号按字符预算装填：body → docstring → used imports →
同文件 callee 签名 → 同文件 caller 签名（approximate）。
零跨文件、零调用图。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from codeindex.symbols import Symbol, outline

DEFAULT_BUDGET_CHARS = 8_000


@dataclass(frozen=True)
class PackResult:
	text: str
	truncated: bool
	sections: tuple[str, ...]


def pack_symbol_context(
	path: str,
	*,
	target: Symbol,
	source_lines: list[str],
	budget: int = DEFAULT_BUDGET_CHARS,
) -> PackResult:
	"""组装给模型看的 pack 文本（不含行号；Read 侧再 add_line_numbers）。"""
	symbols = outline(path)
	body_lines = source_lines[target.start - 1 : target.end]
	body = "\n".join(body_lines)

	sections: list[tuple[str, str]] = []
	sections.append(("body", body))

	doc = _extract_docstring_or_jsdoc(source_lines, target)
	if doc:
		sections.append(("doc", doc))

	imports = _used_imports(source_lines, body)
	if imports:
		sections.append(("imports", "\n".join(imports)))

	callees = _same_file_callees(symbols, target, body)
	if callees:
		sections.append((
			"callees",
			"\n".join(f"{s.kind} { _qual(s) }: {s.signature}" for s in callees),
		))

	callers = _same_file_callers(symbols, target, source_lines)
	if callers:
		sections.append((
			"callers (approximate)",
			"\n".join(f"{s.kind} { _qual(s) }: {s.signature}" for s in callers),
		))

	parts: list[str] = []
	used = 0
	truncated = False
	kept_names: list[str] = []
	for name, content in sections:
		block = f"## {name}\n{content}"
		# body 必须尽量放进；其它段超预算则截断
		if name != "body" and used + len(block) + 2 > budget:
			truncated = True
			break
		if name == "body" and len(block) > budget:
			# 极端：body 本身超预算 → 截 body
			keep = max(0, budget - len(f"## body\n") - 20)
			content = content[:keep] + "\n…[truncated]"
			block = f"## body\n{content}"
			truncated = True
			parts.append(block)
			kept_names.append(name)
			used += len(block)
			break
		parts.append(block)
		kept_names.append(name)
		used += len(block) + 2

	header = (
		f"# pack {target.kind} {_qual(target)} "
		f"lines {target.start}-{target.end}"
		+ (" truncated" if truncated else "")
	)
	text = header + "\n\n" + "\n\n".join(parts)
	return PackResult(text=text, truncated=truncated, sections=tuple(kept_names))


def _qual(s: Symbol) -> str:
	return f"{s.parent}.{s.name}" if s.parent else s.name


def _extract_docstring_or_jsdoc(lines: list[str], target: Symbol) -> str:
	"""目标符号体内开头 docstring，或符号正上方 JSDoc/块注释。"""
	body = lines[target.start - 1 : target.end]
	joined = "\n".join(body)
	# Python """ / '''
	m = re.search(r'(?s)^\s*(?:async\s+)?(?:def|class)\b[^\n]*:\n\s*("""|\'\'\')(.*?)\1', joined)
	if m:
		doc = m.group(2).strip()
		if doc:
			return doc[:1_500]
	# 函数体第一语句是字符串字面量（简化）
	for ln in body[1:6]:
		sm = re.match(r'^\s*("""|\'\'\')(.*)$', ln)
		if sm:
			# 单行 docstring
			rest = sm.group(2)
			if rest.endswith(sm.group(1)):
				return rest[: -len(sm.group(1))].strip()[:1_500]
			break

	# 上方 JSDoc
	i = target.start - 2  # 0-indexed line above
	block: list[str] = []
	while i >= 0:
		ln = lines[i]
		if re.match(r"^\s*/\*\*", ln) or re.match(r"^\s*\*", ln) or re.match(r"^\s*\*/", ln):
			block.append(ln)
			i -= 1
			continue
		if re.match(r"^\s*//", ln):
			block.append(ln)
			i -= 1
			continue
		break
	if block:
		block.reverse()
		return "\n".join(block)[:1_500]
	return ""


def _used_imports(lines: list[str], body: str) -> list[str]:
	"""文件头 import 行中，名字在 body 里出现过的。"""
	import_lines: list[str] = []
	for ln in lines[:120]:
		s = ln.strip()
		if s.startswith(("import ", "from ", "export ")) or "require(" in s:
			import_lines.append(ln.rstrip())
		elif import_lines and not s:
			continue
		elif import_lines and not (
			s.startswith(("import ", "from ", "export ")) or s.endswith("\\") or s.startswith("{")
		):
			# 已过 import 区
			if not s.startswith("#") and not s.startswith("//"):
				break

	used: list[str] = []
	for ln in import_lines:
		names = _import_names(ln)
		if any(n and re.search(rf"\b{re.escape(n)}\b", body) for n in names):
			used.append(ln.strip())
	return used[:40]


def _import_names(line: str) -> list[str]:
	s = line.strip()
	names: list[str] = []
	# from x import a, b as c
	m = re.match(r"^from\s+\S+\s+import\s+(.+)$", s)
	if m:
		for part in m.group(1).split(","):
			part = part.strip()
			if not part or part.startswith("("):
				continue
			if " as " in part:
				names.append(part.split(" as ")[-1].strip())
			else:
				names.append(part.split(".")[0].strip())
		return names
	# import a, b as c
	m = re.match(r"^import\s+(.+)$", s)
	if m:
		for part in m.group(1).split(","):
			part = part.strip()
			if " as " in part:
				names.append(part.split(" as ")[-1].strip())
			else:
				names.append(part.split(".")[0].strip())
		return names
	# const {a} = require / import {a} from
	for n in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", s):
		if n not in {"import", "from", "export", "type", "as", "require", "const", "let", "var"}:
			names.append(n)
	return names


def _same_file_callees(
	symbols: tuple[Symbol, ...] | list[Symbol],
	target: Symbol,
	body: str,
) -> list[Symbol]:
	out: list[Symbol] = []
	for s in symbols:
		if s is target or (s.start == target.start and s.name == target.name and s.parent == target.parent):
			continue
		# 只看非容器内嵌方法时：名字出现在 body 且像调用
		if re.search(rf"\b{re.escape(s.name)}\s*\(", body):
			out.append(s)
	# 去重保序，最多 12
	seen: set[tuple] = set()
	uniq: list[Symbol] = []
	for s in out:
		key = (s.kind, s.name, s.parent, s.start)
		if key in seen:
			continue
		seen.add(key)
		uniq.append(s)
		if len(uniq) >= 12:
			break
	return uniq


def _same_file_callers(
	symbols: tuple[Symbol, ...] | list[Symbol],
	target: Symbol,
	source_lines: list[str],
) -> list[Symbol]:
	"""其它符号体里出现本符号名 → approximate callers。"""
	out: list[Symbol] = []
	name = target.name
	pat = re.compile(rf"\b{re.escape(name)}\s*\(")
	for s in symbols:
		if s.start == target.start and s.end == target.end and s.name == target.name:
			continue
		# 跳过目标的父容器本身（类体包含方法，必然命中）
		if target.parent and s.name == target.parent and s.kind in {"class", "interface"}:
			continue
		chunk = "\n".join(source_lines[s.start - 1 : s.end])
		if pat.search(chunk):
			out.append(s)
		if len(out) >= 12:
			break
	return out
