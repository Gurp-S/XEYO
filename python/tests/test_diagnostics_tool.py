"""Diagnostics tool: syntax/lint loopback."""

from __future__ import annotations

import os
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
async def test_diagnostics_outside_needs_approval(tmp_path: Path) -> None:
	"""区外诊断走生产通路（registry）：无应答者即拒，且文案点名是哪一档。

	原来这条直接 `tool.execute()`，测的是"工体内不认未批准的 ASK"——那不是生产
	形态（registry 裁决后会置批准位），名字却写成"outside denied"，会把已放行的
	行为钉成契约。
	"""
	from msgtypes.message import ToolUse
	from tools.tool_registry import ToolRegistry

	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(DiagnosticsTool(cwd=str(tmp_path)))
	outside = tmp_path.parent / "outside_diag.py"
	outside.write_text("x = 1\n", encoding="utf-8")
	r = await reg.run(
		ToolUse(id="1", name="Diagnostics", input={"path": str(outside)}),
		AbortController(),
	)
	assert r.is_error
	assert "no resolver: read_outside_working_directory" in r.content


def test_diagnostics_policy_outside_asks(tmp_path: Path) -> None:
	# 第二刀：区外读（含 Diagnostics）从静默 DENY 改成 ASK + 目录级授权。
	outside = str(tmp_path.parent)
	d = evaluate_policy(
		"Diagnostics", {"path": outside}, cwd=str(tmp_path)
	)
	assert d.decision == PermissionDecision.ASK
	assert d.reason == "read_outside_working_directory"


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
			if os.name == "nt":
				(bin_dir / "tsc.cmd").write_text("@echo off\n", encoding="utf-8")
			else:
				tsc = bin_dir / "tsc"
				tsc.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
				tsc.chmod(0o755)
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


class TestBoundedScanIsDisclosed:
	"""回归：目录扫描有文件数 / 深度 / 噪音目录三重边界，一条都不能吞。

	「No diagnostics.」被模型读成「这个路径干净」，而它实际只覆盖被检查到的
	那部分文件。行数 / 字符数截断早就有 `… truncated` 说明，范围边界却没有。
	"""

	def _py(self, root: Path, rel: str) -> Path:
		f = root / rel
		f.parent.mkdir(parents=True, exist_ok=True)
		f.write_text("x = 1\n", encoding="utf-8")
		return f

	def test_file_cap_is_disclosed(self, tmp_path: Path, monkeypatch) -> None:
		from tools.diagnostics_tool import diagnostics_tool as mod

		# 跨目录：上限之外的文件必须真的没被走进去，否则"examined 数"和
		# "stopped after N"会互相矛盾。
		self._py(tmp_path, "a.py")
		self._py(tmp_path, "b.py")
		self._py(tmp_path, "sub/c.py")
		monkeypatch.setattr(mod, "_MAX_FILES", 2)
		out = mod._run_py_compile(str(tmp_path))
		text = "\n".join(out)
		assert "2 .py files examined" in text
		assert "stopped after 2 .py files" in text
		assert "c.py" not in text
		assert "No diagnostics" not in text

	def test_depth_bound_is_disclosed(self, tmp_path: Path, monkeypatch) -> None:
		from tools.diagnostics_tool import diagnostics_tool as mod

		self._py(tmp_path, "a.py")
		self._py(tmp_path, "sub/b.py")
		self._py(tmp_path, "sub/deeper/c.py")
		monkeypatch.setattr(mod, "_MAX_DEPTH", 0)
		text = "\n".join(mod._run_py_compile(str(tmp_path)))
		assert "dirs deeper than 0 levels were not walked" in text
		# 折返点之后的目录从未访问，所以不能报出一个"被排除的文件数"。
		assert "2 .py files" not in text

	def test_empty_depth_boundary_stays_silent(
		self, tmp_path: Path, monkeypatch
	) -> None:
		"""边界上只有空目录：没有东西被排除，就不该有说明。"""
		from tools.diagnostics_tool import diagnostics_tool as mod

		self._py(tmp_path, "a.py")
		(tmp_path / "empty").mkdir()
		monkeypatch.setattr(mod, "_MAX_DEPTH", 0)
		assert mod._run_py_compile(str(tmp_path)) == []

	def test_skipped_dirs_are_disclosed(self, tmp_path: Path) -> None:
		from tools.diagnostics_tool import diagnostics_tool as mod

		self._py(tmp_path, "a.py")
		self._py(tmp_path, ".venv/lib/site.py")
		text = "\n".join(mod._run_py_compile(str(tmp_path)))
		assert "skipped dirs: .venv" in text
		assert "site.py" not in text

	def test_unbounded_scan_stays_silent(self, tmp_path: Path) -> None:
		"""没有边界就没有说明——不能为了免责逢扫必附一句。"""
		from tools.diagnostics_tool import diagnostics_tool as mod

		self._py(tmp_path, "a.py")
		self._py(tmp_path, "sub/b.py")
		assert mod._run_py_compile(str(tmp_path)) == []

	async def test_capped_dir_is_not_reported_clean(
		self, tmp_path: Path, monkeypatch
	) -> None:
		import shutil

		from tools.diagnostics_tool import diagnostics_tool as mod

		for name in ("a.py", "b.py", "c.py"):
			self._py(tmp_path, name)
		monkeypatch.setattr(mod, "_MAX_FILES", 2)
		monkeypatch.setattr(shutil, "which", lambda n: None)
		tool = DiagnosticsTool(cwd=str(tmp_path))
		r = await tool.execute(
			{"path": str(tmp_path), "language": "python"},
			AbortController(),
		)
		assert not r.is_error
		assert "No diagnostics." not in r.content
		assert "stopped after 2 .py files" in r.content


class TestRuffPayloadShape:
	"""ruff 的结论读不出来时必须说「读不出」，不能落到「没有诊断」。"""

	class _Proc:
		def __init__(self, out: str) -> None:
			self.returncode, self.stdout, self.stderr = 0, out, ""

	def _run(self, monkeypatch, out: str, tmp_path: Path) -> list[str]:
		import subprocess as sp

		from tools.diagnostics_tool import diagnostics_tool as mod

		monkeypatch.setattr(sp, "run", lambda *a, **k: self._Proc(out))
		return mod._run_ruff("ruff", str(tmp_path))

	def test_non_list_json_is_not_clean(self, monkeypatch, tmp_path: Path) -> None:
		out = self._run(monkeypatch, '{"diagnostics": []}', tmp_path)
		assert out and "unexpected JSON shape" in out[0]
		assert "no diagnostics were read" in out[0]

	def test_all_entries_unreadable_is_an_error(self, monkeypatch, tmp_path: Path) -> None:
		out = self._run(monkeypatch, '["x", 3]', tmp_path)
		assert out and "2 of 2 ruff entries could not be read" in out[0]
		assert ": error:" in out[0]

	def test_partial_drop_is_a_note(self, monkeypatch, tmp_path: Path) -> None:
		out = self._run(
			monkeypatch,
			'[{"code": "F401", "message": "unused", "filename": "a.py",'
			' "location": {"row": 1, "column": 1}}, "junk"]',
			tmp_path,
		)
		assert len(out) == 2
		assert "a.py:1:1: error: F401 unused" == out[0]
		assert "1 of 2 ruff entries could not be read" in out[1]
		assert ": note:" in out[1]
