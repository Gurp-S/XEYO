"""Grep 与 Glob 同源挂载 `.agentignore`（2026-10-05）。

工具描述（grep prompt）早就承诺 ".agentignore/secret files are auto-skipped"，
glob_tool 已接、grep 未接 ⇒ 描述对模型说谎、同族两件语义不一致。
"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from tools.glob_tool.glob_tool import GlobTool
from tools.grep_tool.grep_tool import GrepTool


@pytest.fixture()
def work(tmp_path):
	(tmp_path / ".agentignore").write_text(
		"ignored_secret.txt\nskipdir/\n", encoding="utf-8"
	)
	(tmp_path / "keep.txt").write_text("needle here\n", encoding="utf-8")
	(tmp_path / "ignored_secret.txt").write_text("needle secret\n", encoding="utf-8")
	(tmp_path / "skipdir").mkdir()
	(tmp_path / "skipdir" / "x.txt").write_text("needle inner\n", encoding="utf-8")
	return tmp_path


async def _grep(work, **args):
	r = await GrepTool(cwd=str(work)).execute(
		{"pattern": "needle", "path": ".", "output_mode": "content", **args},
		AbortController(),
	)
	assert not r.is_error, r.content
	return r


@pytest.mark.asyncio
async def test_grep_honours_agentignore(work) -> None:
	r = await _grep(work)
	assert "keep.txt" in r.content, r.content
	assert "ignored_secret.txt" not in r.content, r.content
	assert "skipdir" not in r.content, r.content


@pytest.mark.asyncio
async def test_glob_and_grep_agree_on_agentignore(work) -> None:
	"""同源判据：同一工作区，两件对"被 ignore 的文件"说同一句话。"""
	g = await GlobTool(cwd=str(work)).execute(
		{"pattern": "**/*.txt", "path": "."}, AbortController()
	)
	assert "ignored_secret.txt" not in g.content, g.content
	assert "keep.txt" in g.content, g.content


@pytest.mark.asyncio
async def test_without_agentignore_no_change(tmp_path) -> None:
	"""方向控制：没有 .agentignore 时，命中集不许变。"""
	(tmp_path / "keep.txt").write_text("needle here\n", encoding="utf-8")
	(tmp_path / "other.txt").write_text("needle other\n", encoding="utf-8")
	r = await GrepTool(cwd=str(tmp_path)).execute(
		{"pattern": "needle", "path": ".", "output_mode": "content"},
		AbortController(),
	)
	assert r.is_error is False, r.content
	assert "keep.txt" in r.content and "other.txt" in r.content, r.content
