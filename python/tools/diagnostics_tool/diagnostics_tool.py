"""Diagnostics — minimal language diagnostics (not a full LSP/IDE)."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from engine.abort import AbortController
from permissions import filesystem
from tools.base_tool import ToolResult
from tools.diagnostics_tool.prompt import DESCRIPTION, DIAGNOSTICS_TOOL_NAME

# 与 engine.compact.MAX_TOOL_RESULT_CHARS 对齐，避免白做。
_TIMEOUT_S = 30
_MAX_CHARS = 16_000
_MAX_LINES = 100
_MAX_FILES = 50
_MAX_DEPTH = 2
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}


class DiagnosticsTool:
	name = DIAGNOSTICS_TOOL_NAME

	def __init__(self, *, cwd: str = ".") -> None:
		self._cwd = os.path.abspath(os.path.expanduser(cwd or "."))

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"required": ["path"],
				"properties": {
					"path": {
						"type": "string",
						"description": (
							"Required file or small directory under workspace. "
							"The path identifies the file whose diagnostics are returned."
						),
					},
					"language": {
						"type": "string",
						"enum": ["auto", "python", "typescript", "javascript"],
						"description": (
							"Force backend. Default auto by extension / tsconfig."
						),
					},
				},
				"additionalProperties": False,
			},
		}

	def check_permissions(self, input_data: dict[str, Any], context: Any = None) -> bool:
		return filesystem.check_read_permission_for_tool(self, input_data, context)

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = input or {}
		path_raw = str(raw.get("path") or "").strip()
		if not path_raw:
			return ToolResult(
				content=(
					"path is required. Pass the file you just edited "
					"(e.g. path=src/foo.py). Whole-workspace scans are not allowed."
				),
				is_error=True,
			)
		lang = str(raw.get("language") or "auto").strip().lower() or "auto"
		if lang not in ("auto", "python", "typescript", "javascript"):
			lang = "auto"

		target = filesystem.expand_to_abs(path_raw, cwd=self._cwd)
		if not self.check_permissions({"path": target}):
			return ToolResult(content="permission denied", is_error=True)

		if not os.path.exists(target):
			return ToolResult(content=f"path not found: {target}", is_error=True)

		abort.raise_if_aborted()
		backends, notes = self._select_backends(target, lang)
		if not backends:
			msg = "No diagnostics backend available."
			if notes:
				msg = msg + "\n" + "\n".join(notes)
			return ToolResult(content=msg, is_error=False)

		lines: list[str] = []
		used: list[str] = []
		import asyncio

		for name, runner in backends:
			abort.raise_if_aborted()
			used.append(name)
			try:
				# runner 是同步 subprocess.run（ruff/tsc 最长 30s）——必须挪
				# 线程，否则整个事件循环（所有会话）被冻结到超时。
				lines.extend(await asyncio.to_thread(runner, target))
			except subprocess.TimeoutExpired:
				lines.append(
					f"{target}:0:0: error: {name} timed out after {_TIMEOUT_S}s"
				)
			except Exception as e:  # noqa: BLE001
				lines.append(f"{target}:0:0: error: {name} failed: {e}")

		return ToolResult(content=_format_result(lines, used, notes), is_error=False)

	def _select_backends(
		self, target: str, lang: str
	) -> tuple[list[tuple[str, Any]], list[str]]:
		notes: list[str] = []
		backends: list[tuple[str, Any]] = []
		want_py = lang in ("auto", "python")
		want_ts = lang in ("auto", "typescript", "javascript")

		if want_py and _looks_python(target, lang):
			ruff = shutil.which("ruff")
			if ruff:
				backends.append(("ruff", lambda t, r=ruff: _run_ruff(r, t)))
			else:
				backends.append(("py_compile", _run_py_compile))
				if lang == "python":
					notes.append("ruff not on PATH; using py_compile (syntax only).")

		if want_ts and _looks_typescript(target, lang):
			tsc = shutil.which("tsc") or _find_local_tsc(target, self._cwd)
			tsconfig = _find_tsconfig(target, self._cwd)
			if tsc and (tsconfig or Path(target).is_file()):
				backends.append(
					("tsc", lambda t, b=tsc, c=tsconfig: _run_tsc(b, c, t))
				)
			else:
				missing = []
				if not tsc:
					missing.append("tsc not on PATH or node_modules/.bin")
				if not tsconfig and not Path(target).is_file():
					missing.append("no tsconfig.json found")
				notes.append("TypeScript backend skipped: " + "; ".join(missing))

		if not backends and lang == "auto":
			p = Path(target)
			if p.is_file() and p.suffix.lower() == ".py":
				backends.append(("py_compile", _run_py_compile))
			elif p.is_dir() and _shallow_has(p, {".py"}):
				backends.append(("py_compile", _run_py_compile))
			else:
				notes.append(
					"No matching language backend for this path. "
					"Set language=python|typescript or install ruff/tsc."
				)
		return backends, notes


def _shallow_has(root: Path, suffixes: set[str]) -> bool:
	"""True if any matching file within _MAX_DEPTH (no deep rglob)."""
	try:
		for dirpath, dirnames, filenames in os.walk(root):
			rel = os.path.relpath(dirpath, root)
			depth = 0 if rel == "." else rel.count(os.sep) + 1
			if depth > _MAX_DEPTH:
				dirnames[:] = []
				continue
			for name in filenames:
				if Path(name).suffix.lower() in suffixes:
					return True
	except OSError:
		return False
	return False


def _looks_python(target: str, lang: str) -> bool:
	if lang == "python":
		return True
	p = Path(target)
	if p.is_file():
		return p.suffix.lower() == ".py"
	if p.is_dir():
		return _shallow_has(p, {".py"})
	return False


def _looks_typescript(target: str, lang: str) -> bool:
	if lang in ("typescript", "javascript"):
		return True
	p = Path(target)
	if p.is_file():
		return p.suffix.lower() in _TS_EXTS
	if p.is_dir():
		return (_find_tsconfig(target, str(p)) is not None) or _shallow_has(
			p, _TS_EXTS
		)
	return False


def _find_tsconfig(target: str, cwd: str) -> str | None:
	start = Path(target)
	if start.is_file():
		start = start.parent
	for base in (start, Path(cwd)):
		cur = base
		for _ in range(8):
			cand = cur / "tsconfig.json"
			if cand.is_file():
				return str(cand)
			if cur.parent == cur:
				break
			cur = cur.parent
	return None


def _iter_py_files(target: str) -> list[Path]:
	p = Path(target)
	if p.is_file():
		return [p] if p.suffix.lower() == ".py" else []
	out: list[Path] = []
	try:
		for dirpath, dirnames, filenames in os.walk(p):
			rel = os.path.relpath(dirpath, p)
			depth = 0 if rel == "." else rel.count(os.sep) + 1
			if depth > _MAX_DEPTH:
				dirnames[:] = []
				continue
			# 跳过噪音目录
			dirnames[:] = [
				d
				for d in dirnames
				if d not in {".git", "node_modules", "__pycache__", ".venv", "venv"}
			]
			for name in filenames:
				if name.endswith(".py"):
					out.append(Path(dirpath) / name)
					if len(out) >= _MAX_FILES:
						return out
	except OSError:
		return out
	return out


def _run_py_compile(target: str) -> list[str]:
	out: list[str] = []
	for f in _iter_py_files(target):
		try:
			src = f.read_text(encoding="utf-8", errors="replace")
			ast.parse(src, filename=str(f))
		except SyntaxError as e:
			out.append(f"{f}:{e.lineno or 0}:{e.offset or 0}: error: {e.msg}")
		except OSError as e:
			out.append(f"{f}:0:0: error: {e}")
	return out


def _run_ruff(ruff: str, target: str) -> list[str]:
	proc = subprocess.run(
		[ruff, "check", "--output-format", "json", target],
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=_TIMEOUT_S,
		check=False,
	)
	raw = (proc.stdout or "").strip()
	if not raw:
		err = (proc.stderr or "").strip()
		if proc.returncode != 0 and err:
			return [f"{target}:0:0: error: ruff: {err[:500]}"]
		return []
	try:
		items = json.loads(raw)
	except json.JSONDecodeError:
		return [f"{target}:0:0: error: ruff returned non-JSON output"]
	out: list[str] = []
	if not isinstance(items, list):
		return out
	for it in items:
		if not isinstance(it, dict):
			continue
		loc = it.get("location") or {}
		row = loc.get("row") or 0
		col = loc.get("column") or 0
		code = it.get("code") or ""
		msg = it.get("message") or ""
		fp = it.get("filename") or target
		sev = "warning" if str(code).startswith("W") else "error"
		out.append(f"{fp}:{row}:{col}: {sev}: {code} {msg}".strip())
	return out


def _find_local_tsc(target: str, cwd: str) -> str | None:
	"""沿 tsconfig 同款链条找项目本地 node_modules/.bin/tsc（PATH 外也能用）。

	Diagnostics 之前只认 PATH 上的 tsc，GUI/打包环境 PATH 无全局 tsc 时 TypeScript
	后端恒落空（2026-09-09 会话实测：写测试期间类型检查死掉）。本地优先于全局，
	与 `npm test` 的可复现面一致。
	"""
	start = Path(target)
	if start.is_file():
		start = start.parent
	bases: list[Path] = []
	for base in (start, Path(cwd)):
		cur = base
		for _ in range(8):
			if cur not in bases:
				bases.append(cur)
			if cur.parent == cur:
				break
			cur = cur.parent
	cands: list[str] = []
	if os.name == "nt":
		cands = ["tsc.cmd", "tsc.exe", "tsc.ps1", "tsc"]
	else:
		cands = ["tsc"]
	for base in bases:
		bin_dir = base / "node_modules" / ".bin"
		for cand in cands:
			p = bin_dir / cand
			if p.is_file():
				return str(p)
	return None


def _run_tsc(tsc: str, tsconfig: str | None, target: str) -> list[str]:
	p = Path(target)
	# 路径为 TS/JS 文件时优先做单文件检查。
	if p.is_file() and p.suffix.lower() in _TS_EXTS:
		cmd = [tsc, "--noEmit", "--pretty", "false", str(p)]
		cwd = str(p.parent)
	elif tsconfig:
		cmd = [tsc, "--noEmit", "-p", tsconfig, "--pretty", "false"]
		cwd = str(Path(tsconfig).parent)
	else:
		return [f"{target}:0:0: error: tsc needs a file or tsconfig.json"]

	if os.name == "nt" and tsc.lower().endswith((".cmd", ".bat")):
		# Windows 上 .cmd/.bat 需经 cmd.exe 启动（直接 CreateProcess 报 193）。
		cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", *cmd]

	proc = subprocess.run(
		cmd,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=_TIMEOUT_S,
		check=False,
		cwd=cwd,
	)
	text = (proc.stdout or "") + (proc.stderr or "")
	out: list[str] = []
	target_norm = os.path.normcase(os.path.abspath(target))
	for line in text.splitlines():
		line = line.strip()
		if not line:
			continue
		if ": error TS" not in line and ": warning TS" not in line:
			continue
		parsed = _parse_tsc_line(line)
		if not parsed:
			continue
		fp, row, col, sev, msg = parsed
		fp_norm = os.path.normcase(os.path.abspath(fp))
		if p.is_file():
			if fp_norm != target_norm:
				continue
		elif p.is_dir():
			if fp_norm != target_norm and not fp_norm.startswith(target_norm + os.sep):
				continue
		out.append(f"{fp}:{row}:{col}: {sev}: {msg}")
	return out


def _parse_tsc_line(line: str) -> tuple[str, int, int, str, str] | None:
	try:
		if "): " not in line:
			return None
		left, right = line.split("): ", 1)
		if "(" not in left:
			return None
		fp, loc = left.rsplit("(", 1)
		parts = loc.split(",")
		row = int(parts[0])
		col = int(parts[1]) if len(parts) > 1 else 0
		sev = "error" if right.lower().startswith("error") else "warning"
		return fp.strip(), row, col, sev, right
	except (ValueError, IndexError):
		return None


def _format_result(lines: list[str], used: list[str], notes: list[str]) -> str:
	header = f"backends: {', '.join(used)}"
	parts = [header]
	if notes:
		parts.extend(notes)
	if not lines:
		parts.append("No diagnostics.")
		return "\n".join(parts)
	kept = lines[:_MAX_LINES]
	truncated = len(lines) > _MAX_LINES
	text = "\n".join(kept)
	if len(text) > _MAX_CHARS:
		text = text[:_MAX_CHARS]
		truncated = True
	parts.append(text)
	if truncated:
		extra = max(0, len(lines) - len(kept))
		parts.append(f"… truncated ({extra} more)" if extra else "… truncated")
	return "\n".join(parts)
