"""Diagnostics tool: syntax/lint loopback."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.diagnostics_tool import DiagnosticsTool


@pytest.mark.asyncio
async def test_diagnostics_requires_path(tmp_path: Path) -> None:
	tool = DiagnosticsTool(cwd=str(tmp_path))
	r = await tool.execute({}, AbortController())
	assert r.is_error
	assert "path is required" in r.content.lower()


@pytest.mark.asyncio
async def test_diagnostics_py_compile_syntax_error(tmp_path: Path) -> None:
	bad = tmp_path / "bad.py"
	bad.write_text("def x(\n", encoding="utf-8")
	tool = DiagnosticsTool(cwd=str(tmp_path))
	r = await tool.execute(
		{"path": str(bad), "language": "python"},
		AbortController(),
	)
	assert not r.is_error
	assert "error" in r.content.lower()
	assert "bad.py" in r.content


@pytest.mark.asyncio
async def test_diagnostics_clean_python(tmp_path: Path) -> None:
	ok = tmp_path / "ok.py"
	ok.write_text("x = 1\n", encoding="utf-8")
	tool = DiagnosticsTool(cwd=str(tmp_path))
	r = await tool.execute(
		{"path": str(ok), "language": "python"},
		AbortController(),
	)
	assert not r.is_error
	assert "backends:" in r.content
	assert "No diagnostics." in r.content


@pytest.mark.asyncio
async def test_diagnostics_outside_denied(tmp_path: Path) -> None:
	tool = DiagnosticsTool(cwd=str(tmp_path))
	outside = tmp_path.parent / "outside_diag.py"
	outside.write_text("x = 1\n", encoding="utf-8")
	r = await tool.execute({"path": str(outside)}, AbortController())
	assert r.is_error
	assert "permission" in r.content.lower()


def test_diagnostics_policy_outside(tmp_path: Path) -> None:
	outside = str(tmp_path.parent)
	d = evaluate_policy(
		"Diagnostics", {"path": outside}, cwd=str(tmp_path)
	)
	assert d.decision == PermissionDecision.DENY


@pytest.mark.asyncio
async def test_diagnostics_abort(tmp_path: Path) -> None:
	tool = DiagnosticsTool(cwd=str(tmp_path))
	abort = AbortController()
	abort.abort()
	with pytest.raises(Exception):
		await tool.execute({}, abort)


class TestLocalTscResolution:
	"""回归：PATH 无全局 tsc 时，Diagnostics 应回落项目本地 node_modules/.bin。

	曾只认 shutil.which("tsc")——GUI 仓库的 tsc 在 gui/node_modules/.bin，
	不在 PATH → TypeScript 后端恒落空（2026-09-09 会话实测）。
	"""

	def _make_ws(self, tmp_path: Path, *, with_tsc: bool) -> tuple[Path, Path]:
		ws = tmp_path / "ws"
		src = ws / "src"
		src.mkdir(parents=True)
		target = src / "a.ts"
		target.write_text("const x: number = 1;\n", encoding="utf-8")
		if with_tsc:
			bin_dir = ws / "node_modules" / ".bin"
			bin_dir.mkdir(parents=True)
			(bin_dir / "tsc.cmd").write_text("@echo off\n", encoding="utf-8")
		return ws, target

	def test_uses_local_tsc_when_global_missing(
		self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
	) -> None:
		import shutil

		ws, target = self._make_ws(tmp_path, with_tsc=True)
		monkeypatch.setattr(shutil, "which", lambda n: None)
		tool = DiagnosticsTool(cwd=str(ws))
		backends, notes = tool._select_backends(str(target), "typescript")
		assert any(name == "tsc" for name, _ in backends), notes
		assert not any("skipped" in n for n in notes)

	def test_no_local_tsc_reports_skipped(
		self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
	) -> None:
		import shutil

		ws, target = self._make_ws(tmp_path, with_tsc=False)
		monkeypatch.setattr(shutil, "which", lambda n: None)
		tool = DiagnosticsTool(cwd=str(ws))
		backends, notes = tool._select_backends(str(target), "typescript")
		assert not backends
		assert any("tsc not on PATH" in n for n in notes)


def test_py_compile_says_nothing_was_examined(tmp_path: Path) -> None:
	"""一个文件都没看 ≠ 干净：空目录必须报成未检查。"""
	from tools.diagnostics_tool.diagnostics_tool import _run_py_compile

	(tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
	out = _run_py_compile(str(tmp_path / "notes.txt"))
	assert out and "no .py file examined" in out[0]
	empty = tmp_path / "empty"
	empty.mkdir()
	lines = _run_py_compile(str(empty))
	assert len(lines) == 1 and "nothing was checked" in lines[0]


class _Proc:
	def __init__(self, rc: int, out: str = "", err: str = "") -> None:
		self.returncode, self.stdout, self.stderr = rc, out, err


def test_ruff_failure_without_output_is_not_clean(monkeypatch, tmp_path: Path) -> None:
	"""ruff 非零退出且无 stdout/stderr：必须成为一条可见的失败事实。"""
	import subprocess as sp

	from tools.diagnostics_tool import diagnostics_tool as mod

	monkeypatch.setattr(sp, "run", lambda *a, **k: _Proc(2))
	out = mod._run_ruff("ruff", str(tmp_path))
	assert out and "ruff exited 2" in out[0] and "no output" in out[0]
	assert "No diagnostics" not in "\n".join(out)


def test_ruff_clean_run_still_reports_nothing(monkeypatch, tmp_path: Path) -> None:
	import subprocess as sp

	from tools.diagnostics_tool import diagnostics_tool as mod

	monkeypatch.setattr(sp, "run", lambda *a, **k: _Proc(0))
	assert mod._run_ruff("ruff", str(tmp_path)) == []


def test_tsc_nonzero_with_unattributed_output_is_not_clean(monkeypatch, tmp_path: Path) -> None:
	"""整体没跑成（坏 tsconfig / TS18003）时，路径过滤后的沉默不等于干净。"""
	import subprocess as sp

	from tools.diagnostics_tool import diagnostics_tool as mod

	target = tmp_path / "a.ts"
	target.write_text("export const x = 1\n", encoding="utf-8")
	other = tmp_path / "b.ts"
	other.write_text("boom\n", encoding="utf-8")

	monkeypatch.setattr(
		sp,
		"run",
		lambda *a, **k: _Proc(2, out=f"{other}:1:1 - error TS2304: Cannot find name 'boom'.\n"),
	)
	out = mod._run_tsc("tsc", str(tmp_path / "tsconfig.json"), str(target))
	assert out and "tsc exited 2" in out[0]
	assert not any(": error TS" in line for line in out)


def test_tsc_missing_binary_is_reported(tmp_path: Path) -> None:
	from tools.diagnostics_tool.diagnostics_tool import _run_tsc

	out = _run_tsc("", None, str(tmp_path / "a.ts"))
	assert out and "tsc not found" in out[0]
