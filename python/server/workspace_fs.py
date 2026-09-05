"""工作区文件浏览：仅允许 cwd 内路径。"""

from __future__ import annotations

import base64
import functools
import os
import mimetypes
import shutil
from collections import deque
from pathlib import Path
from typing import Any


@functools.lru_cache(maxsize=1024)
def _guess_mime(name: str) -> str:
	return mimetypes.guess_type(name)[0] or "application/octet-stream"

_MAX_ENTRIES = 800
_MAX_TEXT = 400_000
_MAX_IMAGE = 2 * 1024 * 1024
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
# 产品内部目录 / 仓库元数据：在工作区树与搜索中隐藏，避免噪音与嵌套访问（Agent 工具不受影响）。
_EXCLUDED_DIRS = {
	".git",
	".xy-shadow-git",
	".xy-trash",
	".xeyo_uploads",
	".xeyo_filehelper",
	".xeyo_ilink",
}
_MAX_SEARCH_DEPTH = 6
_MAX_SEARCH_HITS = 200

# G52: 直写通道的显式开关——设 XEYO_WORKSPACE_FS_READONLY=1 后,该旁路
# 只读,任何写/删抛 PermissionError(要求走引擎权限/rewind 链)。
def _workspace_fs_writes_allowed() -> bool:
	raw = os.environ.get("XEYO_WORKSPACE_FS_READONLY", "").strip().lower()
	return raw not in ("1", "true", "on", "yes")


def _audit_write(action: str, cwd: str, rel: str, **extra: Any) -> None:
	"""直写旁路的审计痕迹(不穿引擎权限时的最低可观测保障)。"""
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			f"workspace_fs.{action}", cwd=cwd, rel=rel, **extra
		)
	except Exception:
		pass


def resolve_in_workspace(cwd: str, rel: str) -> Path:
	root = Path(cwd).expanduser().resolve()
	if not root.is_dir():
		raise FileNotFoundError(f"workspace not found: {root}")
	raw = (rel or "").strip().replace("\\", "/")
	if raw in ("", ".", "/"):
		return root
	candidate = Path(raw)
	target = candidate.resolve() if candidate.is_absolute() else (root / raw).resolve()
	try:
		target.relative_to(root)
	except ValueError as e:
		raise PermissionError("path outside workspace") from e
	return target


def _rel_posix(root: Path, path: Path) -> str:
	rel = path.relative_to(root)
	return "" if str(rel) == "." else rel.as_posix()


def list_entries(cwd: str, rel: str = "") -> dict[str, Any]:
	root = Path(cwd).expanduser().resolve()
	folder = resolve_in_workspace(cwd, rel)
	if not folder.is_dir():
		raise NotADirectoryError(f"not a directory: {folder}")
	dirs: list[dict[str, Any]] = []
	files: list[dict[str, Any]] = []
	try:
		children = list(folder.iterdir())
	except OSError as e:
		raise PermissionError(str(e)) from e
	children = [p for p in children if p.name not in _EXCLUDED_DIRS]
	children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
	for entry in children[:_MAX_ENTRIES]:
		try:
			if entry.is_symlink():
				dest = entry.resolve()
				try:
					dest.relative_to(root)
				except ValueError:
					continue
			is_dir = entry.is_dir()
			item = {
				"name": entry.name,
				"path": _rel_posix(root, entry),
				"kind": "dir" if is_dir else "file",
			}
			if not is_dir:
				try:
					item["size"] = entry.stat().st_size
				except OSError:
					item["size"] = 0
			(dirs if is_dir else files).append(item)
		except OSError:
			continue
	return {
		"cwd": str(root),
		"path": _rel_posix(root, folder),
		"name": root.name if folder == root else folder.name,
		"entries": dirs + files,
		"truncated": len(children) > _MAX_ENTRIES,
	}


def _looks_binary(sample: bytes) -> bool:
	if not sample:
		return False
	if b"\x00" in sample:
		return True
	# 高比例非文本控制字节
	ctrl = sum(1 for b in sample if b < 9 or 13 < b < 32)
	return ctrl / max(len(sample), 1) > 0.3


def _file_mtime_ms(st: Any) -> int:
	"""mtime 用毫秒整数，便于前端轻量轮询比对。"""
	return int(st.st_mtime * 1000)


def stat_file(cwd: str, rel: str) -> dict[str, Any]:
	"""只 stat，不读正文。供预览忙碌期轮询。"""
	root = Path(cwd).expanduser().resolve()
	path = resolve_in_workspace(cwd, rel)
	if not path.is_file():
		raise FileNotFoundError(f"file not found: {path}")
	st = path.stat()
	return {
		"cwd": str(root),
		"path": _rel_posix(root, path),
		"name": path.name,
		"size": st.st_size,
		"mtime": _file_mtime_ms(st),
	}


