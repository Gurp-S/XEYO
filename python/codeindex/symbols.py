"""codeindex.symbols — 按需符号解析 + 内容哈希缓存（33号计划 §2.2）。

三个公开函数 + 一个数据类，全部无持久状态：
- 解析按需触发（首次访问某文件时），结果只存 Symbol 元数据；
- 失效校验用 (size, content_hash)，不依赖 mtime（规避 Windows 同秒粗粒度）；
- 语言后端表驱动：.py 走内置 ast（零依赖），ts/tsx/js 走 tree-sitter（可选依赖，
  未安装降级为正则启发式并标记 approximate），其他扩展名返回空。
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterator, Sequence

# ---- 缓存与防御上限（计划书 §2.2 / §4.1） ----
MAX_CACHED_FILES = 5000        # 插入序 LRU，超限淘汰最旧
MAX_SCAN_SYMBOLS = 200_000     # iter_symbols 单次调用累计符号截断
MAX_PARSE_BYTES = 2_000_000    # 超大文件不解析（防御病态输入）

# 支持的代码扩展名 → 后端分发
PY_EXTENSIONS = frozenset({".py", ".pyi"})
TS_EXTENSIONS = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
CODE_EXTENSIONS = PY_EXTENSIONS | TS_EXTENSIONS

_SIGNATURE_MAX_CHARS = 200


@dataclass(frozen=True)
class Symbol:
	"""单个符号的元数据（不携带源码）。"""

	kind: str          # class | method | function | interface | enum | type
	name: str
	start: int         # 起始行，1-indexed，含
	end: int           # 结束行，1-indexed，含
	parent: str | None # 最近一层外层符号名（方法 → 所属类）
	signature: str     # 单行签名串
	approximate: bool = False  # True = 启发式解析产物，行号范围可能不准


# ---- 内容哈希缓存 ----
# 键 = 绝对路径；值 = (size, hash_hex, symbols)。命中时读文件重算哈希比对，
# 不一致才重解析（parse 本就要读文件，校验无额外 I/O）。
_CACHE: OrderedDict[str, tuple[int, str, tuple[Symbol, ...]]] = OrderedDict()


def clear_cache() -> None:
	_CACHE.clear()


def _file_hash(data: bytes) -> str:
	return hashlib.blake2b(data, digest_size=16).hexdigest()


def _read_bytes(path: str) -> bytes | None:
	try:
		if os.path.getsize(path) > MAX_PARSE_BYTES:
			return None
		with open(path, "rb") as f:
			return f.read()
	except OSError:
		return None


def _decode(data: bytes) -> str:
	if data.startswith(b"\xff\xfe"):
		return data.decode("utf-16-le", errors="replace")
	return data.decode("utf-8", errors="replace")


def outline(path: str) -> tuple[Symbol, ...]:
	"""单文件符号大纲；不可读/不支持/解析失败一律返回空。"""
	abs_path = os.path.abspath(path)
	ext = os.path.splitext(abs_path)[1].lower()
	if ext not in CODE_EXTENSIONS:
		return ()

	data = _read_bytes(abs_path)
	if data is None:
		_CACHE.pop(abs_path, None)
		return ()
	size = len(data)
	hash_hex = _file_hash(data)

	cached = _CACHE.get(abs_path)
	if cached is not None and cached[0] == size and cached[1] == hash_hex:
		_CACHE.move_to_end(abs_path)
		return cached[2]

	text = _decode(data)
	if ext in PY_EXTENSIONS:
		symbols = _parse_python(text)
	else:
		symbols = _parse_ts_js(text, ext)

	_CACHE[abs_path] = (size, hash_hex, symbols)
	while len(_CACHE) > MAX_CACHED_FILES:
		_CACHE.popitem(last=False)
	return symbols


def locate(path: str, symbol_path: str) -> Symbol | None:
	"""点号路径定位（如 "ChatStore.applyRewind"）。

	先匹配 parent 链全路径，再回退尾段唯一匹配；命中多个返回 None（歧义），
	调用方可用 locate_all 列出候选。
	"""
	matches = locate_all(path, symbol_path)
	if len(matches) == 1:
		return matches[0]
	return None


def locate_all(path: str, symbol_path: str) -> list[Symbol]:
	"""locate 的全量版本：返回所有命中（0/1/N 个）。"""
	parts = [p for p in symbol_path.strip().strip(".").split(".") if p]
	if not parts:
		return []
	symbols = outline(path)


	# 1) 全路径精确匹配（父链逐级比对，支持 A.B.method 深路径）
	for depth in range(len(parts) - 1, 0, -1):
		tail = parts[depth:]
		exact = [
			s for s in symbols
			if s.name == tail[-1]
			and _parent_chain_matches(symbols, s, tuple(parts[:depth]) + tuple(tail[:-1]))
		]
		if exact:
			return exact

	# 2) 尾段名匹配（parent 一致优先，其次仅按名）
	by_name = [s for s in symbols if s.name == parts[-1]]
	if not by_name:
		return []
	if len(parts) == 1 or len(by_name) == 1:
		return by_name
	with_parent = [s for s in by_name if s.parent == parts[-2]]
	return with_parent or []


def _parent_chain_matches(symbols: Sequence[Symbol], sym: Symbol, chain: tuple[str, ...]) -> bool:
	"""校验 sym 的祖先链是否为 chain（从最外层到直接父级）。"""
	by_name: dict[str, list[Symbol]] = {}
	for s in symbols:
		by_name.setdefault(s.name, []).append(s)
	current = sym
	for expected in reversed(chain):
		if current.parent is None or current.parent != expected:
			return False
		parents = by_name.get(expected, [])
		container = next((p for p in parents if p.start <= current.start <= p.end), None)
		if container is None:
			return False
		current = container
	return True


def iter_symbols(
	paths: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
	pattern: str,
	*,
	ignore_case: bool = True,
	max_symbols: int = MAX_SCAN_SYMBOLS,
) -> Iterator[tuple[str, Symbol]]:
	"""多文件流式符号过滤（惰性，逐文件产出）。

	paths 可为单路径或路径序列（文件或目录，目录递归展开，跳过排除目录与
	非代码扩展名）。pattern 为按符号名过滤的正则；产出累计到 max_symbols 截断。
	产出 (path, symbol)，path 为调用方传入形态对应的绝对路径字符串。
	"""
	if isinstance(paths, (str, os.PathLike)):
		paths = [paths]
	try:
		regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
	except re.error:
		regex = re.compile(re.escape(pattern), re.IGNORECASE if ignore_case else 0)

	excluded = _excluded_dirs()
	count = 0
	for file_path in _walk_code_files(paths, excluded):
		for sym in outline(file_path):
			if regex.search(sym.name):
				yield file_path, sym
				count += 1
				if count >= max_symbols:
					return


# ---- 目录展开与排除 ----

def _excluded_dirs() -> frozenset[str]:
	# 懒加载：与 Grep/Glob 共用同一份排除清单（含 XEYO_SEARCH_EXCLUDE 追加项）
	from tools.fileio.excludes import search_excluded_dirs

	return frozenset(search_excluded_dirs())


def _walk_code_files(paths: Sequence[str | os.PathLike[str]], excluded: frozenset[str]) -> Iterator[str]:
	for raw in paths:
		abs_path = os.path.abspath(raw)
		if os.path.isfile(abs_path):
			if os.path.splitext(abs_path)[1].lower() in CODE_EXTENSIONS:
				yield abs_path
			continue
		if not os.path.isdir(abs_path):
			continue
		for dirpath, dirnames, filenames in os.walk(abs_path):
			dirnames[:] = sorted(d for d in dirnames if d not in excluded and not d.startswith("."))
			for name in sorted(filenames):
				if os.path.splitext(name)[1].lower() in CODE_EXTENSIONS:
					yield os.path.join(dirpath, name)


# ---- Python 后端（内置 ast，零依赖） ----

def _parse_python(text: str) -> tuple[Symbol, ...]:
	try:
		tree = ast.parse(text)
	except SyntaxError:
		return ()
	lines = text.split("\n")
	symbols: list[Symbol] = []

	def signature(line_no: int) -> str:
		return lines[line_no - 1].strip()[:_SIGNATURE_MAX_CHARS] if 0 < line_no <= len(lines) else ""

	def visit(node: ast.AST, parent: str | None, in_class: bool) -> None:
		for child in ast.iter_child_nodes(node):
			if isinstance(child, ast.ClassDef):
				symbols.append(Symbol(
					kind="class", name=child.name, start=child.lineno,
					end=child.end_lineno or child.lineno, parent=parent,
					signature=signature(child.lineno),
				))
				visit(child, child.name, True)
			elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
				kind = "method" if in_class else "function"
				symbols.append(Symbol(
					kind=kind, name=child.name, start=child.lineno,
					end=child.end_lineno or child.lineno, parent=parent,
					signature=signature(child.lineno),
				))
				visit(child, child.name, False)
			else:
				visit(child, parent, in_class)

	visit(tree, None, False)
	symbols.sort(key=lambda s: s.start)
	return tuple(symbols)


# ---- TS/JS 后端（tree-sitter 可选，未装降级正则启发式） ----

_TS_NODE_KINDS: dict[str, str] = {
	"class_declaration": "class",
	"abstract_class_declaration": "class",
	"class": "class",
	"interface_declaration": "interface",
	"enum_declaration": "enum",
	"type_alias_declaration": "type",
	"function_declaration": "function",
	"function_signature": "function",
	"generator_function_declaration": "function",
	"method_definition": "method",
}


def _parse_ts_js(text: str, ext: str) -> tuple[Symbol, ...]:
	parser = _ts_parser(ext)
	if parser is None:
		return _parse_ts_regex(text)
	try:
		tree = parser.parse(text.encode("utf-8"))
	except Exception:
		return _parse_ts_regex(text)
	lines = text.split("\n")
	symbols: list[Symbol] = []

	def signature(row: int) -> str:
		return lines[row].strip()[:_SIGNATURE_MAX_CHARS] if row < len(lines) else ""

	def visit(node, parent: str | None, in_class: bool) -> None:
		kind = _TS_NODE_KINDS.get(node.type)
		if kind:
			name_node = node.child_by_field_name("name")
			name = name_node.text.decode("utf-8", "replace") if name_node else ""
			if name:
				symbols.append(Symbol(
					kind=kind, name=name,
					start=node.start_point.row + 1,
					end=node.end_point.row + 1,
					parent=parent,
					signature=signature(node.start_point.row),
				))
				if kind == "class":
					for child in node.children:
						visit(child, name, True)
					return
		# 变量声明挂箭头函数/函数表达式 → function（顶层或类属性）
		if node.type in ("variable_declarator", "lexical_declaration", "variable_declaration"):
			name_node = node.child_by_field_name("name") if node.type == "variable_declarator" else None
			name = ""
			target = node
			if name_node is not None:
				name = name_node.text.decode("utf-8", "replace")
			else:
				decl = next((c for c in node.children if c.type == "variable_declarator"), None)
				if decl is not None:
					decl_name = decl.child_by_field_name("name")
					value = decl.child_by_field_name("value")
					if decl_name is not None and value is not None and value.type in (
						"arrow_function", "function", "function_expression",
					):
						name = decl_name.text.decode("utf-8", "replace")
						target = decl
			if name:
				value = target.child_by_field_name("value") if target.type == "variable_declarator" else None
				if value is None or value.type in ("arrow_function", "function", "function_expression"):
					symbols.append(Symbol(
						kind="function", name=name,
						start=node.start_point.row + 1,
						end=(value or target).end_point.row + 1,
						parent=parent,
						signature=signature(node.start_point.row),
					))
					return
		for child in node.children:
			visit(child, parent, in_class)

	visit(tree.root_node, None, False)
	symbols.sort(key=lambda s: s.start)
	return tuple(symbols)


_TS_PARSER_CACHE: dict[str, object | None] = {}


def _ts_parser(ext: str):
	"""懒加载 tree-sitter Parser；未安装/初始化失败返回 None（降级启发式）。"""
	if ext in _TS_PARSER_CACHE:
		return _TS_PARSER_CACHE[ext]
	parser = None
	try:
		from tree_sitter import Language, Parser  # type: ignore

		if ext in (".tsx", ".jsx"):
			import tree_sitter_typescript as ts_lang  # type: ignore

			language = Language(ts_lang.language_tsx())
		elif ext in (".ts", ".mts", ".cts"):
			import tree_sitter_typescript as ts_lang  # type: ignore

			language = Language(ts_lang.language_typescript())
		else:
			import tree_sitter_javascript as js_lang  # type: ignore

			language = Language(js_lang.language())
		try:
			parser = Parser(language)  # tree-sitter >= 0.22 新 API
		except TypeError:
			parser = Parser()
			parser.language = language  # 旧 API
	except Exception:
		parser = None
	_TS_PARSER_CACHE[ext] = parser
	return parser


_DECL_RE = re.compile(
	r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?"
	r"(?:(async)\s+)?"
	r"(?:"
	r"function\s*\*?\s*([A-Za-z_$][\w$]*)"
	r"|(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
	r"|interface\s+([A-Za-z_$][\w$]*)"
	r"|enum\s+([A-Za-z_$][\w$]*)"
	r"|type\s+([A-Za-z_$][\w$]*)"
	r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(?:async\s*)?(?:\(|function\b)"
	r")"
)


def _parse_ts_regex(text: str) -> tuple[Symbol, ...]:
	"""无 tree-sitter 时的降级：正则匹配声明行，end 按缩进回推（approximate）。"""
	lines = text.split("\n")
	symbols: list[Symbol] = []
	# groups()[1:] 去掉 async 组后按序对应：function/class/interface/enum/type/const-fn
	kind_by_group = {1: "function", 2: "class", 3: "interface", 4: "enum", 5: "type", 6: "function"}
	for i, line in enumerate(lines):
		m = _DECL_RE.match(line)
		if not m:
			continue
		name = next((g for g in m.groups()[1:] if g), None)
		if not name:
			continue
		kind = kind_by_group[next(idx for idx, g in enumerate(m.groups()[1:], start=1) if g)]
		indent = len(line) - len(line.lstrip())
		end = _block_end_by_indent(lines, i, indent)
		symbols.append(Symbol(
			kind=kind, name=name, start=i + 1, end=end, parent=None,
			signature=line.strip()[:_SIGNATURE_MAX_CHARS], approximate=True,
		))
	return tuple(symbols)


def _block_end_by_indent(lines: list[str], start_idx: int, indent: int) -> int:
	"""启发式块尾：从声明行向下找第一个缩进 <= 声明缩进的非空行，取其前一行。"""
	for j in range(start_idx + 1, len(lines)):
		line = lines[j]
		if not line.strip():
			continue
		if len(line) - len(line.lstrip()) <= indent:
			return j
	return len(lines)
