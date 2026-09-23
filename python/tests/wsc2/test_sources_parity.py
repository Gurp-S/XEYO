"""#31 的对账契约：V2 的派生观测必须和 V1 的 `FileState` 说同一件事。

这些测试的判据不是"V2 自己的规则"，而是**跑一遍 V1 的 `build_file_states` 当金标**。
唯一一处有意分歧（只写未读路径的变更摘要）单独钉了一条测试，写清分歧方向和理由。
"""

from __future__ import annotations

import pytest

from memory.wsc2.events import build_events
from memory.wsc2.projector import render, sections
from memory.wsc2.reducer import reduce_prefix
from memory.wsc2.sources import DERIVED, Observation, Signal, v1_file_oracle
from memory.wsc2.state import ACTIVE, WorkingState

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


def two_results(*rows: tuple[str, str]) -> dict:
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": cid, "content": txt}
        for cid, txt in rows]}


def obs_of(msgs) -> dict[str, Observation]:
    st = reduce_prefix(build_events(msgs), len(msgs))
    return {p: Observation.from_dict(d) for p, d in st.obs.items()}


def assert_parity(msgs) -> dict[str, Observation]:
    """逐字段和 V1 的金标对：任何一处不等值都要显式改测试，不许静默放宽。"""
    mine, oracle = obs_of(msgs), v1_file_oracle(msgs)
    assert set(mine) == set(oracle), "观测集合必须与 V1 同一批路径"
    for p, o in oracle.items():
        m = mine[p]
        assert m.observed_hash == o.observed_hash, f"{p} hash"
        assert m.read_ranges == tuple(o.read_ranges), f"{p} ranges"
        assert (m.stale, m.stale_at) == (bool(o.stale), o.stale_at), f"{p} stale"
        assert m.last_read_index == o.last_read_index, f"{p} last_read"
    return mine


# --- 与 V1 的等价性 ----------------------------------------------------------

def test_read_then_write_cycle_matches_v1_file_state() -> None:
    msgs = [user("改 a.py"),
            use("c1", "Write", file_path="a.py", content="l1\nl2\n"), result("c1", "created"),
            use("c2", "Read", file_path="a.py"), result("c2", "1: l1\n2: l2"),
            use("c3", "Edit", file_path="a.py", old_string="l1", new_string="x"),
            result("c3", "ok")]
    mine = assert_parity(msgs)
    o = mine["a.py"]
    assert o.observed_hash, "精确读必须留下内容 hash（V1 铁律：防读一半当读全）"
    assert o.read_ranges == ((1, 2),), o.read_ranges
    assert o.stale and o.stale_at == 6, "写必须锚在**回执行**（V1 的 _Write.idx 就是结果节点）"
    assert "diff" not in o.diff_summary.lower() and o.diff_summary


def test_a_grep_after_the_write_does_not_reset_the_stale_clock() -> None:
    """片段型命令不参与过期时钟（V1 刻意排除，理由写在 filestate 的注释里）。"""
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x\n"), result("c1"),
            use("c2", "Read", file_path="a.py"), result("c2", "1: x"),
            use("c3", "Edit", file_path="a.py", old_string="x", new_string="y"),
            result("c3"),
            use("c4", "Bash", command="grep -n y a.py"), result("c4", "1:y")]
    mine = assert_parity(msgs)
    assert mine["a.py"].stale and mine["a.py"].stale_at == 6


def test_bash_cat_resets_the_clock_but_never_supplies_the_hash() -> None:
    """整文件读算观测，但 hash / 区间只取精确读 —— 否则一次 Read→cat 切换会让 hash 凭空跳变。"""
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x\ny\n"), result("c1"),
            use("c2", "Read", file_path="a.py", offset=1, limit=1), result("c2", "1: x"),
            use("c3", "Bash", command="cat a.py"), result("c3", "x\ny"),
            use("c4", "Edit", file_path="a.py", old_string="y", new_string="z"),
            result("c4")]
    mine = assert_parity(msgs)
    o = mine["a.py"]
    assert o.read_ranges == ((1, 1),), "区间只能来自 Read 那一次"
    assert o.stale and o.stale_at == 8, "cat 把过期时钟推到 7，写发生在 8"


