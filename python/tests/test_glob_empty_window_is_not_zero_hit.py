"""Glob 的窗口切片为空不等于"没匹配"——它自己的 metadata 里就写着整趟数。

实测（2026-10-03，3 个文件命中，`offset=50`）：

    meta = {'num_files': 0, ..., 'total_matches': 3, 'no_match': True, 'suggestion': True}
    text = 'No files found' + 免责长注脚 + 放宽建议

同一条结果里既说"整趟匹配到 3 个"又说"没有匹配"，而且 `no_match` 会被
`engine/repeat_guard.ZeroHitTracker` 计进"第 N 次空结果"注入模型注意力。
分页越界与真·零命中必须分开说。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from engine.repeat_guard import ZeroHitTracker
from tools.glob_tool.glob_tool import GlobTool

_PATTERN = "**/glb_*.txt"


@pytest.fixture
def work(tmp_path: Path) -> Path:
	for i in range(3):
		(tmp_path / f"glb_{i}.txt").write_text("x\n", encoding="utf-8")
	return tmp_path


async def _run(work: Path, **args):
	r = await GlobTool(cwd=str(work)).execute({"pattern": _PATTERN, "path": ".", **args}, AbortController())
	assert not r.is_error, r.content
	return r


@pytest.mark.asyncio
async def test_empty_window_states_the_pass_total_and_is_not_zero_hit(work: Path) -> None:
	r = await _run(work, offset=50)

	assert "No files found" not in r.content, r.content
	assert "Empty window" in r.content, r.content
	assert "matched 3" in r.content, r.content
	meta = r.metadata or {}
	assert meta.get("total_matches") == 3, meta
	assert not meta.get("no_match"), meta
	assert ZeroHitTracker.is_zero_hit("Glob", r.metadata) is False, meta


@pytest.mark.asyncio
async def test_true_zero_match_keeps_the_old_wording_and_classification(work: Path) -> None:
	"""反向对照：真的一个都没匹配到，措辞、注脚与 no_match 分类都不许变。"""
	r = await _run(work, pattern="**/absent_xyz_*.txt")

	assert "No files found" in r.content, r.content
	assert "Empty window" not in r.content, r.content
	meta = r.metadata or {}
	assert meta.get("no_match") is True, meta
	assert ZeroHitTracker.is_zero_hit("Glob", r.metadata) is True, meta


@pytest.mark.asyncio
async def test_normal_window_untouched(work: Path) -> None:
	"""反向对照 2：正常页仍报 "Found 3 files"，不被新句子污染。"""
	r = await _run(work)

	assert "Found 3 files" in r.content, r.content
	assert "Empty window" not in r.content, r.content