def read_file(cwd: str, rel: str) -> dict[str, Any]:
	root = Path(cwd).expanduser().resolve()
	path = resolve_in_workspace(cwd, rel)
	if not path.is_file():
		raise FileNotFoundError(f"file not found: {path}")
	suffix = path.suffix.lower()
	mime = _guess_mime(path.name)
	st = path.stat()
	size = st.st_size
	mtime = _file_mtime_ms(st)
	payload: dict[str, Any] = {
		"cwd": str(root),
		"path": _rel_posix(root, path),
		"name": path.name,
		"mime": mime,
		"size": size,
		"mtime": mtime,
		"kind": "text",
	}
	if suffix in _IMAGE_EXT and size <= _MAX_IMAGE:
		raw = path.read_bytes()
		b64 = base64.b64encode(raw).decode("ascii")
		payload["kind"] = "image"
		payload["data_url"] = f"data:{mime};base64,{b64}"
		return payload
	# 只读取上限内的字节，大文件（远超 _MAX_TEXT）无需整文件读入内存。
	with path.open("rb") as f:
		raw = f.read(_MAX_TEXT + 8)
	sample = raw[:8192]
	if _looks_binary(sample):
		payload["kind"] = "binary"
		payload["text"] = f"[binary file · {size} bytes]"
		return payload
	try:
		text = raw.decode("utf-8")
	except UnicodeDecodeError:
		text = raw.decode("gbk", errors="replace")
	truncated = size > _MAX_TEXT
	if truncated:
		text = text[:_MAX_TEXT] + "\n…[truncated]"
	payload["kind"] = "text"
	payload["text"] = text
	payload["truncated"] = truncated
	return payload


def write_file(cwd: str, rel: str, text: str) -> dict[str, Any]:
	if not _workspace_fs_writes_allowed():
		raise PermissionError(
			"workspace_fs writes disabled by XEYO_WORKSPACE_FS_READONLY=1 "
			"(use the engine permission/rewind path instead)"
		)
	if len(text) > _MAX_TEXT:
		raise ValueError(f"file too large to write (max {_MAX_TEXT} chars)")
	path = resolve_in_workspace(cwd, rel)
	if path.exists() and path.is_dir():
		raise IsADirectoryError(f"path is a directory: {path}")
	if path.suffix.lower() in _IMAGE_EXT:
		raise PermissionError("refusing to overwrite image as text")
	if path.name in _EXCLUDED_DIRS:
		raise PermissionError("refusing to write internal path")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8", newline="\n")
	_audit_write("write", cwd, rel, bytes=len(text))
	return read_file(cwd, rel)


def delete_path(cwd: str, rel: str, recursive: bool = False) -> dict[str, Any]:
	"""删除工作区内文件或目录。目录默认仅允许空目录；recursive=True 时整棵删除。"""
	if not _workspace_fs_writes_allowed():
		raise PermissionError(
			"workspace_fs writes disabled by XEYO_WORKSPACE_FS_READONLY=1 "
			"(use the engine permission/rewind path instead)"
		)
	root = Path(cwd).expanduser().resolve()
	path = resolve_in_workspace(cwd, rel)
	if path == root:
		raise PermissionError("refusing to delete workspace root")
	if path.name in _EXCLUDED_DIRS:
		raise PermissionError("refusing to delete internal path")
	if not path.exists():
		raise FileNotFoundError(f"path not found: {path}")
	if path.is_dir():
		if not recursive and any(path.iterdir()):
			raise IsADirectoryError(f"directory not empty: {path}")
		shutil.rmtree(path)
	else:
		path.unlink()
	_audit_write("delete", cwd, rel, recursive=recursive)
	return {"ok": True, "cwd": str(root), "path": _rel_posix(root, path)}


def search_entries(cwd: str, query: str, limit: int = _MAX_SEARCH_HITS) -> dict[str, Any]:
	"""按文件名（大小写不敏感、包含匹配）在工作区内搜索。

	广度优先遍历，最多 _MAX_SEARCH_DEPTH 层；隐藏内部目录，命中数封顶。
	"""
	root = Path(cwd).expanduser().resolve()
	if not root.is_dir():
		raise FileNotFoundError(f"workspace not found: {root}")
	q = (query or "").strip().lower()
	limit = max(1, min(limit, _MAX_SEARCH_HITS))
	hits: list[dict[str, Any]] = []
	if not q:
		return {"cwd": str(root), "query": query, "hits": hits, "truncated": False}
	frontier: deque[tuple[Path, int]] = deque([(root, 0)])
	truncated = False
	while frontier and len(hits) < limit:
		folder, depth = frontier.popleft()
		try:
			children = list(folder.iterdir())
		except OSError:
			continue
		for child in children:
			if child.name in _EXCLUDED_DIRS:
				continue
			try:
				is_dir = child.is_dir()
			except OSError:
				continue
			if q in child.name.lower():
				try:
					size = None if is_dir else child.stat().st_size
				except OSError:
					size = None
				hits.append(
					{
						"name": child.name,
						"path": _rel_posix(root, child),
						"kind": "dir" if is_dir else "file",
						"size": size,
					}
				)
			if is_dir and depth + 1 <= _MAX_SEARCH_DEPTH:
				frontier.append((child, depth + 1))
		if len(hits) >= limit:
			truncated = True
			break
	return {"cwd": str(root), "query": query, "hits": hits, "truncated": truncated}
