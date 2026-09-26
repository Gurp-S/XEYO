"""Grep 的扫描面永远是整个搜索根：不许再出现"先算候选、只扫候选"的短路。

历史：2026-09-25 删掉 trigram 内容索引预筛。实测一次字面量查询只省 3~9ms，而建一次
索引要 142~888ms（TTL 30s）——收益不成立；代价却落在诚实上：候选集看不见 TTL 内刚
写入的文件，工具就把"没读到"答成 "No files found"，模型据此认为自己的写入没落地。
这里守住两件事：真实写入立刻可被 Grep 到，以及递给 rg 的目标始终是搜索根本身。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.grep_tool import grep_tool as mod
from tools.grep_tool.grep_tool import GrepTool


@pytest.fixture
def work(tmp_path: Path) -> Path:
	(tmp_path / "a.py").write_text("NEEDLE_ALPHA = 1\n", encoding="utf-8")
	return tmp_path


@pytest.mark.asyncio
async def test_literal_written_after_an_earlier_grep_is_found(work: Path) -> None:
	"""前一次检索不许让后一次写入变成"没有"。"""
	tool = GrepTool(cwd=str(work))
	warm = await tool.execute({"pattern": "NEEDLE_ALPHA", "path": "."}, AbortController())
	assert not warm.is_error and "a.py" in warm.content

	(work / "b.py").write_text("NEEDLE_BETA = 2\n", encoding="utf-8")
	hit = await tool.execute({"pattern": "NEEDLE_BETA", "path": "."}, AbortController())
	assert not hit.is_error, hit.content
	assert "b.py" in hit.content, hit.content


@pytest.mark.asyncio
async def test_argv_target_is_the_search_root(
	work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""真正交给 rg 的最后一个参数是搜索根，而不是某个文件列表。

	预筛复活时最先变的就是这里：目标会被换成候选文件路径。
	"""
	cmds: list[list[str]] = []

	def _spy(cmd, **kw):
		cmds.append(list(cmd))
		return []

	monkeypatch.setattr(mod, "run_ripgrep_lines", _spy)
	tool = GrepTool(cwd=str(work))
	await tool.execute(
		{"pattern": "NEEDLE_ALPHA", "path": ".", "output_mode": "files_with_matches"},
		AbortController(),
	)
	assert len(cmds) == 1, cmds
	assert cmds[0][-1] == str(work.resolve()), cmds[0]
