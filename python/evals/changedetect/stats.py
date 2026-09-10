"""stats —— L2 统计核（纯函数，零依赖，可离线自测）。

这个模块存在的唯一理由是**把"侦测不到"变成可计算的数**。

背景：真模型是随机的，同一份代码重跑两次通过率本身就会差几个百分点
（XEYO 实测噪声地板 4.1~4.5pp）。在这种噪声下，"改个 prompt 看分数"这种
做法对小改动完全没有分辨力——差别被噪声吃掉，看起来"没变"。

这里给出三件事：
1. 已测到的差异有多可信（McNemar 精确检验 / Wilson 区间 / 配对 bootstrap）；
2. **这次实验的分辨力下限 MDE**（最小可侦测效应）——低于它的差异，本次
   实验在数学上就不可能被判为显著，所以只能说"未测出"，不能说"没变化"；
3. **要测出 δ 需要多少样本**（预算法）：把"完美侦测"翻译成一个价格。

配对设计（A/B 都在同一批任务上跑）用的是 McNemar；连续量（成本、token、
耗时）用配对 bootstrap。
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from statistics import NormalDist

_NORM = NormalDist()

#: 双侧检验默认显著性
ALPHA = 0.05
#: 默认统计功效（漏检率 20%）
POWER = 0.80

#: 精确二项检验的最大 n；超过则用带连续性校正的正态近似（避免浮点下溢）
_EXACT_MAX_N = 500


def z_for(alpha: float = ALPHA) -> float:
    """双侧检验的临界 z。"""
    return _NORM.inv_cdf(1.0 - alpha / 2.0)


def z_power(power: float = POWER) -> float:
    return _NORM.inv_cdf(power)


def wilson(k: int, n: int, alpha: float = ALPHA) -> tuple[float, float]:
    """比例的 Wilson 得分区间（小样本比正态近似稳）。"""
    if n <= 0:
        return (0.0, 1.0)
    z = z_for(alpha)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确检验（双侧）。

    b = 「A 通过而 B 未通过」的配对任务数；c = 反向。
    只有不一致对（b+c）携带信息；两侧都过/都挂的不计入。
    """
    n = b + c
    if n == 0:
        return 1.0
    if n > _EXACT_MAX_N:
        return mcnemar_normal(b, c)
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5**n)
    return min(1.0, 2.0 * tail)


def mcnemar_normal(b: int, c: int) -> float:
    """McNemar 正态近似（带连续性校正，仅大样本用）。"""
    n = b + c
    if n == 0:
        return 1.0
    stat = (abs(b - c) - 1) ** 2 / n
    # 卡方(1) 的生存函数 = 2 * (1 - Φ(sqrt(stat)))
    return max(0.0, min(1.0, 2.0 * (1.0 - _NORM.cdf(math.sqrt(max(0.0, stat))))))


def discordant_rate(b: int, c: int, n_pairs: int) -> float:
    """不一致对占比 ψ——它是配对设计的敏感度命门：ψ 越小越难测。"""
    if n_pairs <= 0:
        return 0.0
    return (b + c) / n_pairs


def mde_paired(
    n_pairs: int,
    psi: float,
    alpha: float = ALPHA,
    power: float = POWER,
) -> float:
    """配对设计的最小可侦测效应（通过率之差，绝对值）。

    闭式解：δ_min = (z_{1-α/2} + z_power) · sqrt(ψ / n)

    ψ = 不一致对占比。注意 ψ 是**先验**量：实验前只能用经验值估，
    实验后应当用实测 ψ 反算"本次真实分辨力"。
    """
    if n_pairs <= 0 or psi <= 0:
        return 1.0
    return (z_for(alpha) + z_power(power)) * math.sqrt(psi / n_pairs)


def required_pairs(
    psi: float,
    delta: float,
    alpha: float = ALPHA,
    power: float = POWER,
) -> int:
    """要测出 δ 需要多少配对样本（mde_paired 的逆解）。"""
    if delta <= 0 or psi <= 0:
        return 0
    z = z_for(alpha) + z_power(power)
    return int(math.ceil(psi * (z**2) / (delta**2)))


def power_paired(
    n_pairs: int,
    psi: float,
    delta: float,
    alpha: float = ALPHA,
) -> float:
    """给定样本量/不一致率，测出 δ 的统计功效。"""
    if n_pairs <= 0 or psi <= 0:
        return 0.0
    return _NORM.cdf(math.sqrt(n_pairs) * abs(delta) / math.sqrt(psi) - z_for(alpha))


