"""Main-flow guarantees independent of retired experimental switches."""
from copy import deepcopy
from pathlib import Path

import pytest

from memory.working import WorkingSnapshot, flush, hydrate
from memory.runtime import force_compact, project_for_model
from tools.catalog import build_default_registry
from tools.compact_description import DESCRIPTION
from tests.wsc.test_task_continuity import receipt, task


def test_default_catalog_exposes_complete_compact_description(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "0")
    schema = next(s for s in build_default_registry(cwd=str(tmp_path)).schemas() if s["name"] == "Compact")
    assert schema["description"] == DESCRIPTION
    assert schema["input_schema"]["additionalProperties"] is False


def test_capacity_fallback_has_no_model_name_guess(monkeypatch):
    from engine.query_engine import _default_context_limit
    monkeypatch.delenv("XEYO_CONTEXT_LIMIT", raising=False)
    assert _default_context_limit("openai", "gpt-4.1") is None
    assert _default_context_limit("deepseek", "unknown") is None
    monkeypatch.setenv("XEYO_CONTEXT_LIMIT", "1000000")
    assert _default_context_limit("openai", "any") == 1000000
    monkeypatch.setenv("XEYO_CONTEXT_LIMIT", "0")
    assert _default_context_limit("openai", "any") is None


@pytest.mark.parametrize("native", [False, True])
def test_force_preserves_declared_continuity_unconsumed_output_and_restart(tmp_path, monkeypatch, native):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "0")
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "0")
    from memory import wsc_projection
    wsc_projection._STATE.clear()
    rows = [{"role": "user", "id": "plan", "content": "当前任务：接线并验收"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "verify", "name": "Bash", "input": {"command": "pytest checks.py"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "verify", "content": "12 passed", "is_error": False}]}]
    rows += receipt("todo", [task("wiring", "completed"), task("acceptance")],
                    {"objective": "接线并验收", "context_message_ids": ["plan"],
                     "decisions": ["保留确定性算法"], "verification_call_ids": ["verify"]})
    for i in range(55):
        rows += [{"role": "assistant", "content": [{"type": "tool_use", "id": "obs-" + str(i), "name": "Read", "input": {"file_path": "observations.txt"}}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "obs-" + str(i), "content": "观察 " + str(i) + "x" * 1400}]},
                 {"role": "assistant", "content": "observed"},
                 {"role": "user", "content": "继续 " + str(i)}]
    rows += [{"role": "assistant", "content": [{"type": "tool_use", "id": "pending", "name": "Read", "input": {"file_path": "result.txt"}}]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "pending", "content": "fresh result " + "z" * 13000}]}]
    original = deepcopy(rows)
    working = WorkingSnapshot(session_id="main-" + str(native))
    before = project_for_model(rows, working, context_limit=1000000, capacity_managed=True, include_memory_index=False, cwd=tmp_path)
    assert working.compact_cursor == 0 and "fresh result" in str(before)
    after = force_compact(rows, working, cwd=tmp_path)
    assert working.compact_cursor > 5
    for value in ("接线并验收", "acceptance", "保留确定性算法", "verify", "12 passed"):
        assert value in after[0]["content"]
    assert rows[-1]["content"][0]["content"] in str(after)
    assert "Read(file_path=" in after[0]["content"]
    files = {p: p.read_bytes() for p in tmp_path.rglob("*.txt")}
    assert files
    flush(working.session_id, working)
    restored = hydrate(working.session_id)
    wsc_projection._STATE.clear()
    resumed = project_for_model(rows, restored, context_limit=1000000, capacity_managed=True, include_memory_index=False, cwd=tmp_path)
    assert resumed[0] == after[0]
    assert all(p.read_bytes() == content for p, content in files.items())
    assert rows == original
