"""Unfolded committed output is preserved, frozen representations are not reset."""
from copy import deepcopy

import pytest

from engine.compact import project, project_incremental, build_tool_use_names
from memory.wsc_projection import _emit
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


def rows(error=False):
    return [{"role": "assistant", "content": [{"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": "task.md"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "read", "content": "a" * 7_000 + "\nreceipt_key=7391\n" + "z" * 7_000,
                                          "is_error": error, "execution": {"status": "error" if error else "ok"}}]},
            {"role": "assistant", "content": "observed"}]


@pytest.mark.parametrize("error", [False, True])
def test_consumed_output_is_not_shortened_by_c0_or_optional_offload(monkeypatch, tmp_path, error):
    source = rows(error)
    original = deepcopy(source)
    monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "0")
    monkeypatch.setenv("XEYO_TOOL_OFFLOAD", "0")
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "0")
    baseline = project(source, cwd=tmp_path)
    assert baseline == source
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    monkeypatch.setenv("XEYO_TOOL_OFFLOAD", "1")
    monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
    after = project(source, cwd=tmp_path)
    assert after == source
    assert after[1] is source[1]
    assert source == original
    assert not (tmp_path / ".xeyo_offload").exists()


def test_incremental_tail_and_native_wsc_emission_preserve_same_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    source = rows()
    names = build_tool_use_names(source[:1])
    tail, _ = project_incremental(source[1:], base_len=1, frozen_until=0, id_to_name=names, cwd=tmp_path)
    assert [source[0]] + tail == source
    emitted = _emit("immutable old head", source, 0, 0, cwd=tmp_path)
    assert emitted[0]["content"] == "immutable old head"
    assert "receipt_key=7391" in str(emitted[2])
    assert emitted[2]["content"][0]["content"].split("\n", 1)[1] == source[1]["content"][0]["content"]


def test_frozen_result_representation_and_original_source_stay_unchanged(monkeypatch, tmp_path):
    source = rows()
    original = deepcopy(source)
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "0")
    before = project(source, frozen_until=2, cwd=tmp_path)
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    assert project(source, frozen_until=2, cwd=tmp_path) == before
    assert source == original


def test_execution_output_budget_still_spills_losslessly(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / "spill"))
    class Tool:
        name = "OutputProbe"
        output_budget = 10_000
    registry = ToolRegistry()
    raw = "a" * 12_000 + "\nreceipt_key=4827\n" + "b" * 12_000
    result = registry._apply_output_budget(Tool(), ToolResult(raw), session_id="probe")
    from pathlib import Path
    assert result.metadata["spilled"]
    assert Path(result.metadata["spill_path"]).read_text(encoding="utf-8") == raw
    source = rows()
    source[1]["content"][0]["content"] = result.content
    assert project(source)[1]["content"][0]["content"] == result.content
    assert "full output:" in result.content