def mde_unpaired(
    n_per_arm: int,
    p: float,
    alpha: float = ALPHA,
    power: float = POWER,
) -> float:
    """非配对（两组独立跑）的最小可侦测效应。

    用来回答那个最扎心的问题：连"噪声地板 4.5pp"本身要多少样本才看得见。
    """
    if n_per_arm <= 0 or not (0.0 < p < 1.0):
        return 1.0
    z = z_for(alpha) + z_power(power)
    return z * math.sqrt(2.0 * p * (1.0 - p) / n_per_arm)


def required_unpaired(
    p: float,
    delta: float,
    alpha: float = ALPHA,
    power: float = POWER,
) -> int:
    """非配对设计每臂所需样本数。"""
    if delta <= 0 or not (0.0 < p < 1.0):
        return 0
    z = z_for(alpha) + z_power(power)
    return int(math.ceil(2.0 * (z**2) * p * (1.0 - p) / (delta**2)))


def paired_bootstrap_ci(
    deltas: Sequence[float],
    *,
    n_boot: int = 10_000,
    alpha: float = ALPHA,
    seed: int = 20260910,
) -> tuple[float, float, float]:
    """配对 bootstrap：返回 (下界, 点估计, 上界)。

    用于成本 / token / 耗时这类连续量。deltas 是**逐任务配对差**。
    """
    vals = [float(d) for d in deltas]
    if not vals:
        return (0.0, 0.0, 0.0)
    point = sum(vals) / len(vals)
    if len(vals) == 1:
        return (point, point, point)
    rng = random.Random(seed)
    n = len(vals)
    means: list[float] = []
    for _ in range(n_boot):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return (lo, point, hi)


def summarize_pairs(
    pairs: Sequence[tuple[bool, bool]],
    *,
    alpha: float = ALPHA,
    power: float = POWER,
) -> dict:
    """配对二元结果的完整裁决。

    pairs: [(A 是否通过, B 是否通过), …]，同一任务同一重复序号配成一对。
    """
    n = len(pairs)
    if n == 0:
        return {"n_pairs": 0, "verdict": "no_data"}
    a_only = sum(1 for a, b in pairs if a and not b)  # b 变差
    b_only = sum(1 for a, b in pairs if b and not a)  # b 变好
    both = sum(1 for a, b in pairs if a and b)
    neither = sum(1 for a, b in pairs if not a and not b)
    pa = (a_only + both) / n
    pb = (b_only + both) / n
    delta = pb - pa
    p_value = mcnemar_exact(a_only, b_only)
    psi = discordant_rate(a_only, b_only, n)
    # 已实测 ψ 可用时才可信；全一致时退回保守假设（全部对都不一致）
    psi_for_mde = psi if psi > 0 else 1.0
    mde = mde_paired(n, psi_for_mde, alpha, power)
    significant = p_value < alpha
    if not significant:
        verdict = "inconclusive"
    elif delta > 0:
        verdict = "positive"
    else:
        verdict = "negative"
    return {
        "n_pairs": n,
        "a_pass": a_only + both,
        "b_pass": b_only + both,
        "both_pass": both,
        "both_fail": neither,
        "a_only_pass": a_only,
        "b_only_pass": b_only,
        "pass_rate_a": pa,
        "pass_rate_b": pb,
        "wilson_a": wilson(a_only + both, n, alpha),
        "wilson_b": wilson(b_only + both, n, alpha),
        "delta": delta,
        "discordant_rate": psi,
        "p_value": p_value,
        "alpha": alpha,
        "power": power,
        "mde": mde,
        "significant": significant,
        "verdict": verdict,
        "resolution_note": (
            f"本次 {n} 对样本，不一致率 {psi:.1%}，"
            f"只能可靠测出 ≥{mde:.2%} 的通过率变化；"
            f"更小的变化落在分辨力之下，测不出≠没变化。"
        ),
    }


def power_table(
    *,
    effects: Sequence[float] = (0.01, 0.02, 0.05, 0.10),
    psi_values: Sequence[float] = (0.02, 0.05, 0.10, 0.20),
    alpha: float = ALPHA,
    power: float = POWER,
) -> list[dict]:
    """预算法：每个 (效应, 不一致率) 组合需要多少配对样本。"""
    rows: list[dict] = []
    for psi in psi_values:
        for eff in effects:
            rows.append(
                {
                    "effect": eff,
                    "discordant_rate": psi,
                    "required_pairs": required_pairs(psi, eff, alpha, power),
                }
            )
    return rows
