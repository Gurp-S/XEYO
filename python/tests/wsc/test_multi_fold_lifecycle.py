"""Committed task transitions across true folds, publication and restart."""
from copy import deepcopy

import pytest

from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot, flush, hydrate
from tests.wsc.test_task_continuity import receipt, task


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("large", [False, True])
def test_multiple_folds_keep_latest_evidence_then_terminal_then_new_task(monkeypatch, tmp_path, native, large):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    from memory import wsc_projection
    wsc_projection._STATE.clear()
    rows = [{"role": "user", "id": "old", "content": "顺口提旧启动问题"},
            {"role": "user", "id": "plan", "content": "当前任务A：精度验收；历史启动问题只是背景"}]
    working = WorkingSnapshot(session_id="multi-fold-" + str(native))
    published = {}

    def fold_and_restart(stage):
        for index in range(18):
            rows.append({"role": "assistant", "content": f"已观察 {stage}/{index} " + ("archive field " * 300 if large else "")})
        original = deepcopy(rows)
        old_cursor = working.compact_cursor
        emitted = force_compact(rows, working, cwd=tmp_path)
        assert bool(wsc_projection._STATE) == (native and large)
        assert working.compact_cursor > old_cursor
        assert rows == original
        assert all(path.read_bytes() == body for path, body in published.items())
        published.update({path: path.read_bytes() for path in tmp_path.rglob("*.txt")})
        flush(working.session_id, working)
        recovered = hydrate(working.session_id)
        wsc_projection._STATE.clear()
        resumed = project_for_model(rows, recovered, context_limit=1_000_000,
                                    capacity_managed=True, include_memory_index=False, cwd=tmp_path)
        assert resumed[0] == emitted[0]
        working.__dict__.update(recovered.__dict__)
        return emitted[0]["content"]

    def evidence(identity, text, error):
        rows.extend([
            {"role": "assistant", "content": [{"type": "tool_use", "id": identity, "name": "Bash", "input": {"command": "verify"}}]},
            {"role": "tool", "tool_call_id": identity, "content": [{"type": "tool_result", "tool_use_id": identity,
                "content": text, "is_error": error, "execution": {"status": "error" if error else "ok"}}]},
        ])

    evidence("v1", "revision-1 failed", True)
    rows.extend(receipt("cp1", [task("verify", "in_progress", "验收当前修订")],
        {"objective": "任务A", "context_message_ids": ["plan"], "decisions": ["修订1规则"], "verification_call_ids": ["v1"]}))
    first = fold_and_restart("first")
    assert '目标（声明）: "任务A"' in first
    assert '"call_id":"v1"' in first and "revision-1 failed" in first

    evidence("v2", "revision-2 failed", True)
    rows.extend(receipt("cp2", [task("verify", "in_progress", "验收当前修订")],
        {"objective": "任务A", "context_message_ids": ["plan"], "decisions": ["修订2规则"], "verification_call_ids": ["v2"]}))
    second = fold_and_restart("revision")
    assert '目标（声明）: "任务A"' in second
    assert '"call_id":"v2"' in second and "revision-2 failed" in second
    # Old evidence can stay archived/unresolved; it cannot remain the checkpoint's current binding.
    handoff = second.split("[UNRESOLVED]", 1)[0]
    assert "修订2规则" in handoff and "修订1规则" not in handoff

    evidence("v3", "revision-3 passed", False)
    rows.extend(receipt("cp3", [task("verify", "completed", "验收当前修订")]))
    terminal = fold_and_restart("terminal")
    assert "终态任务（已提交声明）" in terminal
    assert '目标（声明）: "任务A"' not in terminal
    terminal_handoff = terminal.split("[UNRESOLVED]", 1)[0]
    assert '"call_id":"v2"' in terminal_handoff and "revision-2 failed" in terminal_handoff
    assert "检查点绑定验收" in terminal_handoff

    rows.append({"role": "user", "id": "plan-b", "content": "任务B详细定义，验收码9271"})
    rows.extend(receipt("cp4", [task("next", "in_progress", "新任务实现")],
        {"objective": "任务B", "context_message_ids": ["plan-b"], "decisions": ["新任务规则"]}))
    current = fold_and_restart("new-task")
    assert '目标（声明）: "任务B"' in current
    handoff = current.split("[UNRESOLVED]", 1)[0]
    assert "验收码9271" in handoff and "新任务规则" in handoff
    assert "任务A" not in handoff and "修订2规则" not in handoff
    assert all(path.read_bytes() == body for path, body in published.items())
