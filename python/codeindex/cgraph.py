"""codeindex.cgraph — L4 代码知识图谱最小原型（v7 证据门专用）。

定位：离线证据门原型，验证「图谱检索 vs 现有 Grep+Read」。**独立于主线工具面**，
绝不参与 schemas()/工具注册（会话内工具面冻结红线）。

三件事：
- 持久化符号/边索引（sqlite，派生可全量重建）；
- 内容哈希增量更新（改哪文件重解析哪儿，不全量）；
- 跨文件符号定位查询（最小上下文，替代 Grep*N + Read 整读）。

解析复用 codeindex.symbols.outline（按需哈希缓存）；边 = 符号体调用名近似匹配。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from codeindex.symbols import CODE_EXTENSIONS, MAX_PARSE_BYTES, outline

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  sha TEXT NOT NULL,
  mtime REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS symbols (
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  start INTEGER NOT NULL,
  end INTEGER NOT NULL,
  parent TEXT,
  signature TEXT NOT NULL,
  PRIMARY KEY (path, name, start)
);
CREATE TABLE IF NOT EXISTS edges (
  src_path TEXT NOT NULL,
  src_name TEXT NOT NULL,
  dst_path TEXT NOT NULL,
  dst_name TEXT NOT NULL,
  kind TEXT NOT NULL,
  PRIMARY KEY (src_path, src_name, dst_path, dst_name)
);
CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edges(dst_path, dst_name);
"""


@dataclass(frozen=True)
class GraphHit:
	path: str
	name: str
	kind: str
	start: int
	end: int
	parent: str | None
	signature: str
	callers: tuple[tuple[str, str], ...] = ()  # (path, qualified_name)


def _db_path(root: str) -> Path:
	return Path(root) / "python" / ".cgraph_v7" / "index.sqlite3"


def _sha(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


def _connect(root: str) -> sqlite3.Connection:
	path = _db_path(root)
	path.parent.mkdir(parents=True, exist_ok=True)
	conn = sqlite3.connect(str(path))
	conn.execute("PRAGMA journal_mode=WAL")
	conn.executescript(_SCHEMA)
	return conn


def _walk_code_files(root: Path) -> list[str]:
	out: list[str] = []
	skip = {"node_modules", "__pycache__", ".git", ".cgraph_v7", "target", "dist", "build"}
	for dirpath, dirnames, filenames in os.walk(root):
		dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.startswith("."))
		for name in sorted(filenames):
			ext = os.path.splitext(name)[1].lower()
			if ext not in CODE_EXTENSIONS:
				continue
			if name.endswith(".d.ts") or name.endswith(".min.js"):
				continue
			out.append(os.path.join(dirpath, name))
	return out


def build_index(root: str) -> dict[str, int]:
	"""全量重建索引：清空后逐文件解析入库。返回 {symbols, edges} 条数。"""
	base = Path(root).resolve()
	_set_root(str(root))
	conn = _connect(str(root))
	try:
		conn.execute("DELETE FROM files")
		conn.execute("DELETE FROM symbols")
		conn.execute("DELETE FROM edges")
		n_sym = 0
		for abs_path in _walk_code_files(base):
			n_sym += _index_file(conn, base, abs_path)
		_build_edges(conn)
		conn.commit()
		cur = conn.execute("SELECT COUNT(*) FROM edges")
		n_edge = cur.fetchone()[0]
		return {"symbols": n_sym, "edges": n_edge}
	finally:
		conn.close()


def _index_file(conn: sqlite3.Connection, base: Path, abs_path: str) -> int:
	"""单文件解析入库（增量也走这）；返回入库符号数。"""
	rel = abs_path.replace("\\", "/")
	if base:
		try:
			rel = abs_path.replace("\\", "/")
			rel = rel.split(str(base).replace("\\", "/") + "/", 1)[-1]
		except Exception:
			pass
	try:
		data = Path(abs_path).read_bytes()
		if len(data) > MAX_PARSE_BYTES:
			return 0
		content_sha = _sha(data.decode("utf-8", "replace"))
	except OSError:
		return 0
	conn.execute("DELETE FROM symbols WHERE path=?", (rel,))
	conn.execute("DELETE FROM edges WHERE src_path=? OR dst_path=?", (rel, rel))
	conn.execute(
		"INSERT OR REPLACE INTO files(path, sha, mtime) VALUES (?,?,?)",
		(rel, content_sha, os.path.getmtime(abs_path)),
	)
	syms = outline(abs_path)
	n = 0
	for s in syms:
		conn.execute(
			"INSERT OR REPLACE INTO symbols(path, name, kind, start, end, parent, signature)"
			" VALUES (?,?,?,?,?,?,?)",
			(rel, s.name, s.kind, s.start, s.end, s.parent, s.signature[:200]),
		)
		n += 1
	return n


