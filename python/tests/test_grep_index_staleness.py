"""Grep 的内容索引预筛：读不出（空候选）不得说成"没有 files"。

事故（2026-09-25 复现）：先 Grep 一个字面量建好索引 → 写入含另一字面量的
b.py（Write/Edit 只清 glob 缓存，content index 的 TTL 是 30s）→ 立刻 Grep
新字面量 ⇒ 工具答 "No files found"，而同一时刻 `rg` 能扫到 b.py。模型据此
会认为自己的写入没落地，或认为这个词全库不存在。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.fileio import content_index
from tools.grep_tool.grep_tool import GrepTool


@pytest.fixture(autouse=True)
def _clean_index():
	content_index.clear_content_index()
	yield
	content_index.clear_content_index()


@pytest.fixture
def work(tmp_path: Path) -> Path:
	(tmp_path / "a.py").write_text("NEEDLE_ALPHA = 1\n", encoding="utf-8")
	return tmp_path


@pytest.mark.asyncio
async def test_literal_written_after_the_index_was_built_is_still_found(
	work: Path,
) -> None:
	tool = GrepTool(cwd=str(work))
	warm = await tool.execute({"pattern": "NEEDLE_ALPHA", "path": "."}, AbortController())
	assert not warm.is_error and "a.py" in warm.content

	(work / "b.py").write_text("NEEDLE_BETA = 2\n", encoding="utf-8")
	# 索引仍然新鲜：新字面量必然取不到候选——这正是旧代码据此断言"没有"的地方。
	assert content_index.lookup(str(work), "NEEDLE_BETA") == []

	hit = await tool.execute({"pattern": "NEEDLE_BETA", "path": "."}, AbortController())
	assert not hit.is_error, hit.content
	assert "b.py" in hit.content, hit.content


class _Spy:
	"""记录预筛把扫描面收窄成什么；转调真实 rg 以保持下游行为不变。"""

	def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
		from tools.grep_tool import grep_tool as mod

		self.real = mod.run_ripgrep
		self.calls: list[list[str] | None] = []
		monkeypatch.setattr(mod, "run_ripgrep", self._run)

	def _run(self, args, target, **kw):
		self.calls.append(kw.get("files"))
		return self.real(args, target, **kw)


async def _grep(work: Path, monkeypatch: pytest.MonkeyPatch, cands):
	from tools.grep_tool import grep_tool as mod

	spy = _Spy(monkeypatch)
	monkeypatch.setattr(content_index, "lookup", lambda root, pattern: cands)
	tool = GrepTool(cwd=str(work))
	r = await tool.execute({"pattern": "NEEDLE_ZZZ", "path": "."}, AbortController())
	assert not r.is_error, r.content
	assert len(spy.calls) == 1, spy.calls
	return spy.calls[0], r


@pytest.mark.asyncio
async def test_empty_candidates_do_not_shorten_the_scan(
	work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""空候选 = 索引没看到，不是全库没有 ⇒ 必须回到全量 rg（files=None）。"""
	files, r = await _grep(work, monkeypatch, [])
	assert files is None, files
	assert "No files found" in r.content


@pytest.mark.asyncio
async def test_unusable_index_does_not_shorten_the_scan(
	work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	files, _ = await _grep(work, monkeypatch, None)
	assert files is None, files


@pytest.mark.asyncio
async def test_nonempty_candidates_still_narrow_the_scan(
	work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""加速不能因为修正确性而被顺手丢掉：有候选时仍只扫候选集。"""
	files, r = await _grep(work, monkeypatch, ["a.py"])
	assert files == [os.path.normpath(str(work / "a.py"))], files
	# a.py 不含 NEEDLE_ZZZ：收窄后的 rg 仍要给出经过验证的"没有"。
	assert "No files found" in r.content, r.content
