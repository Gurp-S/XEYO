"""B1-a：V1 剪枝卡 → V2 的分支结论事实，外加 V1 没有的"退场"。

不依赖真 V1 投影：卡片用轻量替身（属性名与 `synaptic.types.PruneCard` 一致），
因为这一段要证的是"接得进、幂等、退场只在有证据时发生、渲染带可寻址行号"。
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.wsc2.events import build_events
from memory.wsc2.projector import sections
from memory.wsc2.reducer import reduce_prefix
from memory.wsc2.sources import attach_decisions, decision_signals, error_sig
from memory.wsc2.state import ACTIVE, SUPERSEDED

try:
    import pytest
    pytest.importorskip("synaptic")
except Exception:  # pragma: no cover
    pass


@dataclass
class FakeCard:
    card_id: str
    conclusion: str
    files: tuple[str, ...] = ()
    error_sig: str = ""
    replay: str = ""
    nodes: tuple[int, ...] = ()


ERR_TEXT = "ModuleNotFoundError: no module named x"
# 卡片的 error_sig 与失败事实的 error_sig 必须是**同一个函数的输出**，否则退场永远对不上
# （V1 也是这么算的：`synaptic/graph.py:296` 节点 error_sig = extract_error_sig(结果文本)）。
CARD = FakeCard("B7", "改完还是崩：build 报缺依赖", files=("/p/a.py",),
                error_sig=error_sig(ERR_TEXT), nodes=(11, 14))


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def use(cid: str, name: str, **inp) -> dict:
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": cid, "name": name, "input": inp}]}


def result(cid: str, text: str = "ok", *, is_error: bool = False) -> dict:
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": cid, "content": text,
         "is_error": is_error}]}


def failing_then_retried_success():
    msgs = [user("跑测试"),
            use("c1", "Bash", command="pytest -q"),
            result("c1", ERR_TEXT, is_error=True),
            use("c2", "Bash", command="pytest -q"),
            result("c2", "5 passed")]
    return reduce_prefix(build_events(msgs), len(msgs))


def test_card_becomes_one_derived_fact_with_rows():
    st = reduce_prefix(build_events([user("go")]), 1)
    made = attach_decisions(st, decision_signals([CARD]))
    assert made == 1
    f = next(iter(st.active_facts(("decision",))))
    assert f.authority == "derived" and f.evidence == "prune_card"
    assert f.value["rows"] == [11, 14] and f.value["error_sig"] == error_sig(ERR_TEXT)
    line = dict(sections(st))["EXCLUDED BRANCHES"][0]
    # 1-based：与 Read 的 offset 同口径，事实内部仍存 0-based 索引
    assert "lines=12-15" in line and "rows=" not in line
    assert "ModuleNotFoundError" in line, "结论里没写错误文本 ⇒ 必须补 err="


def test_line_does_not_repeat_what_the_conclusion_already_names():
    """行格式的省钱规则：结论字面里已有的路径与错误签名不再发射第二遍。

    这就是 V2 一行能比 V1 密的原因（V1 靠硬编码 `files[1:]`，这里按字面判）。
    大小写不同也算已有 —— 只折一侧会把该省的行留下、或把该留的行省掉。
    """
    card = FakeCard("B8", "Bash 失败：ModuleNotFoundError 在 /p/A.py",
                    files=("/p/a.py",), error_sig="modulenotfounderror", nodes=(3, 3))
    st = reduce_prefix(build_events([user("go")]), 1)
    attach_decisions(st, decision_signals([card]))
    line = dict(sections(st))["EXCLUDED BRANCHES"][0]
    assert "files=" not in line and "err=" not in line
    assert line == "Bash 失败：ModuleNotFoundError 在 /p/A.py lines=4-4"


def test_attaching_twice_is_idempotent():
    st = reduce_prefix(build_events([user("go")]), 1)
    sigs = decision_signals([CARD])
    attach_decisions(st, sigs)
    first = st.to_jsonl_lines()
    assert attach_decisions(st, sigs) == 0
    assert st.to_jsonl_lines() == first, "重复挂载必须逐字节幂等"


def test_decision_retires_only_when_its_error_actually_got_fixed():
    st = failing_then_retried_success()
    sigs = decision_signals([CARD])
    assert attach_decisions(st, sigs) == 1
    assert st.active_facts(("decision",)) == [], "错误已解决 ⇒ 该分支不该再算当前信息"
    d = st.latest("decision", sigs[0].key)
    assert d is not None and d.status == SUPERSEDED and d.evidence == "same_error_resolved"


def test_decision_stays_active_when_the_error_is_still_unresolved():
    msgs = [user("跑测试"),
            use("c1", "Bash", command="pytest -q"),
            result("c1", ERR_TEXT, is_error=True)]
    st = reduce_prefix(build_events(msgs), len(msgs))
    attach_decisions(st, decision_signals([CARD]))
    live = st.active_facts(("decision",))
    assert len(live) == 1 and live[0].status == ACTIVE, "错误没被解决就不许让分支作废"


def test_decision_survives_when_the_same_error_is_back_after_being_fixed():
    """同签名既有一条"重试成功已解决"的失败、又有一条还挂着 ⇒ 不许退场。

    缺这道闸时状态自相矛盾：`[UNRESOLVED]` 里写着这个错误，`[EXCLUDED BRANCHES]` 却说
    它已经作废。实测 126 点上 26 次退场有 8 次是同签名错误后来又出现 ⇒ 闸必须有。
    """
    msgs = [user("跑测试"),
            use("c1", "Bash", command="pytest -q"),
            result("c1", ERR_TEXT, is_error=True),
            use("c2", "Bash", command="pytest -q"),
            result("c2", "5 passed"),
            use("c3", "Bash", command="pytest -q"),
            result("c3", ERR_TEXT, is_error=True)]
    st = reduce_prefix(build_events(msgs), len(msgs))
    assert any(f.status == "RESOLVED" for f in st.facts.values() if f.kind == "failure")
    attach_decisions(st, decision_signals([CARD]))
    live = st.active_facts(("decision",))
    assert len(live) == 1, "同签名还有未解决的失败 ⇒ 分支还得留在注意力里"


def test_two_cards_with_same_error_and_files_share_one_key():
    a = FakeCard("B1", "第一次尝试", files=("/p/a.py",), error_sig="boom", nodes=(3,))
    b = FakeCard("B9", "换个写法还是boom", files=("/p/a.py",), error_sig="boom", nodes=(8,))
    sa, sb = decision_signals([a]), decision_signals([b])
    assert sa[0].key == sb[0].key, "同一错误类 + 同一现场 = 同一条记录（与 V1 合组键同源）"
    assert sa[0].provenance != sb[0].provenance, "但来源节点各记各的"
