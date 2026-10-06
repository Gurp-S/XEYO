"""Read 的行语义与默认截断提示（2026-10-05）。

修前实测（探针）：
- ``"a\\nb\\n"`` 渲染出 phantom 第 3 行（``3→``），total_lines=3；
- 2100 行文件无 limit 读被 2000 行上限**静默**截断，模型看不到任何提示。
"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from tools.file_read_tool.file_read_tool import FileReadTool


async def _read(tmp_path, name, text, **args):
	p = tmp_path / name
	p.write_text(text, encoding="utf-8")
	r = await FileReadTool(cwd=str(tmp_path)).execute(
		{"file_path": name, **args}, AbortController()
	)
	assert not r.is_error, r.content
	return r


@pytest.mark.asyncio
async def test_trailing_newline_is_not_a_phantom_line(tmp_path) -> None:
	r = await _read(tmp_path, "a.txt", "a\nb\n")
	assert r.content.count("→") == 2, r.content
	assert "3→" not in r.content, r.content


@pytest.mark.asyncio
async def test_without_trailing_newline_same_count(tmp_path) -> None:
	r = await _read(tmp_path, "b.txt", "a\nb")
	assert r.content.count("→") == 2, r.content


@pytest.mark.asyncio
async def test_trailing_blank_line_is_a_real_line(tmp_path) -> None:
	r = await _read(tmp_path, "c.txt", "a\nb\n\n")
	assert r.content.count("→") == 3, r.content


@pytest.mark.asyncio
async def test_shorter_than_offset_counts_real_lines(tmp_path) -> None:
	r = await _read(tmp_path, "d.txt", "a\nb\n", offset=5)
	assert "has 2 lines" in r.content, r.content
	assert "has 3 lines" not in r.content, r.content


@pytest.mark.asyncio
async def test_default_cap_states_the_truncation(tmp_path) -> None:
	text = "\n".join(f"L{i}" for i in range(2100)) + "\n"
	r = await _read(tmp_path, "big.txt", text)
	assert "this view shows lines 1-2000" in r.content, r.content[-300:]
	assert "2100" in r.content, r.content[-300:]


@pytest.mark.asyncio
async def test_explicit_limit_has_no_default_cap_note(tmp_path) -> None:
	text = "\n".join(f"L{i}" for i in range(2100)) + "\n"
	r = await _read(tmp_path, "big2.txt", text, limit=5)
	assert r.content.count("→") == 5, r.content
	assert "other portions" not in r.content, r.content
	assert "2100" not in r.content, r.content
