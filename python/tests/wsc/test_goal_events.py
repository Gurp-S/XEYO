"""Changing authoritative goal facts never rewrites an emitted source prefix."""
import json
from unittest.mock import patch

import pytest
from memory.wsc_goal_events import augment, path_for


BASELINE = {"goal_id": "g1", "revision": 1, "status": "active", "goal": "修复窗口"}


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_REQUEST_PROJECTION", "1")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))


def emit(tmp_path, messages, state, baseline=BASELINE):
    with patch("memory.wsc_goal_source.snapshot", return_value=state):
        return augment(messages, 1, 1, head="frozen", cwd=str(tmp_path), session="s",
                       lifecycle=baseline, source_layout="latest-notes-v1")[0]


def fact(status="paused", revision=2, goal_id="g1", text="修复窗口"):
    return dict(goal_id=goal_id, revision=revision, status=status, text=text)


def raw():
    return [{"role": "user", "content": "初始请求"}, {"role": "assistant", "content": "结果"}]


@pytest.mark.parametrize("status", ["paused", "completed", "blocked", "abandoned"])
def test_changed_state_is_appended_and_same_state_deduplicated(enabled, tmp_path, status):
    before = raw()
    after = emit(tmp_path, before, fact(status))
    assert after[:len(before)] == before
    assert json.loads(after[-1]["content"].split("\n", 1)[1])["status"] == status
    assert emit(tmp_path, before, fact(status)) == after
    extended = emit(tmp_path, before + [{"role": "user", "content": "新请求"}], fact(status))
    assert extended[:len(after)] == after


def test_multiple_states_at_same_source_position_are_ordered(enabled, tmp_path):
    first = emit(tmp_path, raw(), fact())
    second = emit(tmp_path, raw(), fact("active", 3))
    assert second[:len(first)] == first
    assert len(second) == len(first) + 1


@pytest.mark.parametrize("changed", [None, fact("active", 1, "g2", "新目标"), fact("active", 2)])
def test_unbinding_switching_and_revision_only_change_are_facts(enabled, tmp_path, changed):
    result = emit(tmp_path, raw(), changed)
    assert len(result) == len(raw()) + 1


def test_open_tool_pair_defers_event_until_result(enabled, tmp_path):
    use = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}
    messages = raw() + [use]
    assert emit(tmp_path, messages, fact()) == messages
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}
    closed = messages + [result]
    augmented = emit(tmp_path, closed, fact())
    assert augmented[:len(closed)] == closed
    assert augmented[-1]["name"] == "goal_state"


def test_write_failure_preserves_prior_emission_and_retry_appends(enabled, tmp_path):
    first = emit(tmp_path, raw(), fact())
    with patch("memory.wsc_goal_events._save", side_effect=OSError("disk full")):
        assert emit(tmp_path, raw(), fact("completed", 3)) == first
    final = emit(tmp_path, raw(), fact("completed", 3))
    assert final[:len(first)] == first


def test_read_failure_preserves_prior_events(enabled, tmp_path):
    first = emit(tmp_path, raw(), fact())
    with patch("memory.wsc_goal_source.snapshot", side_effect=OSError("unavailable")):
        second, _ = augment(raw(), 1, 1, head="frozen", cwd=str(tmp_path), session="s",
                            lifecycle=BASELINE, source_layout="latest-notes-v1")
    assert second == first


def test_tampered_event_ledger_is_rejected(enabled, tmp_path):
    emit(tmp_path, raw(), fact())
    path = path_for("s", str(tmp_path), "frozen", 1, "latest-notes-v1")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["events"][0]["fact"]["status"] = "completed"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="digest_mismatch"):
        emit(tmp_path, raw(), fact())


def test_default_off_adds_no_state_fact(monkeypatch, tmp_path):
    monkeypatch.delenv("XEYO_WSC_REQUEST_PROJECTION", raising=False)
    assert emit(tmp_path, raw(), fact()) == raw()


def test_goal_event_survives_c0c1_fold(enabled, tmp_path):
    """织入的状态事实穿过真实 C0/C1 折叠后逐字保留 —— 折叠不吃状态。

    对应验收项 `bound_state_survives_fold`（`evals/wsc_request_projection.py::freeze_replay`）：
    `augment()` 在 C0/C1 **之前**织入，若折叠层改写/丢弃这条 assistant 消息，
    "完成/暂停"事实就会在折叠后消失，而头字节检查看不出来（它只比头是否一致）。
    """
    from engine.compact import project as c0c1

    raw_messages = raw() + [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                           "input": {"command": "ls"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 40000}]},
    ]
    emitted = emit(tmp_path, raw_messages, fact("completed", 3))
    woven = [m for m in emitted if "[BOUND_GOAL_STATE]" in json.dumps(m, ensure_ascii=False)]
    assert woven, "状态变化后应当织入一条状态事实"
    for frozen_until in range(len(emitted) + 1):
        folded = c0c1(emitted, frozen_until=frozen_until)
        assert [m for m in folded if "[BOUND_GOAL_STATE]" in json.dumps(m, ensure_ascii=False)] == woven


def test_corrupt_ledger_cannot_silently_emit_a_shorter_prefix(enabled, tmp_path):
    from memory.wsc_projection import _emit
    from memory.wsc_goal_events import GoalEventLedgerError
    emit(tmp_path, raw(), fact())
    ledger = path_for("s", str(tmp_path), "frozen", 1, "latest-notes-v1")
    ledger.write_text("{invalid", encoding="utf-8")
    with pytest.raises(GoalEventLedgerError):
        _emit("frozen", raw(), 1, 1, cwd=str(tmp_path), session="s",
              lifecycle=BASELINE, source_layout="latest-notes-v1")


def test_missing_committed_ledger_does_not_reconstruct_a_different_prefix(enabled, tmp_path):
    from memory.wsc_goal_events import GoalEventLedgerError
    emit(tmp_path, raw(), fact())
    ledger = path_for("s", str(tmp_path), "frozen", 1, "latest-notes-v1")
    ledger.unlink()
    with pytest.raises(GoalEventLedgerError):
        emit(tmp_path, raw(), fact("completed", 3))


def test_unreadable_real_binding_is_not_treated_as_unbound(enabled, tmp_path):
    from engine.goal_state import GoalStore
    from memory.wsc_goal_source import snapshot
    store = GoalStore(str(tmp_path))
    goal = store.create(title="g", text="原目标")
    store.bind("s", goal.goal_id)
    store._binding_path("s").write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot(str(tmp_path), "s")


def test_missing_bound_goal_is_unknown_but_actual_unbinding_is_none(enabled, tmp_path):
    from engine.goal_state import GoalStore
    from memory.wsc_goal_source import snapshot
    store = GoalStore(str(tmp_path))
    goal = store.create(title="g", text="原目标")
    store.bind("s", goal.goal_id)
    store._goal_path(goal.goal_id).unlink()
    with pytest.raises(ValueError, match="bound_goal_unavailable"):
        snapshot(str(tmp_path), "s")
    store.unbind("s")
    assert snapshot(str(tmp_path), "s") is None
