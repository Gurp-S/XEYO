"""B4：V2 的路径触碰账必须与 V1 建图时的 `refs` 池同域。

#30 那次的教训：两臂各自内部都自洽、只有 join 全线失配。所以这一类不看"渲染得好不好看"，
只看一件事——**同一个前缀，V1 图里 `refs` 的集合与 V2 账本里的集合是不是同一批键**。
"""

from __future__ import annotations

from memory.wsc2.events import build_events
from memory.wsc2.projector import sections
from memory.wsc2.reducer import reduce_prefix
from memory.wsc2.state import WorkingState


def use(cid, name, **inp):
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": cid, "name": name, "input": inp}]}


def result(cid, text, *, is_error=False):
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": cid, "content": text,
         "is_error": is_error}]}


def user(text="go"):
    return {"role": "user", "content": text}


def _pool(state: WorkingState) -> set[str]:
    return set(state.paths)


def test_ledger_records_input_command_and_mention_paths():
    """三条来源都要记到：工具输入、Bash 命令、结果文本里的提及。

    夹具用 V1 认得的写法（相对带目录的 `src/app/a.py`）——V1 的 `_PATH_RE` 不收
    `/p/a.py` 这种前导斜杠的 unix 绝对路径，用它当夹具会让断言"永远通过"或"永远失败"，
    两种都比不测更糟。
    """
    msgs = [user("改代码"),
            use("c1", "Read", file_path="src/app/a.py"),
            result("c1", "ok"),
            use("c2", "Bash", command="pytest tests/wsc/test_b.py -q"),
            result("c2", "ModuleNotFoundError: failed to import src/lib/mod.py"),
            use("c3", "Bash", command="true > build/out.log"),
            result("c3", "Exit code 1", is_error=True)]
    pool = _pool(reduce_prefix(build_events(msgs), len(msgs)))
    assert "src/app/a.py" in pool, "工具输入里的路径"
    assert any("test_b.py" in p for p in pool), "命令里的路径"
    assert any("mod.py" in p for p in pool), "结果文本里提到的路径也算提及"
    assert any("out.log" in p for p in pool), "重定向目标就是现场"


def test_machine_noise_paths_never_enter_the_ledger():
    """V1 的来源过滤在建图前做，对所有信息类同口径 ⇒ V2 也必须在入账前过滤。

    同一条命令里放"该记的"与"该滤的"，这样这条断言既能响也不会因为全空而假通过。
    """
    msgs = [user(),
            use("c1", "Bash", command="cat src/app/a.py build/cache.pyc > /dev/null"),
            result("c1", "junk")]
    pool = _pool(reduce_prefix(build_events(msgs), len(msgs)))
    assert any("a.py" in p for p in pool), "该记的没记 ⇒ 这条夹具根本没在扫命令"
    assert not [p for p in pool if p.endswith(".pyc") or "dev/null" in p]


def test_pool_equals_v1_graph_refs_for_the_same_prefix():
    """金标 = V1 自己的 `build_graph`。归并两侧都做（V1 在建图时、V2 在渲染时）。"""
    pytest_v1 = __import__("pytest")
    pytest_v1.importorskip("synaptic")
    from synaptic.graph import build_graph
    from synaptic.textutil import suffix_chain_canonical

    msgs = [user("跑起来"),
            use("c1", "Read", file_path="code/cli/src/components/X.tsx"),
            result("c1", "1\timport {y} from 'components/y.tsx'"),
            use("c2", "Bash", command="pytest tests/wsc/test_x.py -q"),
            result("c2", "FAILED tests/wsc/test_x.py - RuntimeError at /p/x.py", is_error=True),
            use("c3", "Write", file_path="src/components/X.tsx", content="x"),
            result("c3", "ok")]
    st = reduce_prefix(build_events(msgs), len(msgs))
    v2 = set(suffix_chain_canonical(sorted(_pool(st))).get(p, p) for p in _pool(st))
    v1 = {p for n in build_graph(msgs, include_soft_edges=False).nodes for p in n.refs}
    v1 = set(suffix_chain_canonical(sorted(v1)).get(p, p) for p in v1)
    assert v2 == v1, f"键域错位：只在 V2={sorted(v2 - v1)} / 只在 V1={sorted(v1 - v2)}"


def test_paths_section_is_quota_bounded_and_deterministic():
    """配额就是这一类的生命周期：判不出"提及作废"，所以只展示前 N 条，不给退场规则。"""
    st = WorkingState()
    for i in range(400):
        st.touch_path(f"/p/filler/dir{i}/file{i}.py", i, failed=(i % 7 == 0))
    a = dict(sections(st))["PATHS"]
    b = dict(sections(st))["PATHS"]
    assert a == b, "同一状态两次渲染必须逐字相同"
    assert len(a) <= 48, "V2 的实测条数上限"
    assert a and all(len(l) < len("/p/filler/dir0/file0.py") for l in a), \
        "发射的是最短唯一后缀，不是整条键"


def test_failure_sites_rank_above_cold_paths():
    """同池内，失败现场要抢到位置——它撑的是 `failure_site` 那类针（V1 的 tier 2）。"""
    st = WorkingState()
    for i in range(300):
        st.touch_path(f"/p/cold/dir{i}/f{i}.py", i)
    st.touch_path("/p/hot/the_failure.py", 5, failed=True)
    lines = dict(sections(st))["PATHS"]
    assert any("the_failure.py" in l for l in lines), "失败现场被配额挤掉 ⇒ 优先级写错了"


def test_paths_follow_excluded_branches_under_equal_budget():
    """路径段不能先于错误结论占用固定头预算。"""
    from memory.wsc2.projector import _path_caps

    assert _path_caps() == (48, 384)
    st = WorkingState()
    st.touch_path("src/app/main.py", 1)
    st.add("decision", "branch", {"conclusion": "failed branch: ImportError"},
           event_id="e1", event_index=1, evidence="branch result")
    names = [name for name, _ in sections(st)]
    assert names.index("EXCLUDED BRANCHES") < names.index("PATHS")
