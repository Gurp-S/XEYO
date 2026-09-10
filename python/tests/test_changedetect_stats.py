"""stats 模块的数值正确性测试。

这个文件是合约：所有数字都从已知闭式 / 已知样本算出来，错一个就是 bug。
McNemar 精确、bootstrap 区间、MDE 闭式、required_n 往返 都打表核对。
"""

from __future__ import annotations

import math
import random

import pytest

from evals.changedetect import stats


def test_z_for_default():
    assert math.isclose(stats.z_for(0.05), 1.959963984540054, rel_tol=1e-12)


def test_wilson_basic():
    # 50/100, 95% CI 应当含 0.5 且比正态近似稳
    lo, hi = stats.wilson(50, 100)
    assert lo < 0.5 < hi
    assert hi - lo < 0.20


def test_wilson_degenerate_zero_or_full():
    # Wilson 拒绝退化: 0/n 的上界 <1, k=n 的下界 >0（浮点容许极小 epsilon）
    lo, hi = stats.wilson(0, 10)
    assert -1e-12 < lo < 0.01
    assert 0.0 < hi < 0.5
    lo, hi = stats.wilson(10, 10)
    assert 0.5 < lo < 1.0
    assert 0.99 < hi <= 1.0


def test_mcnemar_exact_known_values():
    # 经典: b=10, c=0 → 双侧 p = 2 * 2^-10 = 0.001953125
    assert math.isclose(stats.mcnemar_exact(10, 0), 0.001953125, abs_tol=1e-9)
    # 对称: b=c=5 → p = 1.0（被上限封顶）
    assert stats.mcnemar_exact(5, 5) == 1.0
    # 一致: b=0, c=0 → p = 1.0
    assert stats.mcnemar_exact(0, 0) == 1.0
    # b=c=1 → p = 1.0
    assert stats.mcnemar_exact(1, 1) == 1.0


def test_mcnemar_normal_continuity_correction():
    # 极端不对称在大 n 下应非常显著
    p = stats.mcnemar_normal(50, 0)
    assert p < 1e-6
    # 对称大样本应不显著
    p = stats.mcnemar_normal(500, 500)
    assert p > 0.5


def test_required_pairs_round_trip_with_mde():
    for psi, delta in [(0.05, 0.02), (0.10, 0.05), (0.20, 0.10)]:
        n = stats.required_pairs(psi, delta)
        mde = stats.mde_paired(n, psi)
        # 反解回的 MDE 应 ≤ 目标 delta（确保 power ≥ 80%）
        assert mde <= delta * 1.001


def test_mde_paired_monotone_in_psi_and_n():
    m1 = stats.mde_paired(100, 0.05)
    m2 = stats.mde_paired(100, 0.20)
    m3 = stats.mde_paired(400, 0.05)
    assert m1 < m2          # 不一致越多 → 越容易看到
    assert m1 > m3          # 样本越大 → 越精确


def test_power_paired_zero_when_delta_zero():
    # δ=0 时 power = α (双侧), 不是 0——必须保留 α 的"误判"风险
    p = stats.power_paired(1000, 0.10, 0.0)
    assert 0.02 < p < 0.03


def test_power_paired_matches_mde_at_target():
    psi, alpha, power = 0.10, 0.05, 0.80
    delta = stats.mde_paired(500, psi, alpha, power)
    pwr = stats.power_paired(500, psi, delta, alpha)
    # MDE 定义就是 power = 80% 处的最小 delta；实际 power 应 ≈ 0.80
    assert math.isclose(pwr, power, abs_tol=0.005)


def test_required_unpaired_and_mde():
    # p=0.7, δ=1pp 应当需要大样本（实操约 33k/臂）—— 体现噪声地板
    n = stats.required_unpaired(0.7, 0.01)
    assert n > 30_000
    mde = stats.mde_unpaired(1600, 0.7)
    # 实测噪声地板 ~4.5pp → 1600/臂应当能分辨约 4.5pp 量级
    assert 0.03 < mde < 0.06


def test_bootstrap_ci_brackets_point():
    rng = random.Random(0)
    deltas = [rng.gauss(0.1, 0.05) for _ in range(200)]
    lo, pt, hi = stats.paired_bootstrap_ci(deltas, n_boot=5000, seed=42)
    assert lo <= pt <= hi
    assert 0.05 < pt < 0.15  # 均值应在 0.1 附近


def test_summarize_pairs_inconclusive_when_no_discordant():
    pairs = [(True, True), (False, False), (True, True)]
    rep = stats.summarize_pairs(pairs)
    assert rep["n_pairs"] == 3
    assert rep["verdict"] == "inconclusive"  # 全一致 → 配对检验无信息
    assert rep["p_value"] == 1.0
    # 没真实信号，mde 取全不一致假设下的值
    assert rep["mde"] > 0


def test_summarize_pairs_significant_drop():
    # 6 对全降: McNemar p = 2 * 0.5^6 = 0.03125 < 0.05
    pairs = [(True, False)] * 6
    rep = stats.summarize_pairs(pairs)
    assert rep["verdict"] == "negative"
    assert rep["delta"] < 0
    assert rep["p_value"] < 0.05


def test_summarize_pairs_significant_gain():
    pairs = [(False, True)] * 6
    rep = stats.summarize_pairs(pairs)
    assert rep["verdict"] == "positive"
    assert rep["delta"] > 0
    assert rep["p_value"] < 0.05


def test_power_table_shape():
    rows = stats.power_table()
    assert len(rows) == 4 * 4
    # δ 越大, 所需样本越少
    eff02 = next(r["required_pairs"] for r in rows if r["effect"] == 0.02 and r["discordant_rate"] == 0.10)
    eff10 = next(r["required_pairs"] for r in rows if r["effect"] == 0.10 and r["discordant_rate"] == 0.10)
    assert eff02 > eff10
