"""G1: explicit closure, conservative rejection, lossless recall, frozen bytes."""
from dataclasses import replace

from synaptic.assemble import build_pins
from synaptic.freshness import analyze
from synaptic.graph import build_graph
from synaptic.project import project
from synaptic.types import WscParams


OLD = "chatgpt总是打开半天不出现,或者说只有进程前台不出现,现在就是只有进程,怎么修复"
NEXT = "根据整个上下文分析WSC的问题，给出具体事实依据"
CLOSE = "WSC一直记住我说的chatgpt的问题，但是这个问题我自己已经修复好了导致你白花时间去解决"


def messages(close=CLOSE):
    return [{"role": "user", "content": t} for t in (OLD, NEXT, close)]


def projection(rows, **kwargs):
    return project(rows, region_end=len(rows), session="goal-regression",
                   params=WscParams(), persist_view=False, **kwargs)


def test_explicit_matching_closure_retires_goal_only_when_enabled(monkeypatch):
    rows = messages()
    graph = build_graph(rows)
    monkeypatch.delenv("XEYO_STALE_GOAL_RETIRE", raising=False)
    baseline = analyze(graph)
    assert 0 not in baseline.superseded
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "1")
    actual_shape = "把没有修复的全部记住，就是WSC一直记住我说的chatgpt的问题，但是这个问题我自己已经修复好了导致你白花时间，如果出现其它问题怎么办"
    assert 0 in analyze(build_graph(messages(actual_shape))).superseded
    fresh = analyze(graph)
    assert 0 in fresh.superseded
    assert fresh.by_class["goal"] == 1
    assert [(d.idx, d.by) for d in fresh.downgrades if d.cls == "goal"] == [(0, 2)]
    goal = next(p for p in projection(rows).result.hot.pins if p.key == "goal")
    assert goal.text == NEXT and goal.nodes == (1,)
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "0")
    assert analyze(graph) == baseline
    for value in ("", "false", "off", "no", "invalid"):
        monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", value)
        assert analyze(graph) == baseline
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "1")
    reopened = rows + [{"role": "user", "content": "现在继续修复chatgpt"}]
    assert analyze(build_graph(reopened)).mis_downgrade
    assert not analyze(build_graph(reopened), region_end=3).mis_downgrade
    chinese = [{"role": "user", "content": "登录窗口故障修复"},
               {"role": "user", "content": "登录窗口故障已经修好了"}]
    assert 0 in analyze(build_graph(chinese)).superseded


def test_unrelated_negated_quoted_future_and_weak_closures_do_not_retire(monkeypatch):
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "1")
    cases = [
        "支付接口已经修好了", "chatgpt已解决", "chatgpt修复还没有已解决",
        "chatgpt修复如果已解决再告诉你", "chatgpt修复是否已解决？",
        "示例：chatgpt修复已解决", '> chatgpt修复已解决',
        '他说“chatgpt修复已解决”', '```\nchatgpt修复已解决\n```',
        '例如“我自己已经修复好了”。现在分析chatgpt修复的问题',
        "chatgpt修复。支付接口已解决", "chatgpt修复撤销", "现在做支付接口",
        "支付已解决，chatgpt修复还在进行", "不要作废chatgpt修复",
        "chatgpt修复看看，支付接口已解决",
        "如果chatgpt修复，这个问题已解决", "chatgpt修复未已解决",
    ]
    for text in cases:
        assert 0 not in analyze(build_graph(messages(text))).superseded, text
    graph = build_graph(messages())
    assert 0 not in analyze(graph, region_end=2).superseded
    reverse = [{"role": "user", "content": CLOSE}, {"role": "user", "content": OLD}]
    assert 1 not in analyze(build_graph(reverse)).superseded
    mixed = [{"role": "user", "content": OLD + "，必须保留数据库"},
             {"role": "user", "content": CLOSE}]
    assert 0 not in analyze(build_graph(mixed)).superseded


