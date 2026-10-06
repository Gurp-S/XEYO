"""实际投影增益门（候选臂，`memory/wsc_gain_candidates.py`）的契约测试。

钉的四件事：
1. 旗标默认关 ⇒ 一次测量都不做，判据与旧口径逐字同值（旁路上线的第一条红线）。
2. 开着时判据的比较对象是**两个完整候选的长度差**，门槛复用 `c2_min_gain_chars`；
   候选差为负不许截成 0（那正是该拒的形态）。
3. 测量失败 ⇒ 退回估算口径**并在账上记 `gain_arm`**，不许静默。
4. trial 不许动活的 `WorkingSnapshot`，也不许往生产会话的取回视图/头快照上写一个字节
   （影子档事故的同型风险：共写一份视图 ⇒ 生产头里的 `Read(offset=…)` 行号静默指错）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("synaptic")

from evals import wsc_gain_candidates as gc  # noqa: E402
from memory.working import WorkingSnapshot  # noqa: E402


def _params(min_gain: int = 4000, save_ratio: float = 0.0):
    return SimpleNamespace(c2_min_gain_chars=min_gain, c2_min_save_ratio=save_ratio,
                           c2_extend_theta=1.0)


def _msgs(n: int, size: int = 6000) -> list[dict]:
    return [{"role": "user", "content": "x" * size} for _ in range(n)]


def _working(cursor: int = 0, sid: str = "s_gain_contract") -> WorkingSnapshot:
    w = WorkingSnapshot()
    w.session_id = sid
    w.compact_cursor = cursor
    w.c1_frozen_until = cursor
    w.turns_since_c2 = 999
    return w


def _gate(monkeypatch, mem_switch, *, pair, msgs=None, cursor=0, min_gain=4000):
    """把候选臂的测量桩成给定 pair，返回 `(判据, account)`。"""
    from memory.runtime import _c2_gain_enough

    mem_switch(XEYO_L5="v61")
    monkeypatch.setenv("XEYO_WSC_GAIN_CANDIDATES", "1")
    monkeypatch.setattr(gc, "measure_pair", lambda *a, **k: pair)
    acct: dict = {}
    measured = gc.measure_pair(msgs or _msgs(4), _working(cursor), 3, cwd=".", context_limit=None)
    acct.update(gc.account_fields(measured))
    ok = (gc.gain_ok(measured, min_gain) if measured is not None else
          _c2_gain_enough(msgs or _msgs(4), _working(cursor), 3, _params(min_gain), account=acct))
    return ok, acct


def test_default_off_never_measures(monkeypatch, mem_switch) -> None:
    """旗标不设 ⇒ 连测量函数都不许被碰到（默认路径逐字节不变的硬证）。"""
    from memory.runtime import _c2_gain_enough

    mem_switch(XEYO_L5="v61")
    monkeypatch.delenv("XEYO_WSC_GAIN_CANDIDATES", raising=False)

    def _boom(*a, **k):
        raise AssertionError("默认档不该做候选测量")

    monkeypatch.setattr(gc, "measure_pair", _boom)
    acct: dict = {}
    ok = _c2_gain_enough(_msgs(4), _working(), 3, _params(), account=acct, cwd=".")
    assert ok is True                       # 估算口径下 4×6000 字符区 vs 小摘要：放行
    assert acct["gain_arm"] == gc.GAIN_ARM_ESTIMATE
    assert "projection_saved_tokens" not in acct


def test_candidate_arm_decides_on_pair_difference(monkeypatch, mem_switch) -> None:
    ok_big, acct = _gate(monkeypatch, mem_switch, pair=gc.CandidatePair(10_000, 5_000))
    assert ok_big is True                   # 差 5,000 ≥ 门槛 4,000
    assert acct["gain_arm"] == gc.GAIN_ARM_CANDIDATE
    assert acct["projection_saved_tokens"] == (10_000 - 5_000) // 4
    assert acct["gain_counter"] == gc.GAIN_COUNTER

    ok_small, _ = _gate(monkeypatch, mem_switch, pair=gc.CandidatePair(40_000, 36_500))
    assert ok_small is False                # 原文差很大但**发射面只差 3,500** ⇒ 拒
    # 上一条正是这道门要修的东西：估算口径（region 40,000 字符 vs 小摘要）会放行。


def test_negative_difference_is_not_clamped(monkeypatch, mem_switch) -> None:
    ok, acct = _gate(monkeypatch, mem_switch, pair=gc.CandidatePair(5_000, 9_000))
    assert ok is False
    assert acct["projection_saved_tokens"] == (5_000 - 9_000) // 4
    assert acct["projection_saved_tokens"] < 0   # 折了反而更长：如实记账，不许抹成 0


def test_measure_failure_falls_back_and_is_recorded(monkeypatch, mem_switch) -> None:
    """测量失败必须**可见**：退回估算口径 + 记 `gain_arm=估算`，不许静默当成候选臂。"""
    ok, acct = _gate(monkeypatch, mem_switch, pair=None, min_gain=4000)
    assert acct["gain_arm"] == gc.GAIN_ARM_ESTIMATE
    assert acct["projection_saved_tokens"] is None
    assert ok is True                       # 估算口径的结论（与默认档同值）


def test_saved_net_meaning_is_untouched() -> None:
    """`saved_net` 不许原地改含义：加不加新字段，它和 `transition` 必须同值。"""
    from memory.runtime import _size_gate_fold_account

    msgs = _msgs(6)
    w = _working(cursor=0)
    base = _size_gate_fold_account(msgs, w, 4, forced=False)
    with_gain = _size_gate_fold_account(msgs, w, 4, forced=False,
                                        gain={"projection_saved_tokens": 123, "gain_counter": "c"})
    assert base and with_gain
    for key in ("saved_net", "transition", "region_chars", "region_tokens", "head_tokens"):
        assert base[key] == with_gain[key], key
    assert base["saved_net_basis"] == "c2_estimate"
    assert with_gain["projection_saved_tokens"] == 123


def test_trial_id_survives_the_safe_truncation_trap() -> None:
    """`_safe` 把会话名截到 40/64 字符 ⇒ 拿 `sid+后缀` 做 trial 名会在长 sid 上撞回生产文件。"""
    from memory.wsc_projection import _safe, _view_path_for

    for sid in ("sess_mumrnbtz_kf5hge", "s" * 80, ""):
        tid = gc._trial_id(sid)
        assert len(_safe(tid)) == len(tid), "trial 名被截断 ⇒ 可能与生产视图同名"
        assert _view_path_for(".", tid) != _view_path_for(".", sid)
    assert gc._trial_id("a") != gc._trial_id("b")


def test_trial_does_not_move_live_state_or_touch_production_view(tmp_path, monkeypatch,
                                                                 mem_switch) -> None:
    """真跑两臂（不桩），证明：活快照没被改、生产视图没被写、trial 产物已被清掉。"""
    from memory.wsc_projection import _view_path_for

    mem_switch(XEYO_L5="v61")
    monkeypatch.setenv("XEYO_WSC", "1")
    monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
    # 两臂必须在"decide 已经点了 C2"的世界裡比（生产里这道门就是在那一支里被问的），
    # 否则两臂都走 keep 分支、逐字相同 —— 那正是上一版空转桩的形态。
    monkeypatch.setattr(
        "memory.simulator.decision.decide",
        lambda *a, **k: SimpleNamespace(
            a_star="C2", hardtop=False,
            branches={"keep": SimpleNamespace(x="K"), "C1": SimpleNamespace(x="C"),
                      "C2": SimpleNamespace(x="C2")},
        ),
    )
    live_view = _view_path_for(str(tmp_path), "s_gain_contract")
    live_view.parent.mkdir(parents=True, exist_ok=True)
    live_view.write_text("PRE-EXISTING\n", encoding="utf-8")

    w = _working(cursor=0)
    msgs = _msgs(8, size=4000)
    pair = gc.measure_pair(msgs, w, 6, cwd=str(tmp_path), context_limit=1_000_000)

    assert pair is not None, f"两臂测量失败：{pair}"
    assert pair.keep_chars > 0 and pair.fold_chars > 0
    # 空转桩自校：这一枪的候选差必须为正且够大，否则"两臂其实没分岔"就又回来了
    # （上一版把 fold 臂的 try_extend_c2 也钉成桩 ⇒ 游标不前移 ⇒ 两臂逐字相同 ⇒ saved≡0）。
    assert pair.saved_chars > 0, f"两臂没有分岔：keep={pair.keep_chars} fold={pair.fold_chars}"
    assert w.compact_cursor == 0, "trial 动了活快照的游标"
    assert not getattr(w, "c2_summary_text", "")
    assert live_view.read_text(encoding="utf-8") == "PRE-EXISTING\n", "trial 写了生产取回视图"
    leftover = sorted(p.name for p in live_view.parent.glob("gt-*"))
    assert not leftover, f"trial 产物没清干净：{leftover}"


def test_fold_arm_is_a_real_counterfactual_not_thetas_own_answer(monkeypatch, mem_switch, tmp_path) -> None:
    """θ 此刻拒绝的那一枪，候选差仍必须量得出"真折一次会发什么"。

    否则候选门拿到 0 就判"不折"——那只是把 θ 的回答抄回来，不是独立测量。
    （实测踩过：`_arm(fold=True)` 不放开 `force` 时，两个被 θ 拒的决策点
    `keep_chars` 与 `fold_chars` 逐字相等，各 46,526 / 55,454。）
    """
    from dataclasses import replace

    from memory.simulator.params import load_params
    from memory.runtime import try_extend_c2

    mem_switch(XEYO_L5="v61")
    monkeypatch.setenv("XEYO_WSC", "1")
    monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
    # θ = price_ratio × margin / PAYBACK_SHOTS（`synaptic.cadence.theta_required`）
    # ⇒ 把 margin 抬到不可能满足，就能造出"θ 这一枪拒绝"的决策点。
    strict = replace(load_params(), c2_extend_safety_margin=1e9)
    monkeypatch.setattr("memory.simulator.params.load_params", lambda *a, **k: strict)

    msgs = _msgs(40, size=6000)
    w = _working(cursor=6, sid="s_gain_theta")
    w.c2_summary_text = "SUMMARY-KEPT-VERBATIM\n"
    new_cursor = 20
    acct: dict = {}
    assert try_extend_c2(w, msgs, new_cursor, strict, account=acct) is False, acct
    assert acct.get("reason") not in (None, ""), "θ 门没记账 ⇒ 这一枪根本没被评估"

    # 机制级断言：fold 臂必须让"这一枪真折一次"发生，否则候选差只是 θ 的回声。
    import copy

    import memory.runtime as rt
    trial = copy.deepcopy(w)
    with gc._arm(fold=True):
        folded = rt.try_extend_c2(trial, msgs, new_cursor, strict, account={})
    assert folded is True, "fold 臂没真折：两臂会逐字相同，候选差退化成 0"
    assert trial.compact_cursor == new_cursor
    assert w.compact_cursor == 6, "测量把活快照折进去了"


def test_offline_candidate_flag_cannot_change_live_gate(tmp_path, monkeypatch, mem_switch) -> None:
    """接线证据：候选臂放行时，`fold_events` 那一行必须带上两个新字段与计数器名。"""
    import memory.runtime as rt
    from usage.ledger import fold_events_path

    mem_switch(XEYO_L5="v61")
    monkeypatch.setenv("XEYO_WSC", "1")
    monkeypatch.setenv("XEYO_WSC_GAIN_CANDIDATES", "1")
    monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
    monkeypatch.setattr(
        "memory.simulator.decision.decide",
        lambda *a, **k: SimpleNamespace(
            a_star="C2", hardtop=False,
            branches={"keep": SimpleNamespace(x="K"), "C1": SimpleNamespace(x="C"),
                      "C2": SimpleNamespace(x="C2")},
        ),
    )
    monkeypatch.setattr(gc, "measure_pair",
                        lambda *a, **k: gc.CandidatePair(200_000, 100_000))

    w = _working(cursor=0, sid="s_gain_ledger")
    rt.project_for_model(_msgs(40, size=6000), w, remaining_turns=30,
                         context_limit=1_000_000, cwd=str(tmp_path), include_memory_index=False)
    assert w.compact_cursor > 0, "候选臂放行却没折 ⇒ 接线没通（夹具：切点没推进）"

    rows = [json.loads(ln) for ln in fold_events_path().read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    mine = [r for r in rows if r.get("session_id") == "s_gain_ledger"]
    assert mine, "fold_events 一行都没写 ⇒ 观测缺口还在"
    row = mine[-1]
    assert row["gain_arm"] == gc.GAIN_ARM_ESTIMATE
    assert "projection_saved_tokens" not in row
    assert row["saved_net_basis"] == "c2_estimate"
    assert isinstance(row["saved_net"], int), "saved_net 被新字段挤掉了含义"
