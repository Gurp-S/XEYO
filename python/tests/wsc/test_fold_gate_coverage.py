"""折叠判据的接线契约：已压缩态必须经过 θ 门，且每种折叠都要留痕。

历史缺陷（2026-09-29 定位，全部来自盘上账本）：``project_for_model`` 的扩展闸以
``c2_summary_text`` 非空为前提，而 WSC 接管发射面后摘要永远是空 ⇒ 该前提对 WSC 会话
整体不成立，每次 ``decide`` 点 C2 都退到只查 4000 字符的尺寸门，节奏只剩固定
``min_middle_edit_gap=4``，且 ``fold_events`` 一条不写。生产实测：
``sess_mumhoho0_xkv803`` 当日 ``c2_events`` 12 行 / 折叠记账 0 行、折叠正好每 4 枪一次。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from memory.working import WorkingSnapshot


def _big_msgs(n: int, size: int = 6000) -> list[dict]:
    return [{"role": "user", "content": "x" * size} for _ in range(n)]


def _decide(action: str) -> SimpleNamespace:
    return SimpleNamespace(
        a_star=action,
        hardtop=False,
        branches={
            "keep": SimpleNamespace(x="K"),
            "C1": SimpleNamespace(x="C"),
            "C2": SimpleNamespace(x="C2"),
        },
    )


def _press(monkeypatch, mem_switch, *, msgs, cursor, summary="", action="C2", context_limit=None):
    """把活路径打到「decide 点了 action」这一枪，返回 working。"""
    from memory.runtime import project_for_model

    mem_switch(XEYO_L5="v61")
    monkeypatch.setenv("XEYO_WSC", "1")  # WSC 权威=env（live_enabled 读的就是 env）
    monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: _decide(action))
    w = WorkingSnapshot()
    w.session_id = "s_gate_contract"
    w.compact_cursor = cursor
    w.c1_frozen_until = cursor
    w.c2_summary_text = summary
    w.turns_since_c2 = 999  # 避开中间编辑冷却，只测判据本身
    project_for_model(msgs, w, remaining_turns=30, context_limit=context_limit,
                      include_memory_index=False)
    return w


def _rows(path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _ledgers():
    from usage.ledger import c2_events_path, fold_events_path

    return _rows(fold_events_path()), _rows(c2_events_path())


def test_compacted_state_with_empty_summary_still_passes_theta_gate(monkeypatch, mem_switch):
    """摘要空 + 已压缩：这一枪必须经过 θ 门并留下判定行，而不是无痕折掉。"""
    w = _press(monkeypatch, mem_switch, msgs=_big_msgs(40), cursor=8)
    fold_rows, c2_rows = _ledgers()
    assert w.compact_cursor > 8, "游标没前推 ⇒ 夹具没打到折叠"
    assert c2_rows, "推进了却没写 c2_events ⇒ 触发侧记账断了"
    assert fold_rows, (
        "折了一枪却没有任何折叠判定行：θ 门又被旁路了（生产同形状 = c2_events 12 / fold_events 0）"
    )
    approved = [r for r in fold_rows if r.get("fold")]
    assert approved, f"折叠行全是拒绝态：{[r.get('reason') for r in fold_rows]}"
    assert approved[-1].get("reason") == "worth_fold", "批准折叠必须出自经济门"


def test_measured_cooldown_is_set_after_a_gated_fold(monkeypatch, mem_switch):
    """θ 门批准后必须回填实测回本枪数——那是折叠间隔唯一的入口数。"""
    w = _press(monkeypatch, mem_switch, msgs=_big_msgs(40), cursor=8)
    assert int(getattr(w, "c2_gap_shots", 0) or 0) > 0, (
        "折了但 c2_gap_shots 仍是 0 ⇒ 冷却闸拿不到实测数，节奏退回固定常数"
    )


def test_wsc_live_does_not_materialize_the_summary(monkeypatch, mem_switch):
    """WSC 接管发射面时摘要不进 sidecar：它永远不会被发出去，写进去只是无谓膨胀。"""
    w = _press(monkeypatch, mem_switch, msgs=_big_msgs(40), cursor=8)
    assert w.compact_cursor > 8
    assert w.c2_summary_text == "", "WSC live 却物化了摘要 ⇒ 7.7 MB 快照那类膨胀会回来"


def test_first_press_fold_is_recorded_with_its_own_gate(monkeypatch, mem_switch):
    """首压（cursor==0）仍走尺寸门——那里没有可保留的头——但必须留痕且标出自己的 gate。"""
    w = _press(monkeypatch, mem_switch, msgs=_big_msgs(40), cursor=0)
    fold_rows, c2_rows = _ledgers()
    assert w.compact_cursor > 0, "首压没推进游标 ⇒ 夹具失效"
    assert c2_rows and fold_rows
    size_rows = [r for r in fold_rows if r.get("gate") == "size_first_press"]
    assert size_rows, f"首压折叠没标 gate：{[r.get('reason') for r in fold_rows]}"
    row = size_rows[-1]
    assert row.get("fold") is True
    for field in ("region_tokens", "head_tokens", "tail_tokens", "saved_net", "transition"):
        assert field in row, f"首压折叠行缺判据字段 {field}：{row}"


def _extend_gate(monkeypatch, *, theta_env: str, msgs=None, cursor: int = 8, window_tokens: int = 128_000):
    """直接开经济闸（`try_extend_c2`），返回 (是否批准, 判定账目, working)。

    不走 `project_for_model` 是为了避开窗口占用率派生出来的 HardTop——本文件只测闸门本身。
    """
    from memory.runtime import try_extend_c2
    from memory.simulator.params import Params

    monkeypatch.setenv("XEYO_C2_MARGIN", theta_env)  # θ 的两个因子之一，env 是唯一覆盖面
    w = WorkingSnapshot()
    w.session_id = "s_gate_contract"
    w.compact_cursor = cursor
    w.c1_frozen_until = cursor
    w.turns_since_c2 = 999
    msgs = msgs or _big_msgs(40)
    acct: dict = {}
    ok = try_extend_c2(
        w, msgs, len(msgs) - 4,
        Params(window_tokens=window_tokens),
        account=acct,
    )
    return ok, acct, w


def test_theta_veto_is_recorded_in_fold_events(monkeypatch, mem_switch):
    """否决本身必须进账：否则"这道门挡了多少次、每次差多少"仍要靠重放转录倒推。"""
    from usage.ledger import fold_events_path

    monkeypatch.setenv("XEYO_C2_MARGIN", "1e9")  # θ 拉到不可能通过（env 是它唯一的覆盖面）
    w = _press(monkeypatch, mem_switch, msgs=_big_msgs(40), cursor=8, context_limit=1_000_000)
    rows = _rows(fold_events_path())
    vetoed = [r for r in rows if not r.get("fold")]
    assert vetoed, f"θ 拉到 1e9 却没有任何否决行：{rows}"
    assert vetoed[-1].get("reason") in ("pays_back_too_slow", "gain_below_floor")
    assert vetoed[-1].get("theta") is not None, "否决行必须带判据数字，否则无法复算"
    assert w.compact_cursor == 8, "否决不许动游标（动了就是投影整段重排）"