def _name_map(conn: sqlite3.Connection) -> dict[str, list[str]]:
	"""符号名 → 该名所有 (path, name) 定义，供跨文件边解析。"""
	m: dict[str, list[str]] = {}
	for path, name in conn.execute("SELECT path, name FROM symbols"):
		m.setdefault(name, []).append((path, name))
	return m


def _build_edges(conn: sqlite3.Connection) -> int:
	"""建近似调用边：符号体里出现 `name(` 即连到同名定义（含跨文件）。"""
	rows = conn.execute("SELECT path, name, signature FROM symbols").fetchall()
	by_name = {}
	for path, name, _sig in rows:
		by_name.setdefault(name, []).append(path)
	n = 0
	for path, name, _sig in rows:
		body = _symbol_body(path, name)
		if not body:
			continue
		found = set()
		for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
			callee = m.group(1)
			if callee == name or callee in found:
				continue
			dst_paths = by_name.get(callee)
			if not dst_paths:
				continue
			found.add(callee)
			for dp in dst_paths:
				conn.execute(
					"INSERT OR IGNORE INTO edges(src_path, src_name, dst_path, dst_name, kind)"
					" VALUES (?,?,?,?,?)",
					(path, name, dp, callee, "call"),
				)
				n += 1
	return n


def _symbol_body(path: str, name: str) -> str | None:
	"""取单个符号体文本，供建边。"""
	try:
		base = _current_root
		abs_path = path if os.path.isabs(path) else os.path.join(base, path)
		syms = outline(abs_path)
	except Exception:
		return None
	for s in syms:
		if s.name != name:
			continue
		try:
			lines = Path(abs_path).read_text(encoding="utf-8", errors="replace").split("\n")
		except OSError:
			return None
		return "\n".join(lines[s.start - 1 : s.end])
	return None


_current_root: str = ""


def _set_root(root: str) -> None:
	global _current_root
	_current_root = root


def incremental_update(root: str) -> dict[str, int]:
	"""增量更新：只对内容哈希变化的文件重解析。返回 {reparsed, total_symbols, edges}。"""
	base = Path(root).resolve()
	_set_root(str(root))
	conn = _connect(str(root))
	changed = 0
	total = 0
	try:
		for abs_path in _walk_code_files(base):
			rel = abs_path.replace("\\", "/").split(str(base).replace("\\", "/") + "/", 1)[-1]
			row = conn.execute("SELECT sha FROM files WHERE path=?", (rel,)).fetchone()
			try:
				data = Path(abs_path).read_bytes()
				content_sha = _sha(data.decode("utf-8", "replace"))
			except OSError:
				continue
			if row and row[0] == content_sha:
				continue
			total += _index_file(conn, base, abs_path)
			changed += 1
		_build_edges(conn)
		conn.commit()
		cur = conn.execute("SELECT COUNT(*) FROM edges")
		return {"reparsed": changed, "symbols": total, "edges": cur.fetchone()[0]}
	finally:
		conn.close()


def query_symbol(root: str, name: str) -> list[GraphHit]:
	"""按符号名查询：返回定义 + 同文件/跨文件调用者（最小上下文）。"""
	conn = _connect(root)
	try:
		rows = conn.execute(
			"SELECT path, name, kind, start, end, parent, signature"
			" FROM symbols WHERE name=? ORDER BY path",
			(name,),
		).fetchall()
		out: list[GraphHit] = []
		for path, n, kind, start, end, parent, signature in rows:
			callers = tuple(
				(p, f"{c}" ) for p, c in conn.execute(
					"SELECT DISTINCT src_path, src_name FROM edges WHERE dst_path=? AND dst_name=? AND src_name!=?",
					(path, n, n),
				)
			)
			out.append(GraphHit(path, n, kind, start, end, parent, signature, callers))
		return out
	finally:
		conn.close()


def read_symbol_body(root: str, h: GraphHit) -> str:
	"""读目标符号体正文（与现有 Read 同范围，公平口径）。"""
	base = root.replace("\\", "/").rstrip("/")
	abs_path = h.path if os.path.isabs(h.path) else os.path.join(root, h.path)
	try:
		lines = Path(abs_path).read_text(encoding="utf-8", errors="replace").split("\n")
	except OSError:
		return ""
	return "\n".join(lines[h.start - 1 : h.end])


def compile_hits(root: str, hits: list[GraphHit], max_callers: int = 6, with_body: bool = False) -> str:
	"""把命中最小编成文本：定位 + 签名 + 调用者（可选正文）。"""
	lines: list[str] = []
	for h in hits:
		qual = f"{h.parent}.{h.name}" if h.parent else h.name
		lines.append(f"# {h.kind} {qual}  @ {h.path}:{h.start}-{h.end}")
		lines.append(f"  signature: {h.signature}")
		if h.callers:
			for p, c in h.callers[:max_callers]:
				lines.append(f"  caller: {c}  @ {p}")
		if with_body:
			lines.append("-- body --")
			lines.append(read_symbol_body(root, h))
	return "\n".join(lines)
