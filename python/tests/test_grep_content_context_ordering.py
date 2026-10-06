"""Grep content+context 的输出形态：分串行 / 排序 / 相对化（2026-10-05）。

修前实测（探针）：
- `--` 分串行被排到输出最顶端；
- context 行（`path-13-text` 形态）解析不出路径 ⇒ 按整行字符串排序、
  绝对路径原样泄漏、且与 match 行彻底分离（match 全在底部）。
"""

from __future__ import annotations

import re

import pytest

from engine.abort import AbortController
from tools.grep_tool.grep_tool import GrepTool


@pytest.fixture()
def work(tmp_path):
	for name in ("a_low.txt", "b_low.txt"):
		lines = [f"{name} line {i}" for i in range(1, 21)]
		lines[4] = "TARGET here"
		lines[14] = "TARGET later"
		(tmp_path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
	return tmp_path


async def _run(work, **args):
	r = await GrepTool(cwd=str(work)).execute(
		{"pattern": "TARGET", "path": ".", "output_mode": "content", **args},
		AbortController(),
	)
	assert not r.is_error, r.content
	return r


@pytest.mark.asyncio
async def test_no_group_separators_and_no_nul_in_output(work) -> None:
	r = await _run(work, context=2)
	assert "--" not in r.content.splitlines(), r.content
	assert "\0" not in r.content, "NUL 定界是内部形态，不得进模型可见面"


@pytest.mark.asyncio
async def test_context_lines_are_relativized(work) -> None:
	r = await _run(work, context=2)
	assert str(work) not in r.content, "context 行的绝对路径泄漏"
	assert "a_low.txt-3-" in r.content, r.content
	assert "a_low.txt:5:TARGET here" in r.content, r.content


@pytest.mark.asyncio
async def test_context_and_matches_interleave_by_line_number(work) -> None:
	r = await _run(work, context=2)
	nums = [int(m.group(1)) for m in re.finditer(r"a_low\.txt[:-](\d+)[:-]", r.content)]
	assert nums == [3, 4, 5, 6, 7, 13, 14, 15, 16, 17], (nums, r.content)


@pytest.mark.asyncio
async def test_match_only_output_shape_unchanged(work) -> None:
	"""方向控制：不带 context 的命中行形态保持（相对路径 + :num:）。"""
	r = await _run(work)
	assert "a_low.txt:5:TARGET here" in r.content, r.content
	assert "\0" not in r.content, r.content
	assert "--" not in r.content.splitlines(), r.content