def test_retired_user_text_is_losslessly_recoverable(monkeypatch, tmp_path):
    from synaptic.coldstore import node_handle
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "1")
    rows = messages()
    view = tmp_path / "isolated-goal-view.txt"
    result = project(rows, region_end=len(rows), session="goal-regression",
                     params=WscParams(handle_style="read"), view_path=view)
    assert result.denoise["downgraded_by_class"]["goal"] == 1
    assert result.cold.expand(node_handle(0)) == (OLD,)
    assert OLD in view.read_text(encoding="utf-8")
    assert rows[0]["content"] == OLD
    from evals.stale_goal_ab import evaluate
    report = evaluate(rows, goal_index=0, close_index=2, cuts=[2, 3],
                      output=tmp_path / "ab", protected=(view,))
    assert all(report["acceptance"].values())
    assert report["arms"]["off"]["closed_goal_still_pinned_count"] == 1
    assert report["arms"]["on"]["closed_goal_still_pinned_count"] == 0
    wrong_annotation = evaluate(rows, goal_index=0, close_index=1, cuts=[2, 3],
                                output=tmp_path / "ab-wrong-annotation", protected=(view,))
    assert not wrong_annotation["acceptance"]["closed_goal_retired"]


def test_frozen_existing_lines_survive_and_other_pins_are_unchanged(monkeypatch, tmp_path):
    from synaptic.assemble import assemble
    from synaptic.types import MODE_APPEND_ONLY
    rows = messages()
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "0")
    before = projection(rows)
    monkeypatch.setenv("XEYO_STALE_GOAL_RETIRE", "1")
    after = projection(rows)
    assert before.seeds.original_task != after.seeds.original_task
    assert [p for p in build_pins(before.seeds) if p.key != "goal"] == [
        p for p in build_pins(after.seeds) if p.key != "goal"]
    params = replace(WscParams(), mode=MODE_APPEND_ONLY, journal_layout=True,
                     journal_growth_tokens=100000)
    args = (before.graph, before.seeds, before.result.hot.pins, (), (), (), params)
    old_text, _, state, _ = assemble(*args, region_end=len(rows))
    new_text, _, _, _ = assemble(after.graph, after.seeds, after.result.hot.pins,
                              (), (), (), params, prev=state, region_end=len(rows))
    assert new_text.startswith(old_text)
    # Actual runtime reuse, with the closure arriving in the unfrozen tail.
    from types import SimpleNamespace
    from engine.compact import keep_tail_cut
    import memory.wsc_projection as live
    from tests.wsc._fixtures import synth_session, msg_asst_text
    saved = dict(live._STATE)
    live._STATE.clear()
    monkeypatch.setenv("XEYO_WSC", "1")
    monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("XEYO_CWD", str(tmp_path))
    monkeypatch.delenv("XEYO_WSC_FROZEN_HEAD", raising=False)
    monkeypatch.delenv("XEYO_WSC_CADENCE_ABSORB", raising=False)
    try:
        source = synth_session(turns=22, error_turn=4)
        source[0] = {"role": "user", "content": OLD}
        cut = keep_tail_cut(source)
        working = SimpleNamespace(session_id="g1-live-regression", compact_cursor=cut, c1_frozen_until=0)
        first = live.project_c2_messages(source, working, cwd=str(tmp_path))
        assert first is not None
        frozen = next(iter(live._STATE.values())).head
        previous = "\n".join(str(m.get("content") or "") for m in first)
        grown = source + [{"role": "user", "content": CLOSE}]
        for extra in ([], [msg_asst_text("继续记录WSC现场事实")]):
            emitted = live.project_c2_messages(grown + extra, working, cwd=str(tmp_path))
            assert emitted is not None
            body = "\n".join(str(m.get("content") or "") for m in emitted)
            assert body.startswith(previous)
            assert next(iter(live._STATE.values())).head == frozen
            previous = body
    finally:
        live._STATE.clear()
        live._STATE.update(saved)
