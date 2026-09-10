"""budget —— 把"再跑几组才能测出来"折算成人民币。

没有这一层，"完美侦测"就是一句空话：用户没法判断一次评测值不值。有了它，
每次统计实验开跑之前先报价，超预算直接拒绝执行，而不是跑完才发现烧了一堆钱。

价格口径有两个预设，都显式标注来源：
  official-new  2026-09-10 官方新价（命中 0.02 / 未命中 1.0 / 输出 4.0 元/百万）
  repo-local    仓库内 usage/pricing.py 的本地表，**已知未更新新价且仍带
                peak×2**，仅用于对比与回归，不应当作真实账单
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 2026-09-10 官方新价（元 / 百万 token）
PRESET_OFFICIAL_NEW: dict[str, float] = {"hit": 0.02, "miss": 1.0, "out": 4.0}

#: 预算法默认标定：来自 P2 全量实测（89 题 ¥26.48 → ¥0.2975/题·次）
DEFAULT_COST_PER_TASK_RUN_CNY = 0.2975
DEFAULT_CALIBRATION_NOTE = "P2 全量实测 89 题 ¥26.48（2026-09-10，新价口径）"

#: 单题单次的参考 token 形态（用于在没有标定数据时给出量级感）
REFERENCE_TOKENS_PER_TASK_RUN: dict[str, int] = {
    "input_hit": 757_000,   # 缓存命中段：占量 86%，占钱 ~5%
    "input_miss": 34_400,
    "output": 62_000,
}


@dataclass(frozen=True)
class Price:
    hit: float
    miss: float
    out: float
    source: str

    def cost_cny(self, *, hit_tokens: int, miss_tokens: int, out_tokens: int) -> float:
        return (
            hit_tokens * self.hit + miss_tokens * self.miss + out_tokens * self.out
        ) / 1_000_000.0


def preset(name: str = "official-new") -> Price:
    if name in ("official-new", "official", "new"):
        return Price(**PRESET_OFFICIAL_NEW, source="2026-09-10 官方新价")
    if name in ("repo-local", "local", "repo"):
        try:
            from usage.pricing import unit_prices_cny_per_mtoken

            hit, miss, out, _w = unit_prices_cny_per_mtoken(
                provider="deepseek", model="flash", ts=0.0, slot="offpeak"
            )
            return Price(
                hit=float(hit),
                miss=float(miss),
                out=float(out),
                source="usage/pricing.py 本地表（未更新新价，仅作对比）",
            )
        except Exception as exc:  # noqa: BLE001
            return Price(
                **PRESET_OFFICIAL_NEW, source=f"本地表不可用({type(exc).__name__})，回退新价"
            )
    raise ValueError(f"未知价格预设：{name}（可选 official-new / repo-local）")


def estimate_from_calibration(
    calibration: dict[str, Any] | None,
    *,
    price: Price,
) -> tuple[float, str]:
    """用历史 A/B 报告里的实测 token 形态估算「每题每臂」花费。"""
    if not calibration:
        return DEFAULT_COST_PER_TASK_RUN_CNY, DEFAULT_CALIBRATION_NOTE
    per = calibration.get("cost_per_task_run_cny")
    if isinstance(per, (int, float)) and per > 0:
        return float(per), str(calibration.get("note") or "来自标定文件")
    hits = int(calibration.get("input_hit", 0))
    miss = int(calibration.get("input_miss", 0))
    out = int(calibration.get("output", 0))
    if hits or miss or out:
        cost = price.cost_cny(hit_tokens=hits, miss_tokens=miss, out_tokens=out)
        return cost, "由标定文件的 token 形态换算"
    return DEFAULT_COST_PER_TASK_RUN_CNY, DEFAULT_CALIBRATION_NOTE


def plan(
    *,
    n_tasks: int,
    repeats: int,
    arms: int = 2,
    price: Price | None = None,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """开跑前的报价单。"""
    price = price or preset()
    per_run, note = estimate_from_calibration(calibration, price=price)
    runs = n_tasks * repeats * arms
    return {
        "n_tasks": n_tasks,
        "repeats": repeats,
        "arms": arms,
        "total_runs": runs,
        "cost_per_task_run_cny": round(per_run, 4),
        "estimated_total_cny": round(per_run * runs, 2),
        "price_preset": price.source,
        "calibration": note,
        "reference_tokens_per_task_run": REFERENCE_TOKENS_PER_TASK_RUN,
    }


def check_budget(plan_dict: dict[str, Any], budget_cny: float | None) -> dict[str, Any]:
    """预算门：无上限则视为未授权实跑。"""
    est = float(plan_dict.get("estimated_total_cny") or 0.0)
    if budget_cny is None:
        return {
            "allowed": False,
            "reason": "未提供 --budget；实跑必须显式给出人民币上限（先看报价再决定）",
            "estimated_total_cny": est,
        }
    if est > budget_cny:
        return {
            "allowed": False,
            "reason": (
                f"预估 ¥{est:.2f} 超出上限 ¥{budget_cny:.2f}；"
                f"减少 --repeats / 缩小 --tasks 或提高 --budget"
            ),
            "estimated_total_cny": est,
        }
    return {"allowed": True, "reason": "在预算内", "estimated_total_cny": est}
