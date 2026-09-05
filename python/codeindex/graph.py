"""工作区代码图：文件节点 + import 边 + 架构层折叠。

机制移植自 Understand-Anything（结构图 / 分层）与 Archify（组件与边界），
但零 LLM、无持久索引、不外挂其仪表盘。图只服务 GUI 的「地图 + 当前
agent 落点」；工具层不新增入口。
"""

from __future__ import annotations

import ast
import os
import re
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from codeindex.symbols import CODE_EXTENSIONS, PY_EXTENSIONS, TS_EXTENSIONS

# 硬顶：超大仓只扫前 N 个源文件，避免 AST 全仓解析卡死 UI。
# 经验值：≤400 文件 + 边顶后，本机首次扫描通常 <2s；前端代码视图再截到 ≤64 节点。
MAX_FILES = 400
MAX_EDGES = 2000
MAX_PARSE_BYTES = 120_000
MAX_WALK_DIRS = 2000
MAX_PACKAGES = 120
MAX_PACKAGE_EDGES = 400

# 额外噪音目录（Grep 排除清单之外、地图不应出现的内部产物）
_GRAPH_SKIP_DIRS = frozenset({
	".dismantle",
	".agents",
	".cursor",
	".vscode",
	".idea",
	"__pycache__",
	"target",
	"coverage",
})

LAYER_ORDER = (
	"ui",
	"api",
	"engine",
	"tools",
	"prompt",
	"memory",
	"policy",
	"core",
	"test",
	"docs",
)

_TS_SPEC_RE = re.compile(
	r"""(?:import|export)\s+(?:type\s+)?(?:[^'"\n;]+?\s+from\s+)?['"]([^'"]+)['"]"""
	r"""|import\(\s*['"]([^'"]+)['"]\s*\)"""
	r"""|require\(\s*['"]([^'"]+)['"]\s*\)""",
	re.MULTILINE,
)

# 进程内缓存：cwd → (mtime_bucket, built_at, graph)
_CACHE_LOCK = threading.Lock()
_GRAPH_CACHE: dict[str, tuple[float, float, dict[str, Any]]] = {}
_CACHE_TTL_SEC = 60.0


def clear_graph_cache() -> None:
	"""测试 / 手动刷新入口。"""
	with _CACHE_LOCK:
		_GRAPH_CACHE.clear()


def build_workspace_graph(cwd: str, *, refresh: bool = False) -> dict[str, Any]:
	"""扫描工作区，返回文件图 + 架构（包）图。

	``refresh=True`` 跳过缓存强制重扫（GUI 刷新按钮）。
	"""
	root = Path(cwd).expanduser().resolve()
	if not root.is_dir():
		raise FileNotFoundError(f"workspace not found: {root}")

	key = str(root)
	now = time.monotonic()
	if not refresh:
		with _CACHE_LOCK:
			hit = _GRAPH_CACHE.get(key)
			if hit is not None:
				_stamp, built_at, graph = hit
				if now - built_at < _CACHE_TTL_SEC:
					return graph

	graph = _build_workspace_graph_uncached(root)
	with _CACHE_LOCK:
		_GRAPH_CACHE[key] = (now, now, graph)
	return graph


def _build_workspace_graph_uncached(root: Path) -> dict[str, Any]:
	excluded = _excluded_dirs()
	files = list(_walk_code_files(root, excluded))
	truncated = len(files) > MAX_FILES
	files = files[:MAX_FILES]

	rel_by_abs = {abs_path: _rel_posix(root, Path(abs_path)) for abs_path in files}
	file_index = _build_file_index(root, rel_by_abs.values())

	file_nodes: list[dict[str, Any]] = []
	file_edges: list[dict[str, str]] = []
	seen_edges: set[tuple[str, str]] = set()

	for abs_path in files:
		rel = rel_by_abs[abs_path]
		pkg = package_id(rel)
		layer = infer_layer(rel)
		file_nodes.append({
			"id": rel,
			"name": Path(rel).name,
			"layer": layer,
			"pkg": pkg,
		})
		for dest in _imports_of(abs_path, rel, file_index):
			key = (rel, dest)
			if key in seen_edges or dest == rel:
				continue
			seen_edges.add(key)
			file_edges.append({"from": rel, "to": dest})
			if len(file_edges) >= MAX_EDGES:
				break
		if len(file_edges) >= MAX_EDGES:
			break

	packages, package_edges = _collapse_packages(file_nodes, file_edges)
	pkg_truncated = len(packages) > MAX_PACKAGES
	if pkg_truncated:
		packages = packages[:MAX_PACKAGES]
		keep = {p["id"] for p in packages}
		package_edges = [
			e for e in package_edges if e["from"] in keep and e["to"] in keep
		][:MAX_PACKAGE_EDGES]
	elif len(package_edges) > MAX_PACKAGE_EDGES:
		package_edges = package_edges[:MAX_PACKAGE_EDGES]
		pkg_truncated = True
	return {
		"ok": True,
		"cwd": str(root).replace("\\", "/"),
		"fileCount": len(file_nodes),
		"truncated": truncated or pkg_truncated,
		"layers": [layer for layer in LAYER_ORDER if any(n["layer"] == layer for n in packages)],
		"files": file_nodes,
		"fileEdges": file_edges,
		"packages": packages,
		"packageEdges": package_edges,
	}


