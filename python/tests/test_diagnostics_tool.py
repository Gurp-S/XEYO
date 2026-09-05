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
	assert "No diagnostics" in r.content or "backends:" in r.content


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
