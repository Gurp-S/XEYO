"""Receipt arrival, not invocation age, determines model consumption."""
from copy import deepcopy

import pytest

from memory.wsc_execution_boundary import protect
from tests.wsc._fixtures import msg_asst_use, msg_tool


def test_late_result_after_assistant_text_protects_original_parallel_frame():
    use = msg_asst_use("early", "Bash", {"command": "verify"})
    use["content"].append({"type": "tool_use", "id": "late", "name": "Read", "input": {"file_path": "spec"}})
    rows = [{"role": "user", "content": "规范"}, use, msg_tool("early", "Bash", "passed"),
            {"role": "assistant", "content": "已看到第一条"}, msg_tool("late", "Read", "完整详细规范")]
    assert protect(rows, len(rows)) == 1
    assert protect(rows + [{"role": "assistant", "content": "已看到全部"}], len(rows) + 1) == len(rows) + 1


def test_late_prior_result_and_new_invocation_protect_earliest_origin():
    rows = [msg_asst_use("old", "Read", {}), {"role": "assistant", "content": "继续"},
            msg_asst_use("new", "Read", {}), msg_tool("old", "Read", "late"), msg_tool("new", "Read", "new")]
    assert protect(rows, 5) == 0


def test_unknown_and_conflicting_identities_are_not_assumed_consumed():
    rows = [{"role": "assistant", "content": "记录"}, msg_tool("missing", "Read", "late")]
    assert protect(rows, 2) == 1
    rows = [msg_asst_use("same", "Read", {}), msg_asst_use("same", "Read", {}),
            {"role": "assistant", "content": "记录"}, msg_tool("same", "Read", "late")]
    assert protect(rows, 4) == 0


@pytest.mark.parametrize("native", [False, True])
def test_real_force_and_restart_preserve_late_result_and_source_rows(monkeypatch, tmp_path, native):
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory import wsc_projection
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    wsc_projection._STATE.clear()
    rows = [{"role": "assistant", "content": "归档记录 " + "x" * 1600} for _ in range(30)]
    start = len(rows)
    rows += [msg_asst_use("late", "Read", {"file_path": "spec.txt"}),
             {"role": "assistant", "content": "先前状态"}, msg_tool("late", "Read", "规范原文 " + "z" * 13000)]
    rows += [{"role": "user", "content": "追加事实"} for _ in range(10)]
    original = deepcopy(rows)
    working = WorkingSnapshot(session_id="late-receipt-" + str(native))
    emitted = force_compact(rows, working, cwd=tmp_path)
    assert working.compact_cursor == start
    assert rows == original
    assert rows[start + 2]["content"][0]["content"] in str(emitted)
    old_objects = {path: path.read_bytes() for path in tmp_path.rglob("*.txt")}
    flush(working.session_id, working)
    recovered = hydrate(working.session_id)
    wsc_projection._STATE.clear()
    resumed = project_for_model(rows, recovered, context_limit=1_000_000, capacity_managed=True,
                                include_memory_index=False, cwd=tmp_path)
    assert resumed == emitted
    assert all(path.read_bytes() == body for path, body in old_objects.items())