def infer_layer(rel: str) -> str:
	"""路径启发式分层（Understand-Anything 的 layer 口径，无 LLM）。"""
	p = rel.replace("\\", "/").lower()
	parts = ("/" + p).replace("\\", "/")
	name = Path(p).name
	if (
		"/test/" in parts
		or "/tests/" in parts
		or name.endswith(".test.ts")
		or name.endswith(".test.tsx")
		or name.endswith(".spec.ts")
		or name.endswith("_test.py")
		or name.startswith("test_")
	):
		return "test"
	if p.startswith("docs/") or p.startswith("doc/"):
		return "docs"
	if "/permissions/" in parts:
		return "policy"
	if "/prompt/" in parts:
		return "prompt"
	if "/session/" in parts or "/memory/" in parts or "/rewind/" in parts:
		return "memory"
	if "/tools/" in parts:
		return "tools"
	if "/engine/" in parts:
		return "engine"
	if "/server/" in parts or "/routers/" in parts:
		return "api"
	if (
		p.startswith("gui/")
		or p.startswith("src/components/")
		or p.startswith("src/pages/")
		or p.endswith(".tsx")
	):
		return "ui"
	if p.startswith("gui/src/lib/") or p.startswith("src/lib/"):
		return "core"
	return "core"


def package_id(rel: str) -> str:
	"""折叠为架构节点：gui 取三段，python 取两段，其余取顶层目录。"""
	parts = [p for p in rel.replace("\\", "/").split("/") if p]
	if not parts:
		return "root"
	if len(parts) == 1:
		return parts[0]
	head = parts[0]
	if head == "gui" and len(parts) >= 3:
		return "/".join(parts[:3])
	if head == "python" and len(parts) >= 2:
		return "/".join(parts[:2])
	if head in {"src", "lib", "app"} and len(parts) >= 2:
		return "/".join(parts[:2])
	return head


def _excluded_dirs() -> frozenset[str]:
	from tools.fileio.excludes import search_excluded_dirs

	return frozenset(search_excluded_dirs()) | _GRAPH_SKIP_DIRS


def _rel_posix(root: Path, path: Path) -> str:
	return path.resolve().relative_to(root).as_posix()


def _walk_code_files(root: Path, excluded: frozenset[str]) -> list[str]:
	out: list[str] = []
	dir_count = 0
	for dirpath, dirnames, filenames in os.walk(root):
		dir_count += 1
		if dir_count > MAX_WALK_DIRS:
			break
		dirnames[:] = sorted(
			d for d in dirnames
			if d not in excluded and d not in _GRAPH_SKIP_DIRS and not d.startswith(".")
		)
		for name in sorted(filenames):
			ext = os.path.splitext(name)[1].lower()
			if ext not in CODE_EXTENSIONS:
				continue
			if name.endswith(".d.ts") or name.endswith(".min.js"):
				continue
			out.append(os.path.join(dirpath, name))
			if len(out) > MAX_FILES:
				return out
	return out


def _build_file_index(root: Path, rels: Iterable[str]) -> dict[str, str]:
	"""把多种 import 写法映射到工作区相对路径。"""
	index: dict[str, str] = {}
	for rel in rels:
		posix = rel.replace("\\", "/")
		index[posix] = posix
		no_ext = _strip_code_ext(posix)
		index[no_ext] = posix
		index[no_ext.replace("/", ".")] = posix
		# 文件路径 python/engine/query_loop.py 映射为模块名 engine.query_loop
		if posix.startswith("python/"):
			mod = _strip_code_ext(posix[len("python/"):]).replace("/", ".")
			index[mod] = posix
		if posix.startswith("gui/src/"):
			mod = _strip_code_ext(posix[len("gui/src/"):])
			index[mod] = posix
			index["@/" + mod] = posix
		if posix.startswith("src/"):
			mod = _strip_code_ext(posix[len("src/"):])
			index[mod] = posix
			index["@/" + mod] = posix
		# index.ts / __init__.py 目录导入
		base = Path(posix).name
		if base in {"index.ts", "index.tsx", "index.js", "index.mjs", "__init__.py"}:
			parent = str(Path(posix).parent).replace("\\", "/")
			if parent and parent != ".":
				index[parent] = posix
				index[parent.replace("/", ".")] = posix
	return index


