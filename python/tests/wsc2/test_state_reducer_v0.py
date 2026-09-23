"""WSC V2 Phase-1 回归：StateReducer v0 的保守性与分层不变量。

方向锁死在两件事上（§五 / §十三）：
- 没有明确事件证据 ⇒ 不许 SUPERSEDE / RESOLVE（宁可多留）。
- Working State 不许知道 transport（cache / theta / cursor / journal）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.wsc2.audit import gold, score
from memory.wsc2.events import build_events
from memory.wsc2.reducer import StateReducer, reduce_events, reduce_prefix
from memory.wsc2.state import (ACTIVE, CANCELLED, RESOLVED, SUPERSEDED, Fact,
                               WorkingState)

pytest.importorskip("synaptic")


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def use(cid: str, name: str, **inputs) -> dict:
    return {"role": "assistant", "content": [
        {"type": "text", "text": "working"},
        {"type": "tool_use", "id": cid, "name": name, "input": inputs}]}


def result(cid: str, text: str = "ok", *, is_error: bool = False) -> dict:
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": cid, "content": text,
         "is_error": is_error}]}


def one(msgs) -> WorkingState:
    return reduce_events(build_events(list(msgs)))[0]


def facts_of(state: WorkingState, kind: str) -> list[Fact]:
    return [state.facts[i] for i in state.order if state.facts[i].kind == kind]


def active(state: WorkingState, kind: str) -> list[Fact]:
    return [f for f in facts_of(state, kind) if f.status == ACTIVE]


# --- 文件版本 ---------------------------------------------------------------

def test_second_write_supersedes_the_first_and_leaves_one_active_version() -> None:
    st = one([user("改一下配置"),
              use("c1", "Write", file_path="a/b.py", content="x"),
              result("c1"),
              use("c2", "Write", file_path="a/b.py", content="y"),
              result("c2")])
    files = facts_of(st, "file")
    assert len(files) == 2, "两份历史版本都要留在 Event Store 的记账里"
    old, new = files
    assert old.status == SUPERSEDED and old.superseded_by == new.fact_id
    assert old.evidence == "write_after_write"
    assert new.status == ACTIVE and new.version == 2
    assert len(active(st, "file")) == 1, "同一 key 只允许一条 ACTIVE"


def test_active_file_fact_points_at_the_last_write_event() -> None:
    msgs = [user("go"),
            use("c1", "Write", file_path="p.py", content="x"), result("c1"),
            use("c2", "Edit", file_path="p.py", old_string="x", new_string="y"),
            result("c2")]
    events = build_events(msgs)
    st = reduce_events(events)[0]
    last_write = max(e.index for e in events
                     if e.kind == "tool_use" and "p.py" in e.paths)
    cur = st.latest("file", "p.py")
    assert cur is not None and cur.created_index == last_write


def test_read_of_a_written_file_does_not_bump_its_version() -> None:
    st = one([user("go"),
              use("c1", "Write", file_path="p.py", content="x"), result("c1"),
              use("c2", "Read", file_path="p.py"), result("c2", "1: x")])
    cur = st.latest("file", "p.py")
    assert cur is not None and cur.status == ACTIVE and cur.version == 1


# --- 保守闸（不明确 ⇒ KEEP）-------------------------------------------------

def test_a_new_user_request_never_supersedes_the_previous_one() -> None:
    """"实现 A"→"A 做完了"→"再实现 B" 里，前两条是否完成没有 deterministic 证据。"""
    st = one([user("实现 A"), user("A 做完了"), user("再实现 B")])
    reqs = facts_of(st, "request")
    assert len(reqs) == 3
    assert all(f.status == ACTIVE for f in reqs), "v0 不许凭正则判请求已完成"
    assert all(f.evidence == "user_text" for f in reqs)


def test_repeated_identical_request_merges_into_one_fact_with_provenance() -> None:
    st = one([user("继续"), user("继续"), user("继续")])
    reqs = facts_of(st, "request")
    assert len(reqs) == 1, "同文重发不得长成三条"
    assert len(reqs[0].provenance) == 3
    assert int(reqs[0].value["repeat"]) == 3


def test_transition_to_active_is_refused_once_a_fact_has_exited() -> None:
    st = WorkingState()
    f = st.add("file", "p.py", {"op": "write"}, event_id="E1", event_index=1,
               evidence="first_write")
    g = st.add("file", "p.py", {"op": "write"}, event_id="E2", event_index=2,
               evidence="write_after_write")
    st.transition(f, SUPERSEDED, event_id="E2", event_index=2,
                  evidence="write_after_write", successor=g.fact_id)
    st.transition(f, ACTIVE, event_id="E3", event_index=3, evidence="猜的")
    assert f.status == SUPERSEDED, "退场的事实不能被无证据地拉回 ACTIVE"
    assert g.status == ACTIVE


def test_unknown_status_is_not_applied() -> None:
    st = WorkingState()
    f = st.add("request", "k", {}, event_id="E1", event_index=1, evidence="user_text")
    st.transition(f, "FINISHED", event_id="E2", event_index=2, evidence="x")
    assert f.status == ACTIVE


# --- 工具配对 / 失败生命周期 -------------------------------------------------

def test_pending_tool_set_is_exactly_the_unanswered_calls() -> None:
    st = one([user("go"), use("c1", "Read", file_path="a"), use("c2", "Read",
                                                                 file_path="b")])
    assert {f.key for f in active(st, "tool_call")} == {"c1", "c2"}
    st = one([user("go"), use("c1", "Read", file_path="a"), use("c2", "Read",
                                                                 file_path="b"),
              result("c1", "x")])
    assert {f.key for f in active(st, "tool_call")} == {"c2"}
    done = st.latest("tool_call", "c1")
    assert done is not None and done.status == RESOLVED
    assert done.evidence == "tool_result_paired"


def test_identical_retry_that_succeeds_resolves_the_failure() -> None:
    msgs = [user("go"),
            use("c1", "Bash", command="pytest -q"), result("c1", "FAILED",
                                                            is_error=True),
            use("c2", "Bash", command="pytest -q"), result("c2", "1 passed")]
    st = one(msgs)
    fails = facts_of(st, "failure")
    assert len(fails) == 1 and fails[0].status == RESOLVED
    assert fails[0].evidence == "identical_retry_succeeded"
    assert active(st, "failure") == []


def test_a_different_retry_does_not_resolve_the_failure() -> None:
    """改了就不同的入参：那是"新尝试"，不是"旧失败已解决"的证据。"""
    st = one([user("go"),
              use("c1", "Bash", command="pytest -q"),
              result("c1", "FAILED", is_error=True),
              use("c2", "Bash", command="pytest -q tests/x"),
              result("c2", "ok")])
    assert len(active(st, "failure")) == 1, "不同入参的成功不许顺手关掉旧失败"


def test_unresolved_failure_stays_active() -> None:
    st = one([user("go"), use("c1", "Bash", command="make"),
              result("c1", "boom", is_error=True)])
    assert len(active(st, "failure")) == 1


# --- TODO ---------------------------------------------------------------

def _todo(items: list[dict]) -> dict:
    return use("t1", "TodoWrite", todos=items)


def test_todo_completion_is_resolved_from_the_literal_status() -> None:
    st = one([user("go"), _todo([{"content": "写测试", "status": "completed"}])])
    todos = facts_of(st, "todo")
    assert len(todos) == 1
    assert todos[0].status == RESOLVED and todos[0].evidence == "todo_status_literal"


def test_todo_status_change_supersedes_the_previous_snapshot_row() -> None:
    st = WorkingState()
    red = StateReducer()
    events = build_events([user("go"),
                           _todo([{"content": "写测试", "status": "pending"}])])
    events += build_events([{"role": "assistant", "content": [
        {"type": "tool_use", "id": "t2", "name": "TodoWrite",
         "input": {"todos": [{"content": "写测试", "status": "in_progress"}]}}]}])
    for e in events:
        red.apply(st, e)
    todos = facts_of(st, "todo")
    assert len(todos) == 2 and todos[0].status == SUPERSEDED
    assert todos[1].status == ACTIVE and todos[1].version == 2


def test_cancelled_todo_is_not_marked_resolved() -> None:
    st = one([user("go"), _todo([{"content": "旧方案", "status": "cancelled"}])])
    assert st.facts[st.order[-1]].status == CANCELLED


# --- 评测台自身的非循环性 ---------------------------------------------------

def test_gold_is_computed_from_events_not_from_the_reducer() -> None:
    """金标必须在 reducer 之外算：否则 Active Recall 恒等于 1（循环定义）。"""
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x"), result("c1"),
            use("c2", "Write", file_path="b.py", content="y"), result("c2"),
            use("c3", "Write", file_path="a.py", content="z"), result("c3")]
    events = build_events(msgs)
    g = gold(events, 3)
    assert "a.py" in g["files"], "a.py 之后还被写 ⇒ 在 t=3 是活事实"
    assert "b.py" not in g["files"], "b.py 只在 t 之后出现 ⇒ t 时还不存在"
    st = reduce_prefix(events, 3)
    sc = score(events, 3, st)
    assert sc["file_recall"] == 1.0 and sc["file_gold"] == 1
    assert sc["file_wrong_version"] == 0


def test_score_flags_a_missed_active_fact() -> None:
    """金标里有、状态里没有 ⇒ 必须掉召回（证明这套度量能抓出漏，而不是恒等 1）。"""
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x"), result("c1"),
            use("c2", "Write", file_path="b.py", content="y"), result("c2"),
            use("c3", "Write", file_path="a.py", content="z"), result("c3")]
    events = build_events(msgs)
    st = reduce_prefix(events, 3)
    st.facts[st.latest("file", "a.py").fact_id].status = SUPERSEDED  # 人为漏一条
    sc = score(events, 3, st)
    assert sc["file_gold"] == 1 and sc["file_missed"] == 1
    assert sc["file_recall"] == 0.0


# --- 分层与影子不变量（§三 / §十三）----------------------------------------

TRANSPORT_WORDS = ("theta", "price_ratio", "prefix_hit", "cache_hit", "journal",
                   "keep_tail", "compact_cursor", "fold_events", "PAYBACK_SHOTS")


@pytest.mark.parametrize("name", ["state.py", "reducer.py", "events.py",
                                  "projector.py", "audit.py"])
def test_working_state_layer_does_not_know_transport(name: str) -> None:
    src = (Path(__file__).resolve().parents[2] / "memory" / "wsc2" / name).read_text(
        encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    hit = [w for w in TRANSPORT_WORDS if w in body]
    assert not hit, f"语义层读到了 transport 词汇：{hit}"


def test_production_projection_does_not_import_wsc2_yet() -> None:
    """第一阶段：生产投影里一个 wsc2 引用都不许有（V2 只活在旁路）。"""
    src = (Path(__file__).resolve().parents[2] / "memory" /
           "wsc_projection.py").read_text(encoding="utf-8")
    assert "wsc2" not in src, "V2 接管生产输出的口子被提前打开了"


def test_impl_flag_defaults_to_v1(monkeypatch) -> None:
    from memory import wsc2

    monkeypatch.delenv("XEYO_WSC_IMPL", raising=False)
    assert wsc2.impl() == "v1" and wsc2.shadow_enabled() is False
    monkeypatch.setenv("XEYO_WSC_IMPL", "garbage")
    assert wsc2.impl() == "v1", "脏值必须落回 v1，不能落进 v2"
    monkeypatch.setenv("XEYO_WSC_IMPL", "shadow")
    assert wsc2.impl() == "shadow" and wsc2.shadow_enabled() is True


def test_reducer_is_deterministic_and_serialisable() -> None:
    msgs = [user("go"), use("c1", "Write", file_path="a.py", content="x"),
            result("c1"), use("c2", "Bash", command="ls"),
            result("c2", "a.py", is_error=True)]
    a = json.dumps(one(msgs).to_jsonl_lines(), ensure_ascii=False)
    b = json.dumps(one(msgs).to_jsonl_lines(), ensure_ascii=False)
    assert a == b, "同输入必须同输出（否则缓存/回归全废）"

def test_v1_section_parser_handles_inline_headers() -> None:
    """生产热层段头是**行内**的（`[CONSTRAINTS] 目标: …`）。按独占整行解析会把整份头
    灌进 _TOP ⇒ V1 侧指标全假零（Phase 2 第一版就是这么算错的）。"""
    from memory.wsc2.audit import v1_sections

    secs = v1_sections(chr(10).join([
        "[CONSTRAINTS] 目标: 测试所有工具",
        "[UNRESOLVED] 未解决: 退出码 1（×5）",
        "[UNRESOLVED] 未解决: 退出码 2（×3）",
        "无段头的裸行"]))
    assert secs["CONSTRAINTS"] == ["目标: 测试所有工具"]
    assert len(secs["UNRESOLVED"]) == 3, "同段头续写 + 段头后的裸行归给上一段"
    # 已知局限：段头之后的裸行归给上一段（生产里它们本就是该段的内容行）。
    assert secs["UNRESOLVED"][-1] == "无段头的裸行"
