"""Grep 分页越界不是"没匹配"，count 的 "total" 也不许是页内小计。

实测（2026-10-03，同一份夹具 2 文件 ×3 行命中，只换 offset/head_limit）：

- `output_mode="content", offset=50` ⇒ 文本 `"No matches found"` + 范围注脚，
  而同一趟 rg 明明匹配了 6 行；`result_no_match()` 返回 True。
- `files_with_matches` / `count` 同样越界 ⇒ `"No files found"` / `"Found 0 total
  occurrences across 0 files"`。
- `count, head_limit=1` ⇒ `"Found 3 total occurrences across 1 file"`，
  真值是 6 次 / 2 个文件——**正常翻页就在报错数**，"total" 一词描述的是页内小计。

后果不只是措辞：`execute` 把 `result_no_match()` 写成 `metadata={"no_match": True}`，
`engine/repeat_guard.ZeroHitTracker` 据此计"第 N 次空结果"并注入模型注意力（阈值 2）。
⇒ 一次成功的检索被记成空结果，模型被一句"事实"推向"这条路没有"的错误结论。

修法只补分母，不改扫描面：`GrepOutput.total_matched` = 本次分页**前**匹配到的条目数，
空页时陈述它、且不再声明零命中；count 的总数按整趟算。真·零命中措辞一字不动
（`tests/test_grep_scope_notes.py` 钉着它）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from engine.repeat_guard import ZeroHitTracker
from tools.grep_tool.grep_tool import GrepTool

_MARKER = "NEEDLE_MARKER"
_ABSENT = "zzz_no_such_literal_anywhere"
# 夹具真值：2 个文件、6 行命中；count/files 的"整趟条目数"是 2，content 是 6。
_FILES = 2
_LINES = 6


@pytest.fixture
def work(tmp_path: Path) -> Path:
	"""两份文件、共 6 行命中：越界空页与页内小计都用这同一份夹具量。"""
	for i in range(_FILES):
		(tmp_path / f"f{i}.txt").write_text(
			"\n".join(f"{_MARKER} {i}-{k}" for k in range(3)) + "\n", encoding="utf-8"
		)
	return tmp_path


async def _run(work: Path, **args):
	inp = {"pattern": args.pop("pattern", _MARKER), "path": ".", **args}
	r = await GrepTool(cwd=str(work)).execute(inp, AbortController())
	assert not r.is_error, r.content
	return r


@pytest.mark.asyncio
@pytest.mark.parametrize(
	"mode,total,unit",
	[
		("content", _LINES, "line(s)"),
		("files_with_matches", _FILES, "file(s)"),
		("count", _FILES, "file row(s)"),
	],
	ids=["content", "files", "count"],
)
async def test_paged_empty_result_is_not_reported_as_zero_match(
	work: Path, mode: str, total: int, unit: str
) -> None:
	"""越界的空页必须陈述"整趟匹配到什么"，且不得声明零命中。"""
	r = await _run(work, output_mode=mode, offset=50)

	assert "No matches found" not in r.content, r.content
	assert "No files found" not in r.content, r.content
	assert f"in this page" in r.content, r.content
	assert f"the pass matched {total} {unit} in total" in r.content, r.content
	# 端到端见证：metadata 才是 ZeroHitTracker 的唯一输入，文本对不等于分类对。
	assert not (isinstance(r.metadata, dict) and r.metadata.get("no_match")), r.metadata
	assert ZeroHitTracker.is_zero_hit("Grep", r.metadata) is False, r.metadata


@pytest.mark.asyncio
async def test_count_totals_describe_the_whole_pass_not_the_page(work: Path) -> None:
	"""分页生效时，"total" 必须是整趟的总数（真值 6 次 / 2 个文件）。"""
	r = await _run(work, output_mode="count", head_limit=1)

	assert f"Found {_LINES} total occurrences across {_FILES} files" in r.content, r.content
	assert "pagination" in r.content, "页宽信息不能因为改总数就被丢掉"


@pytest.mark.asyncio
async def test_true_zero_match_wording_is_unchanged(work: Path) -> None:
	"""反向对照：真的没有命中时，旧措辞与范围注脚必须原样保留、分类仍是零命中。"""
	for mode in ("content", "files_with_matches", "count"):
		r = await _run(work, pattern=_ABSENT, output_mode=mode)
		assert ("No matches found" in r.content) or ("No files found" in r.content), (
			mode,
			r.content,
		)
		assert "Not searched by this pass" in r.content, (mode, r.content)
		assert "in this page" not in r.content, (mode, r.content)
		assert ZeroHitTracker.is_zero_hit("Grep", r.metadata) is True, (mode, r.metadata)


@pytest.mark.asyncio
async def test_normal_page_is_not_polluted(work: Path) -> None:
	"""反向对照 2：落在命中区间内的正常页，不被新增句子污染。"""
	r = await _run(work, output_mode="content", head_limit=2)

	assert _MARKER in r.content
	assert "in this page" not in r.content, r.content
	assert r.metadata is None, r.metadata