def test_only_the_first_tool_result_of_a_message_counts_as_a_read() -> None:
    """V1 在第一个 tool_result 块就 break ⇒ 第二个块的区间不许进账。"""
    msgs = [user("go"),
            use("c1", "Read", file_path="a.py", offset=1, limit=2),
            use("c2", "Read", file_path="a.py", offset=9, limit=2),
            two_results(("c1", "1: a\n2: b"), ("c2", "9: i\n10: j"))]
    mine = assert_parity(msgs)
    assert mine["a.py"].read_ranges == ((1, 2),), mine["a.py"].read_ranges


def test_failed_read_still_counts_as_an_observation_like_v1() -> None:
    """V1 不看 is_error：失败回执的文本照样被 hash。V2 若要改，得先说服 V1 一起改。"""
    msgs = [user("go"),
            use("c1", "Read", file_path="missing.py"),
            result("c1", "File does not exist", is_error=True)]
    assert_parity(msgs)


def test_write_only_path_keeps_the_last_summary_this_is_one_deliberate_divergence() -> None:
    """唯一一处有意与 V1 不同：只写未读的路径，摘要取**最后一次**写。

    V1 的 `synaptic/filestate.py:181` 是 `for w in writes: if w.path in states: continue`
    ⇒ 从没被读过的文件一旦进表，后续写全被跳过，摘要永远停在第一次写。V2 不复制这个行为：
    "这文件被改成什么样了"停在历史值上，比没有摘要更坏。分歧方向、成因与行号一并钉住。
    """
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x\n"), result("c1"),
            use("c2", "Edit", file_path="a.py", old_string="x", new_string="y"),
            result("c2")]
    mine, oracle = obs_of(msgs), v1_file_oracle(msgs)
    assert mine["a.py"].observed_hash == "" and not mine["a.py"].stale
    assert mine["a.py"].diff_summary.startswith("-x +y"), mine["a.py"].diff_summary
    assert oracle["a.py"].diff_summary.startswith("Write 全文覆盖"), "V1 停在第一次写"


# --- 派生事实的 authority 与"只登记不淘汰" ----------------------------------

def test_constraint_facts_are_derived_and_can_never_be_retired() -> None:
    st = reduce_prefix(build_events([
        user("输出必须是中文，不要夹英文"),
        user("先改成英文试试"),
        user("算了，别用英文了")]), 3)
    cons = [f for f in st.active_facts(("constraint",)) if f.kind == "constraint"]
    assert cons, "V1 的抽取器能认出的约束句，V2 必须进状态"
    assert all(f.status == ACTIVE for f in cons)
    assert all(f.authority == DERIVED for f in cons), "来源档位必须记成 DERIVED"
    head = render(st)
    assert "CONSTRAINTS (lifecycle undetermined)" in head, "寿命未定的事实要写明，不能装当前结论"


def test_signal_rejects_an_unknown_authority_tier() -> None:
    with pytest.raises(ValueError):
        Signal("constraint", "k", {"literal": "x"}, "definitely-not-a-tier", "e")


def test_observations_are_deterministic_across_runs() -> None:
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x\n"), result("c1"),
            use("c2", "Read", file_path="a.py"), result("c2", "1: x"),
            use("c3", "Edit", file_path="a.py", old_string="x", new_string="y"),
            result("c3")]
    ev = build_events(msgs)
    a = reduce_prefix(ev, len(msgs))
    b = reduce_prefix(build_events(msgs), len(msgs))
    assert a.to_jsonl_lines() == b.to_jsonl_lines()
    assert a.obs_jsonl_lines() == b.obs_jsonl_lines()
    assert isinstance(a, WorkingState)


def test_working_set_line_carries_the_v1_semantics() -> None:
    msgs = [user("go"),
            use("c1", "Write", file_path="a.py", content="x\n"), result("c1"),
            use("c2", "Read", file_path="a.py", offset=1, limit=1), result("c2", "1: x"),
            use("c3", "Edit", file_path="a.py", old_string="x", new_string="y"),
            result("c3")]
    st = reduce_prefix(build_events(msgs), len(msgs))
    lines = dict(sections(st))["WORKING SET"]
    assert len(lines) == 1, lines
    line = lines[0]
    assert "hash=" in line and "read:1-1" in line and "STALE@6" in line, line
