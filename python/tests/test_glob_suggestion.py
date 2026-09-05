"""Glob 空结果 near-miss 提示（Did you mean）的回归测试。"""

from __future__ import annotations

import shutil

import pytest

from tools.glob_tool.glob_tool import GlobInput, GlobTool


@pytest.fixture
def work(tmp_path):
	(tmp_path / "docs").mkdir()
	(tmp_path / "docs" / "agent-b.md").write_text("x", encoding="utf-8")
	return tmp_path


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_pattern_miss_suggests_real_file(work):
	"""`doc/agent_b.md`（目录与文件名双错位）应给出一条指向 docs/agent-b.md 的提示。"""
	tool = GlobTool(cwd=str(work))
	out = tool.call(GlobInput(pattern="doc/agent_b.md"))
	assert not out.filenames
	assert out.suggestion is not None
	assert "agent-b.md" in out.suggestion
	assert "docs" in out.suggestion
	text = tool.map_tool_result_to_content(out)
	assert "Did you mean:" in text
	assert "agent-b.md" in text


def test_path_miss_suggests_fuzzy_dir(work):
	"""`path="doc"` 不存在时应模糊匹配到 docs/。"""
	tool = GlobTool(cwd=str(work))
	v = tool.validate_input(GlobInput(pattern="agent_b.md", path="doc"))
	assert v["result"] is False
	assert "Did you mean docs" in v["message"]


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_normal_hit_has_no_suggestion(work):
	"""命中时绝不出提示，也不触发额外建议。"""
	tool = GlobTool(cwd=str(work))
	out = tool.call(GlobInput(pattern="agent-b.md"))
	assert out.filenames
	assert out.suggestion is None
	assert "Did you mean" not in tool.map_tool_result_to_content(out)


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_miss_without_near_match_is_silent(work):
	"""放宽搜索也无结果时，应静默（不返回建议），保持普通 No files found。"""
	tool = GlobTool(cwd=str(work))
	out = tool.call(GlobInput(pattern="zzz_nope.md"))
	assert not out.filenames
	assert out.suggestion is None
	text = tool.map_tool_result_to_content(out)
	assert "No files found" in text
	assert "Did you mean" not in text


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_empty_tip_kept(work):
	"""既有 tip（No files found + node_modules 提示）必须原样保留。"""
	tool = GlobTool(cwd=str(work))
	out = tool.call(GlobInput(pattern="zzz_nope.md"))
	text = tool.map_tool_result_to_content(out)
	assert "No files found" in text
	assert "node_modules" in text
