"""Explicit folds archive sparse tool histories without sacrificing evidence."""
from copy import deepcopy
from pathlib import Path

import pytest

from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot
from memory.wsc_request_timing import prepare
from memory.wsc_timing import request_measure
from tests.wsc.test_task_continuity import receipt, task


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("checkpoint", [False, True])
def test_sparse_tools_capacity_fold_and_exact_archive(tmp_path, monkeypatch, native, checkpoint):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    from memory import wsc_projection
    wsc_projection._STATE.clear()
    rows = [{"role": "user", "id": "plan", "content": "当前目标：核验这次交接"}]
    if checkpoint:
        rows += receipt("todo", [task()], {"objective": "核验这次交接", "context_message_ids": ["plan"], "decisions": ["保留原始存档"]})
    for i in range(80):
        rows += [{"role": "assistant", "content": "已观察事实 " + str(i) + "x" * 2000},
                 {"role": "user", "content": "继续 " + str(i)}]
    rows += [{"role": "assistant", "content": [{"type": "tool_use", "id": "new", "name": "Read", "input": {"file_path": "result.txt"}}]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "new", "content": "尚未消费 " + "z" * 5000}]}]
    original = deepcopy(rows)
    working = WorkingSnapshot(session_id=f"sparse-{native}-{checkpoint}")
    before = project_for_model(rows, working, context_limit=1000000, capacity_managed=True, include_memory_index=False, cwd=tmp_path)
    assert working.compact_cursor == 0
    assert request_measure(before, [], context_limit=45000).action == "capacity"
    prepared = prepare(before, [], working, context_limit=45000, build=lambda value: value,
                       render=lambda value, text: value + [{"role": "system", "content": text}],
                       compact=lambda: force_compact(rows, working, cwd=tmp_path))
    assert prepared.facts["automatic_attempts"] == 1
    assert prepared.facts["after"]["timing_action"] == "keep"
    assert working.compact_cursor > 100
    assert rows[-1]["content"][0]["content"] in str(prepared.messages)
    if checkpoint:
        assert "保留原始存档" in prepared.messages[0]["content"]
    assert "Read(file_path=" in prepared.messages[0]["content"]
    archived = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.txt"))
    assert rows[3 if checkpoint else 1]["content"] in archived
    assert rows == original