def _strip_code_ext(path: str) -> str:
	lower = path.lower()
	for ext in (".tsx", ".ts", ".mts", ".cts", ".jsx", ".mjs", ".cjs", ".pyi", ".py", ".js"):
		if lower.endswith(ext):
			return path[: -len(ext)]
	return path


def _imports_of(abs_path: str, rel: str, index: dict[str, str]) -> list[str]:
	ext = os.path.splitext(abs_path)[1].lower()
	try:
		size = os.path.getsize(abs_path)
		if size > MAX_PARSE_BYTES:
			return []
		with open(abs_path, "rb") as f:
			data = f.read()
	except OSError:
		return []
	text = data.decode("utf-8", errors="replace")
	if ext in PY_EXTENSIONS:
		specs = _python_import_specs(text, rel)
	elif ext in TS_EXTENSIONS:
		specs = _ts_import_specs(text, rel)
	else:
		return []
	out: list[str] = []
	seen: set[str] = set()
	for spec in specs:
		resolved = _resolve_spec(spec, rel, index)
		if not resolved or resolved in seen:
			continue
		seen.add(resolved)
		out.append(resolved)
	return out


def _python_import_specs(text: str, rel: str) -> list[str]:
	try:
		tree = ast.parse(text)
	except SyntaxError:
		return []
	here = [p for p in Path(rel).parts[:-1]]
	specs: list[str] = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				name = (alias.name or "").strip()
				if name:
					specs.append(name)
		elif isinstance(node, ast.ImportFrom):
			level = int(node.level or 0)
			mod = (node.module or "").strip()
			if level <= 0:
				if mod:
					specs.append(mod)
				continue
			pkg = here[: max(0, len(here) - (level - 1))]
			if mod:
				pkg = pkg + mod.split(".")
			if pkg:
				specs.append(".".join(pkg))
	return specs


def _ts_import_specs(text: str, rel: str) -> list[str]:
	specs: list[str] = []
	for match in _TS_SPEC_RE.finditer(text):
		spec = next((g for g in match.groups() if g), "")
		spec = spec.strip()
		if spec:
			specs.append(spec)
	return specs


def _resolve_spec(spec: str, rel: str, index: dict[str, str]) -> str | None:
	raw = spec.strip()
	if not raw or raw.startswith("node:") or raw.startswith("http"):
		return None
	# npm / 标准库：没有路径分隔且不是别名
	if raw.startswith("."):
		here = Path(rel).parent.as_posix()
		joined = (Path(here) / raw).as_posix() if here != "." else raw
		# 规范化 ./a/../b
		norm = os.path.normpath(joined).replace("\\", "/")
		if norm.startswith("../") or norm == "..":
			return None
		return _lookup(norm, index)
	if raw.startswith("@/"):
		return _lookup(raw, index) or _lookup(raw[2:], index)
	# 裸模块：只接受已索引到工作区文件的（engine.query_loop 等）
	if "/" not in raw and "." not in raw:
		# 单段（react、os）几乎一定是外部包
		return None
	if "/" in raw and not raw.startswith("@/") and not any(
		raw.startswith(p) for p in ("gui/", "python/", "src/", "lib/")
	):
		# lodash/fp 一类
		if _lookup(raw, index) is None and _lookup(raw.replace("/", "."), index) is None:
			return None
	return _lookup(raw, index) or _lookup(raw.replace("/", "."), index)


def _lookup(key: str, index: dict[str, str]) -> str | None:
	k = key.replace("\\", "/").lstrip("./")
	if k in index:
		return index[k]
	for suffix in ("", ".ts", ".tsx", ".py", ".js", ".mjs"):
		cand = k + suffix
		if cand in index:
			return index[cand]
	for suffix in ("/index.ts", "/index.tsx", "/index.js", "/__init__.py"):
		cand = k + suffix
		if cand in index:
			return index[cand]
	return None


def _collapse_packages(
	files: list[dict[str, Any]],
	file_edges: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
	counts: dict[str, int] = defaultdict(int)
	layer_of: dict[str, str] = {}
	for node in files:
		pkg = str(node["pkg"])
		counts[pkg] += 1
		layer_of.setdefault(pkg, str(node["layer"]))

	packages = [
		{
			"id": pkg,
			"name": pkg.rsplit("/", 1)[-1],
			"layer": layer_of[pkg],
			"files": counts[pkg],
		}
		for pkg in sorted(counts, key=lambda p: (LAYER_ORDER.index(layer_of[p]) if layer_of[p] in LAYER_ORDER else 99, p))
	]
	edge_set: set[tuple[str, str]] = set()
	pkg_of_file = {n["id"]: str(n["pkg"]) for n in files}
	for edge in file_edges:
		src = pkg_of_file.get(edge["from"])
		dst = pkg_of_file.get(edge["to"])
		if not src or not dst or src == dst:
			continue
		edge_set.add((src, dst))
	package_edges = [{"from": a, "to": b} for a, b in sorted(edge_set)]
	return packages, package_edges
