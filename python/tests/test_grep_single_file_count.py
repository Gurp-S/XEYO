"""Single-file cold discovery must retain the same count framing as directory scans."""
from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.grep_tool.grep_tool import GrepInput, GrepTool, build_rg_args
from tools.grep_tool.rg_fallback import grep_argv_from_rg, pipeline_from_rg


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["file", "directory"])
@pytest.mark.parametrize("offset", [0, 9])
async def test_positive_count_and_empty_page_remain_hits(tmp_path: Path, target: str, offset: int):
    # Three occurrences on two lines: preserve rg -c semantics.
    source = tmp_path / "冷证据 source.jsonl"
    source.write_text("anchor anchor\nother\nanchor\n", encoding="utf-8")
    result = await GrepTool(cwd=str(tmp_path)).execute(
        {"pattern": "anchor", "path": str(source if target == "file" else tmp_path),
         "output_mode": "count", "offset": offset}, AbortController())
    assert not result.is_error, result.content
    assert "Found 2 total occurrences across 1 file" in result.content
    assert "No matches" not in result.content
    assert not (result.metadata or {}).get("no_match")
    if offset:
        assert "the pass matched 1 file row(s) in total" in result.content
    else:
        assert source.name + ":2" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["file", "directory"])
async def test_absent_pattern_still_reports_zero(tmp_path: Path, target: str):
    source = tmp_path / "source.jsonl"
    source.write_text("unrelated\n", encoding="utf-8")
    result = await GrepTool(cwd=str(tmp_path)).execute(
        {"pattern": "anchor", "path": str(source if target == "file" else tmp_path),
         "output_mode": "count"}, AbortController())
    assert not result.is_error
    assert "Found 0 total occurrences across 0 files" in result.content
    assert (result.metadata or {}).get("no_match")


def test_fallback_preserves_single_file_count_framing():
    args = build_rg_args(GrepInput(pattern="anchor", output_mode="count"))
    mapped = grep_argv_from_rg(args, "/app/source.jsonl")
    assert mapped is not None
    assert "-c" in mapped
    assert "-H" in mapped
    assert mapped[-1] == "/app/source.jsonl"


def test_fallback_include_pipeline_accepts_count_filename_flag():
    args = build_rg_args(GrepInput(pattern="anchor", glob="*.jsonl", output_mode="count"))
    command = pipeline_from_rg(args, "/app")
    assert command is not None
    assert "'-H'" in command and "'-c'" in command
