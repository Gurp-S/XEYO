"""L1 指令记忆：XEYO.md 文件族。

后加载覆盖先加载。@include 深度 ≤ 5；环引用丢弃；缺文件静默。

热路径缓存：``load_instruction_text`` 按 (cwd, workspace_root) 缓存，
以「实际读取到的所有文件（含 @include 目标）的 (mtime_ns, size)」为失效签名。
compact（L5 cursor 前进）后调用 ``clear_instruction_cache()`` 强制重载。

frontmatter ``paths:``：仅当 glob 匹配当前 cwd（相对 workspace）时注入该段；
无 paths 的段落为常驻核心，优先占满字符预算。
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Iterable

INCLUDE_RE = re.compile(r"^@include\s+(\S+)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
MAX_CHARS = 40_000  # 硬顶安全阀
MAX_INCLUDE_DEPTH = 5
_DEFAULT_SOFT_CHARS = 8_000


def instruction_char_budget() -> int:
	"""常驻左段实际拼接预算（默认软上限 8k，省钱）；硬顶仍为 MAX_CHARS。"""
	raw = os.environ.get("XEYO_INSTRUCTION_BUDGET", "").strip()
	if raw:
		try:
			return max(256, min(MAX_CHARS, int(raw)))
		except ValueError:
			pass
	return min(MAX_CHARS, _DEFAULT_SOFT_CHARS)

	# 入参 (cwd, workspace_root, budget)，返回 (top_sig, full_sig, text)
_CACHE: dict[
	tuple[str, str, int],
	tuple[tuple[tuple[str, int, int], ...], tuple[tuple[str, int, int], ...], str],
] = {}


def clear_instruction_cache() -> None:
	"""清空 L1 指令缓存。compact 后、或指令文件被显式修改后调用。"""
	_CACHE.clear()


def instruction_cache_signature(cwd: str, workspace_root: str) -> tuple:
	"""对外暴露的缓存签名，供 PromptAssembler 会话级 memo。"""
	discovered = _discover_paths(cwd, workspace_root)
	return _signature(discovered)


def xeyo_home() -> Path:
	"""返回 ~/.xeyo（可用 XEYO_HOME 覆盖，供测试隔离）。"""
	override = os.environ.get("XEYO_HOME", "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo"


def split_paths_frontmatter(text: str) -> tuple[list[str] | None, str]:
	"""解析可选 YAML-ish frontmatter 的 paths。

	返回 ``(paths, body)``：
	- paths is None：无 frontmatter，body 为原文；
	- paths == []：有 frontmatter 但无 paths 键 → 视为常驻；
	- paths 非空：仅匹配时注入 body。
	"""
	raw = text or ""
	m = FRONTMATTER_RE.match(raw.lstrip("\ufeff"))
	if not m:
		return None, raw
	header, body = m.group(1), m.group(2)
	paths: list[str] = []
	in_paths = False
	for line in header.splitlines():
		stripped = line.strip()
		if not stripped or stripped.startswith("#"):
			continue
		if stripped.lower().startswith("paths:"):
			rest = stripped.split(":", 1)[1].strip()
			in_paths = True
			if rest.startswith("[") and rest.endswith("]"):
				inner = rest[1:-1].strip()
				if inner:
					paths.extend(
						p.strip().strip("'\"")
						for p in inner.split(",")
						if p.strip()
					)
			elif rest:
				paths.append(rest.strip().strip("'\""))
			continue
		if in_paths and (stripped.startswith("- ") or stripped.startswith("* ")):
			paths.append(stripped[2:].strip().strip("'\""))
			continue
		if ":" in stripped:
			in_paths = False
	return paths, body


def paths_match_cwd(paths: list[str], *, cwd: str, workspace_root: str) -> bool:
	"""paths glob 是否匹配当前工作目录（相对 workspace 根）。"""
	if not paths:
		return True
	try:
		focus = Path(cwd).expanduser().resolve()
		root = Path(workspace_root).expanduser().resolve()
	except OSError:
		return False
	try:
		rel = focus.relative_to(root).as_posix()
	except ValueError:
		rel = focus.name
	focus_posix = focus.as_posix()
	for g in paths:
		pat = (g or "").strip().replace("\\", "/")
		if not pat:
			continue
		if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(focus_posix, pat):
			return True
		if pat.endswith("/**"):
			prefix = pat[:-3].rstrip("/")
			if not prefix or rel == prefix or rel.startswith(prefix + "/"):
				return True
		if pat.endswith("/**/*"):
			prefix = pat[:-5].rstrip("/")
			if not prefix or rel == prefix or rel.startswith(prefix + "/"):
				return True
	return False


def _filter_instruction_chunk(
	text: str, *, cwd: str, workspace_root: str
) -> tuple[str, bool]:
	"""返回 (正文, is_path_scoped)。不匹配的 path-scoped 段返回空串。"""
	paths, body = split_paths_frontmatter(text)
	if paths is None:
		return text, False
	if paths_match_cwd(paths, cwd=cwd, workspace_root=workspace_root):
		return body.strip(), bool(paths)
	return "", True


def read_optional(
	path: Path,
	*,
	seen: set[str] | None = None,
	depth: int = 0,
	collect: set[Path] | None = None,
) -> list[str]:
	"""读单个指令文件；缺文件静默返回空列表。

	collect 非空时记录所有实际读取的文件（含 @include 目标），供缓存签名。
	"""
	try:
		if not path.is_file():
			return []
		text = path.read_text(encoding="utf-8")
	except OSError:
		return []
	if collect is not None:
		collect.add(path.resolve())
	text = text.strip()
	if not text:
		return []
	tracker = seen if seen is not None else set()
	tracker.add(str(path.resolve()))
	return [_expand_includes(text, path.parent, depth, tracker, collect)]


def join_with_caps(chunks: list[str], *, max_chars: int) -> str:
	"""拼接指令文本并截断到字符上限"""
	text = "\n\n".join(p.strip() for p in chunks if p and str(p).strip())
	if len(text) > max_chars:
		return text[:max_chars]
	return text


def read_glob(pattern: Path, *, collect: set[Path] | None = None) -> list[str]:
	"""按 glob 读取 rules 目录下的 md，缺目录则空"""
	parent = pattern.parent
	if not parent.is_dir():
		return []
	chunks: list[str] = []
	for path in sorted(parent.glob(pattern.name)):
		chunks.extend(read_optional(path, collect=collect))
	return chunks


def _expand_includes(
	text: str,
	base: Path,
	depth: int,
	seen: set[str],
	collect: set[Path] | None,
) -> str:
	"""展开 @include，深度封顶、环引用丢弃。"""
	if depth > MAX_INCLUDE_DEPTH:
		return text

	def repl(match: re.Match[str]) -> str:
		rel = match.group(1).strip().strip("\"'")
		target = (base / rel).resolve()
		key = str(target)
		if key in seen:
			return ""
		if not target.is_file():
			return ""
		seen.add(key)
		if collect is not None:
			collect.add(target)
		try:
			body = target.read_text(encoding="utf-8")
		except OSError:
			return ""
		return _expand_includes(body, target.parent, depth + 1, seen, collect)

	return INCLUDE_RE.sub(repl, text)


def _walk_chain(cwd: str, workspace_root: str) -> list[Path]:
	"""从 cwd 向上走到 workspace 根：根目录先加载、越靠近 cwd 越后加载。"""
	try:
		start = Path(cwd).expanduser().resolve()
		root = Path(workspace_root).expanduser().resolve()
	except OSError:
		return []
	chain: list[Path] = []
	cur = start
	for _ in range(32):
		chain.append(cur)
		if cur == root or cur.parent == cur:
			break
		try:
			cur.relative_to(root)
		except ValueError:
			break
		cur = cur.parent
	chain.reverse()
	return chain


def _chain_files(chain: list[Path]) -> list[Path]:
	"""展开链上每个目录的 XEYO.md / .xeyo/XEYO.md / .xeyo/rules/*.md。"""
	files: list[Path] = []
	for directory in chain:
		files.append(directory / "XEYO.md")
		files.append(directory / ".xeyo" / "XEYO.md")
		rules_dir = directory / ".xeyo" / "rules"
		if rules_dir.is_dir():
			files.extend(sorted(rules_dir.glob("*.md")))
	return files


def walk_up_to_root(
	cwd: str,
	workspace_root: str,
	*,
	collect: set[Path] | None = None,
) -> list[str]:
	"""从 cwd 向上走到 workspace 根，收集 XEYO.md / .xeyo/XEYO.md / rules。

	根目录先加载、越靠近 cwd 越后加载（后加载覆盖）。
	"""
	chunks: list[str] = []
	for path in _chain_files(_walk_chain(cwd, workspace_root)):
		chunks.extend(read_optional(path, collect=collect))
	return chunks


def read_aliases(workspace_root: str, *, collect: set[Path] | None = None) -> list[str]:
	"""只读并入 CLAUDE.md / AGENTS.md / .cursor/rules，新写入仍用 XEYO.md"""
	try:
		root = Path(workspace_root).expanduser().resolve()
	except OSError:
		return []
	chunks: list[str] = []
	chunks.extend(read_optional(root / "CLAUDE.md", collect=collect))
	chunks.extend(read_optional(root / "AGENTS.md", collect=collect))
	chunks.extend(read_glob(root / ".cursor" / "rules" / "*.md", collect=collect))
	return chunks


def _signature(files: Iterable[Path]) -> tuple[tuple[str, int, int], ...]:
	"""按「实际读取到的文件 → (path, mtime_ns, size)」生成失效签名。"""
	out: list[tuple[str, int, int]] = []
	for path in sorted({str(p.resolve()) for p in files}):
		try:
			st = Path(path).stat()
		except OSError:
			out.append((path, 0, 0))
			continue
		out.append((path, st.st_mtime_ns, st.st_size))
	return tuple(out)


def _discover_paths(cwd: str, workspace_root: str) -> list[Path]:
	"""按加载顺序列出候选指令文件（只 stat，不读正文），供缓存失效签名。"""
	home = xeyo_home()
	files: list[Path] = []
	files.append(home / "XEYO.md")
	rules_home = home / "rules"
	if rules_home.is_dir():
		files.extend(sorted(rules_home.glob("*.md")))
	files.extend(_chain_files(_walk_chain(cwd, workspace_root)))
	try:
		root = Path(workspace_root).expanduser().resolve()
	except OSError:
		root = Path(workspace_root)
	files.append(root / "XEYO.local.md")
	files.append(root / "CLAUDE.md")
	files.append(root / "AGENTS.md")
	cursor_rules = root / ".cursor" / "rules"
	if cursor_rules.is_dir():
		files.extend(sorted(cursor_rules.glob("*.md")))
	return files


def load_instruction_text(cwd: str, workspace_root: str) -> str:
	"""按优先级拼接 XEYO.md 文件族（后加载覆盖先加载），供 system 左段注入。

	带缓存：签名覆盖「候选文件集 + 实际读取到的 @include 目标」，
	任一方 (path, mtime_ns, size) 变化都触发重载；compact 后调用
	clear_instruction_cache() 强制重载。

	常驻段优先占满软预算（见 instruction_char_budget）；带 paths: 且匹配的段再追加。
	子目录嵌套规则不靠「读文件」时：仅当 cwd 位于子树时 walk_up 带入；
	工作区根会话的深层规则由 instruction_maintain 在 Read 后挂 T_now。
	"""
	home = xeyo_home()
	discovered = _discover_paths(cwd, workspace_root)
	top_sig = _signature(discovered)
	budget = instruction_char_budget()

	key = (str(cwd), str(workspace_root), budget)
	cached = _CACHE.get(key)
	if cached is not None:
		cached_top, cached_full, cached_text = cached
		if _signature(discovered) == cached_top:
			full_paths = {Path(p) for p, _m, _s in cached_full}
			if _signature(full_paths) == cached_full:
				return cached_text

	collect: set[Path] = set()
	chunks: list[str] = []
	chunks.extend(read_optional(home / "XEYO.md", collect=collect))
	chunks.extend(read_glob(home / "rules" / "*.md", collect=collect))
	chunks.extend(walk_up_to_root(cwd, workspace_root, collect=collect))
	try:
		root = Path(workspace_root).expanduser().resolve()
		chunks.extend(read_optional(root / "XEYO.local.md", collect=collect))
	except OSError:
		pass
	chunks.extend(read_aliases(workspace_root, collect=collect))

	core: list[str] = []
	scoped: list[str] = []
	for chunk in chunks:
		body, is_scoped = _filter_instruction_chunk(
			chunk, cwd=cwd, workspace_root=workspace_root
		)
		if not body:
			continue
		if is_scoped:
			scoped.append(body)
		else:
			core.append(body)

	text = join_with_caps(core, max_chars=budget)
	remain = budget - len(text)
	if remain > 64 and scoped:
		extra = join_with_caps(scoped, max_chars=remain)
		if extra:
			text = f"{text}\n\n{extra}" if text else extra
			if len(text) > budget:
				text = text[:budget]
	_CACHE[key] = (top_sig, _signature(collect), text)
	return text
