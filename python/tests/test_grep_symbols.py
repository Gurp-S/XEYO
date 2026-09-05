"""Grep symbols 模式用例（33号计划 Step 3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.grep_tool.grep_tool import GrepTool


@pytest.fixture(autouse=True)
def _clean_cache():
	from codeindex.symbols import clear_cache

	clear_cache()
	yield
	clear_cache()


@pytest.fixture
def work(tmp_path: Path) -> Path:
	src = tmp_path / "src"
	src.mkdir()
	(src / "store.py").write_text(
		"class Store:\n"
		"	def apply(self, x):\n"
		"		return x\n"
		"\n"
		"def helper():\n"
		"	pass\n",
		encoding="utf-8",
	)
	(src / "util.ts").write_text(
		"export function alpha(): number { return 1 }\n"
		"export class Beta {\n"
		"	go() {}\n"
		"}\n",
		encoding="utf-8",
	)
	(src / "notes.md").write_text("# not code\n", encoding="utf-8")
	return tmp_path


@pytest.mark.asyncio
async def test_symbols_lists_matches_with_signature(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{"pattern": "apply|helper", "output_mode": "symbols", "path": "src"},
		AbortController(),
	)
	assert not r.is_error
	sep = "\\" if "\\" in r.content else "/"
	assert f"src{sep}store.py:2: def apply(self, x):" in r.content
	assert f"src{sep}store.py:5: def helper():" in r.content
	assert "Found 2 symbols matched" in r.content


@pytest.mark.asyncio
async def test_symbols_filters_by_glob(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": "alpha|apply",
			"output_mode": "symbols",
			"path": "src",
			"glob": "*.py",
		},
		AbortController(),
	)
	assert not r.is_error
	assert "store.py" in r.content
	assert "alpha" not in r.content


@pytest.mark.asyncio
async def test_symbols_case_insensitive_flag(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	sensitive = await tool.execute(
		{"pattern": "APPLY", "output_mode": "symbols", "path": "src"},
		AbortController(),
	)
	assert "No symbols found" in sensitive.content

	insensitive = await tool.execute(
		{
			"pattern": "APPLY",
			"output_mode": "symbols",
			"path": "src",
			"-i": True,
		},
		AbortController(),
	)
	assert "def apply" in insensitive.content


@pytest.mark.asyncio
async def test_symbols_pagination(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": "apply|helper|alpha|Beta|go",
			"output_mode": "symbols",
			"path": "src",
			"head_limit": 2,
		},
		AbortController(),
	)
	assert not r.is_error
	body_lines = [ln for ln in r.content.split("\n") if ":" in ln and "Found" not in ln]
	assert len(body_lines) == 2
	assert "limit: 2" in r.content


@pytest.mark.asyncio
async def test_symbols_empty_result_has_tip(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{"pattern": "no_such_symbol_xyz", "output_mode": "symbols", "path": "src"},
		AbortController(),
	)
	assert not r.is_error
	assert "No symbols found" in r.content


@pytest.mark.asyncio
async def test_symbols_invalid_mode_still_rejected(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{"pattern": "x", "output_mode": "bogus", "path": "src"},
		AbortController(),
	)
	assert r.is_error
	assert "invalid output_mode" in r.content


# ---- detail=folded / kinds（第 2 层输出形态优化） ----


@pytest.mark.asyncio
async def test_symbols_folded_collapses_methods(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": ".",
			"output_mode": "symbols",
			"path": "src",
			"detail": "folded",
		},
		AbortController(),
	)
	assert not r.is_error
	# 方法被折叠进容器行：apply 不再单独出现；顶层函数 helper 照常列出
	assert "def apply" not in r.content
	assert "def helper" in r.content
	assert "[+1 members" in r.content  # Store 有 1 个方法 apply
	assert "expand" in r.content.lower()  # 尾部展开提示


@pytest.mark.asyncio
async def test_symbols_folded_ts_class(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": ".",
			"output_mode": "symbols",
			"path": "src",
			"glob": "*.ts",
			"detail": "folded",
		},
		AbortController(),
	)
	assert not r.is_error
	# Beta.go 折叠进 Beta；alpha 顶层函数保留
	assert "Beta" in r.content
	assert "Found 2 symbols matched" in r.content
	assert "go() {}" not in r.content


@pytest.mark.asyncio
async def test_symbols_kinds_filter(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": ".",
			"output_mode": "symbols",
			"path": "src",
			"kinds": ["class", "interface"],
		},
		AbortController(),
	)
	assert not r.is_error
	assert "class Store" in r.content
	assert "def apply" not in r.content
	assert "def helper" not in r.content


@pytest.mark.asyncio
async def test_symbols_kinds_invalid_rejected(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": ".",
			"output_mode": "symbols",
			"path": "src",
			"kinds": ["bogus_kind"],
		},
		AbortController(),
	)
	assert r.is_error
	assert "invalid kinds" in r.content


@pytest.mark.asyncio
async def test_symbols_detail_invalid_rejected(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": ".",
			"output_mode": "symbols",
			"path": "src",
			"detail": "bogus",
		},
		AbortController(),
	)
	assert r.is_error
	assert "invalid detail" in r.content


@pytest.mark.asyncio
async def test_symbols_default_detail_unchanged(work: Path) -> None:
	# 不传 detail → 行为与折叠功能加入前完全一致（方法照常列出）
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{"pattern": "apply|helper", "output_mode": "symbols", "path": "src"},
		AbortController(),
	)
	assert not r.is_error
	assert "def apply" in r.content and "def helper" in r.content
	assert "members" not in r.content


@pytest.mark.asyncio
async def test_symbols_folded_with_pagination(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	r = await tool.execute(
		{
			"pattern": ".",
			"output_mode": "symbols",
			"path": "src",
			"detail": "folded",
			"head_limit": 1,
		},
		AbortController(),
	)
	assert not r.is_error
	body_lines = [ln for ln in r.content.split("\n") if ln.strip()]
	assert len([ln for ln in body_lines if ln.startswith("src")]) == 1
	assert "limit: 1" in r.content
