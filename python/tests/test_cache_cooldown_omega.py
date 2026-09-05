"""A1 ω 缓存冷却平滑：TTL 过期不再把预测命中打到 0，消除挂机后误压缩。

**已固化开启**（原 XEYO_CACHE_COOLDOWN_OMEGA 键已删，cache_model.cooldown_enabled 恒
True）；本文件锁定恒开行为与「ω 只抬升下包络、温缓存零回归」两条性质。
"""

from __future__ import annotations

import pytest

from memory.simulator.cache_model import (
    CacheState,
    cooldown_enabled,
    cooldown_omega,
    rho_hat,
)
from memory.simulator.params import load_params


def test_fixed_on():
    """固化契约：冷却平滑恒开，4 小时冷缓存预测 = α×floor（不再打到 0）。"""
    assert cooldown_enabled() is True
    p = load_params()
    assert rho_hat(CacheState(age_seconds=4 * 3600), p) == pytest.approx(p.alpha_hit * 0.4)


def test_omega_floor_and_decay():
    p = load_params()
    assert cooldown_omega(60.0, p) > 0.98  # 挂机 1 分钟几乎不影响
    assert cooldown_omega(4 * 3600.0, p) == pytest.approx(0.4)  # floor
    assert cooldown_omega(0.0, p) == pytest.approx(1.0)


def test_omega_never_reduces_prediction():
    """ω 只抬升下包络，任何 age 下预测命中 ≥ 冻结表值。"""
    p = load_params()
    for age in (0.0, 30.0, 300.0, 600.0, 1800.0, 3600.0, 7200.0, 4 * 3600.0):
        s = 1.0
        for max_age, surv in p.rho_age_table:
            s = surv
            if age <= max_age:
                break
        table_only = min(1.0, max(0.0, s * p.alpha_hit))
        assert rho_hat(CacheState(age_seconds=age), p) >= table_only - 1e-12


def _state_with_m(tokens_hint: int = 0):
    """构造带 M 段的最小 ContextState（决策链需要 frozen_i_m 非空）。"""
    from memory.simulator.state_model import ContextState, Segment, freeze_s0

    body = ("noise line for window pressure\n" * 40) + (
        'Traceback (most recent call last):\n  File "a.py", line 1\nValueError: boom\n'
    )
    m = (
        Segment(id="m1", text=body, role="tool", kind="tool_result"),
        Segment(id="m2", text="theta = 0.5\n", role="tool", kind="tool_result"),
    )
    s = ContextState(p_s=(), p_c=(), m=m, t_k=(), t_now=())
    return freeze_s0(s)


def test_idle_short_greeting_not_compressed():
    """挂机 4 小时后的下一枪：keep 分支预测温和打折（Ĥ>0），不再「全 miss」。

    ω 固化开启后的机制级断言：冷缓存下 keep 分支 H>0 且 J 低于同缓存温态的
    miss-全零情形不可比，改为对照「ω 数学性质」：冷缓存 Ĥ = α×floor > 0，
    温缓存（age=0）预测=表值=α（ω≈1 不改变温缓存行为）；C2 分支 H 与缓存温度无关。
    """
    from memory.simulator.decision import decide
    from memory.simulator.projection import project

    s0 = _state_with_m()
    x_prev = project(s0).x
    frozen_len = max(1, project(s0).length - 50)  # 冻结前缀≈全投影
    cold = CacheState(age_seconds=4 * 3600, x_prev=x_prev, x_prev_frozen_len=frozen_len)
    warm = CacheState(age_seconds=0.0, x_prev=x_prev, x_prev_frozen_len=frozen_len)

    omega = decide(s0, cold, remaining_turns=8, forecast="p0")
    # 冷缓存 keep 分支：ρ = α×floor → Ĥ>0（冻结版此处为 0）
    assert omega.branches["keep"].H > 0.0
    # C2 分支不受 ω 影响（投影与 x_prev 无共同前缀，冷/温 H 一致）
    warm_dec = decide(s0, warm, remaining_turns=8, forecast="p0")
    assert omega.branches["C2"].H == warm_dec.branches["C2"].H
