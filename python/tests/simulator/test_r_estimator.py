"""P1 缺失3：R 估算降级为约束条件（r_estimator 决策分级）。

验收（见交接提示词）：
- 窗口 75% 且 5 个待读文件 → {4:T, 8:T, 16:T}。
- 窗口 30% 且 0 待读 → {4:T, 8:F, 16:F}。
- 不得把 R 当作唯一选择器：r_gate 只约束哪些 horizon 参与决策/投票，Q/J/vote 不变。
"""

from __future__ import annotations

from memory.simulator.cache_model import CacheState
from memory.simulator.decision import decide
from memory.simulator.params import load_params
from memory.simulator.r_estimator import (
    RGate,
    count_unread_files,
    estimate_r_gate,
    usage_ratio_from_tokens,
)
from memory.simulator.scenarios import state_from_messages


def test_acceptance_75_and_5():
    g = estimate_r_gate(0.75, 5)
    assert g.allow[4] is True
    assert g.allow[8] is True
    assert g.allow[16] is True


def test_acceptance_30_and_0():
    g = estimate_r_gate(0.30, 0)
    assert g.allow[4] is True
    assert g.allow[8] is False
    assert g.allow[16] is False


def test_window_pressure_allows_16_even_without_unread():
    g = estimate_r_gate(0.80, 0)
    assert g.allow[4] is True
    assert g.allow[8] is False
    assert g.allow[16] is True


def test_unread_work_allows_8_and_16():
    g = estimate_r_gate(0.30, 4)
    assert g.allow[4] is True
    assert g.allow[8] is True
    assert g.allow[16] is True


def test_force_hardtop_defensive_never_triggered_by_rules():
    # 规则保证 allow[4] 恒真，因此 force_hardtop 恒为 False（防御性兜底）。
    for usage, unread in ((1.0, 0), (1.0, 100), (0.0, 0), (0.0, 2)):
        g = estimate_r_gate(usage, unread)
        assert g.allow[4] is True
        assert g.force_hardtop is False
        assert list(g.allow) == [4, 8, 16]


def test_usage_ratio_from_tokens():
    assert usage_ratio_from_tokens(64000, 128000) == 0.5
    assert usage_ratio_from_tokens(0, 128000) == 0.0
    assert usage_ratio_from_tokens(200000, 128000) == 1.0  # 超窗按 1.0 截断
    assert usage_ratio_from_tokens(100, 0) == 1.0  # 窗口未知按 1.0（防御）


def test_count_unread_files():
    assert count_unread_files({}) == 0
    assert count_unread_files({"a.py": {"offset": 0}}) == 1
    assert count_unread_files({"a.py": {"offset": 0}, "b.py": {"offset": 0}}) == 2


def test_decide_horizon_filter_is_constraint_not_selector():
    """r_gate 过滤允许的 horizon；Q/J/vote 公式不变（r_gate=None 时与旧行为一致）。"""
    msgs = [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "now"},
    ]
    s = state_from_messages(msgs)
    cache = CacheState()
    p = load_params()

    # r_gate=None（默认）→ 全档参与，feasible 含 4/8/16
    d_full = decide(s, cache, remaining_turns=8, params=p, forecast="p0")
    assert set(d_full.feasible.keys()) == {4, 8, 16}

    # r_gate={4:T,8:F,16:F}（窗口低且无待读）→ 只 4 档参与
    gate = RGate(allow={4: True, 8: False, 16: False})
    d_gate = decide(s, cache, remaining_turns=8, params=p, forecast="p0", r_gate=gate)
    assert set(d_gate.feasible.keys()) == {4}
    # 不可行的档默认 keep（不因不可行而捏造 C2 决策）
    assert d_gate.a8 == "keep"
    assert d_gate.a16 == "keep"
    # 投票仍走既有公式（best_n < 2 → keep）
    assert d_gate.a_vote in ("keep", "C1", "C2")
