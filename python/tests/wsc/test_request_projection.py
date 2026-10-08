"""Request focus is independent of guessed goal completion and literal history."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from memory.wsc_projection import production_params
from synaptic.project import project
from synaptic.budget import render_requests, render_requests_grouped, render_requests_compact


@pytest.fixture
def enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_REQUEST_PROJECTION", "1")
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "0")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))


def rows():
    return [{"role": "user", "content": "修复 ChatGPT 前台窗口；必须保留所有用户文件。"},
            {"role": "assistant", "content": "观察结果。"},
            {"role": "user", "content": "分析 WSC 压缩缺陷"}]


def build(tmp_path, messages, previous=None, **kwargs):
    return project(messages, region_end=kwargs.pop("region_end", len(messages)),
                   params=production_params(), view_path=tmp_path / "session.txt",
                   prev=previous.state if previous else None,
                   cold=previous.cold if previous else None, **kwargs)


def test_unclosed_goal_withdraws_without_completion_and_constraint_survives(enabled, tmp_path):
    result = build(tmp_path, rows())
    pins = result.result.hot.pins
    assert not any(p.key == "goal" for p in pins)
    assert next(p.text for p in pins if p.key.startswith("request:")) == rows()[-1]["content"]
    assert result.state.lifecycle["status"] is None
    assert "必须保留所有用户文件" in "\n".join(result.seeds.constraints)
    assert result.cold.expand("node://0") == (rows()[0]["content"],)


@pytest.mark.parametrize("followup", ["继续", "为什么", "总结所有修复给我", "也就是还是会出现刚才那个对话的情况"])
def test_followups_have_exact_focus_and_prior_request_recovery(enabled, tmp_path, followup):
    messages = rows() + [{"role": "user", "content": followup}]
    result = build(tmp_path, messages)
    assert result.seeds.request_text == followup
    assert result.seeds.request_source == 3
    assert result.cold.expand("node://2") == (rows()[2]["content"],)
    assert not result.seeds.goal


@pytest.mark.parametrize("status", ["active", "paused", "blocked", "completed", "abandoned"])
def test_bound_goal_is_not_replaced_by_followup(enabled, tmp_path, status):
    snapshot = {"goal_id": "g1", "revision": 8, "status": status, "text": "完整修复 WSC"}
    original = deepcopy(snapshot)
    result = build(tmp_path, rows(), goal_snapshot=snapshot)
    assert snapshot == original
    assert result.state.lifecycle["status"] == status
    assert result.seeds.goal == (snapshot["text"] if status in {"active", "paused", "blocked"} else "")
    assert result.seeds.request_text == rows()[-1]["content"]
    goal_pin = next((p for p in result.result.hot.pins if p.key == "goal"), None)
    assert goal_pin is None or status in goal_pin.label


def test_tail_request_not_duplicated_then_folds_with_immutable_previous_view(enabled, tmp_path):
    first = build(tmp_path, rows()[:2])
    request_pin = next(p for p in first.result.hot.pins if p.key.startswith("request:"))
    assert request_pin.label == "折叠区末人类请求"
    original = Path(first.view_path).read_bytes()
    tail = build(tmp_path, rows(), region_end=2)
    assert tail.seeds.request_source == -1
    assert not any(p.key.startswith("request:") for p in tail.result.hot.pins)
    folded = build(tmp_path, rows(), first)
    assert folded.result.rebuilt
    assert folded.seeds.request_source == 2
    assert Path(first.view_path).read_bytes() == original
    next_round = build(tmp_path, rows() + [{"role": "assistant", "content": "工作回执"}], folded)
    assert not next_round.result.rebuilt
    assert next_round.text.startswith(folded.text)


def test_notes_and_tool_results_are_not_human_focus(enabled, tmp_path):
    messages = rows() + [
        {"role": "user", "content": "machine note", "note_key": "m1"},
        {"role": "user", "content": "[resume] continue working"},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a result"}]},
        {"role": "user", "content": "<environment_context>cwd=x</environment_context>"}]
    result = build(tmp_path, messages)
    assert result.seeds.request_source == 2
    assert result.seeds.user_nodes == (0, 2)


@pytest.mark.parametrize("render", [render_requests, render_requests_grouped, render_requests_compact])
def test_budget_renderers_never_resurrect_old_task_excerpts(enabled, tmp_path, render):
    result = build(tmp_path, rows())
    for recent in (0, 1, 10):
        rendered = render(result.graph, 3, replace(production_params(), request_recent_verbatim=recent),
                          skip=frozenset({2}), user_nodes=result.seeds.user_nodes)
        assert rendered
        assert "ChatGPT" not in "\n".join(text for _, text in rendered)


def test_default_off_keeps_existing_projection(monkeypatch, tmp_path):
    monkeypatch.delenv("XEYO_WSC_REQUEST_PROJECTION", raising=False)
    monkeypatch.setenv("XEYO_WSC_STATE_CONTRACTS", "1")
    result = build(tmp_path, rows())
    assert result.seeds.goal == rows()[0]["content"]
    assert not result.seeds.request_projection


def test_retry_identity_does_not_restore_old_focus(enabled, tmp_path):
    messages = rows()
    messages[0]["id"] = "first"
    messages += [deepcopy(messages[0])]
    result = build(tmp_path, messages)
    assert result.seeds.request_source == 2
    assert 3 not in result.seeds.user_nodes
    assert 3 in result.seeds.pin_nodes
    assert result.cold.expand("node://3") == (messages[0]["content"],)


def test_identity_collision_fails_without_publishing_wrong_focus(enabled, tmp_path):
    messages = rows()
    messages[0]["id"] = messages[2]["id"] = "collided"
    with pytest.raises(ValueError, match="request_identity_conflict"):
        build(tmp_path, messages)
