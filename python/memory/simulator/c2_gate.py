"""c2_gate — Path A：把 C2 触发阈值/保尾常量改成「从 XEYO 成本模型推导的公式」。

诊断根因：XEYO 的 v61 **每轮 decide 都可能触发 C2**（基线：sess_real_200turn_c2 上
decide 605 次、apply_c2_messages 456 次 = 75.4% 处于压缩态、边界推进 11 次 =
11 次历史前缀改写 → 累计命中率被拉低）。同类实现只在「head-anchored + 保尾 + 压力阈值」
同时满足时才触发。本模块把 C2 的**触发时机**换成从成本模型/窗口几何推导的公式，
而不是硬编码的 ``c2_min_gain_chars`` / ``c2_min_save_ratio`` / ``0.62`` 等常量。

**红线**：所有公式只在对应 ``XEYO_C2_*`` 开关打开时生效；开关关（默认）时，
``runtime._c2_gain_enough`` / ``try_extend_c2`` / ``context_compact_ratio`` 走
**冻结行为，逐字节不变**（回归必绿）。HardTop 兜底永远保留——窗口真快溢出时
仍强制压缩，防止「调严导致尾溢出」。

公式来源（params.py，与 alpha_win / window_tokens / reserve_tokens 同源）：
- 压力门  = ``(l_hard_send − output_reserve − tail_budget) / window`` —— **窗口自适应**。
  l_hard_send = window − reserve（硬顶，随窗口变），output_reserve 给本轮输出留余量、
  tail_budget 保尾。三者都随窗口/模型调整，因此切换模型（128k→1M）时压力门仍
  「离硬顶留够余量才压」，不串味（取代旧 ``(l_max − tail_budget)/window`` 在窗口大时
  与硬顶严重错位的缺陷）。
- 收益门  = 复用 ``try_extend_c2`` 已有经济公式：改写当轮一次性 miss 必须能被
  剩余轮次 × 每轮省 token 摊平（``remaining_turns·saved/turn ≥ margin·price_ratio·miss``），
  随 remaining_turns 动态，而不是固定 0.40 / 8000 字符。
- 保尾    = ``per_turn_tokens × retain_rounds``（从真录统计每轮均 token；本仓基线
  ≈717 tok/轮，×3 轮 ≈2150 tok —— 不要再拍 24k）。
- 扩展条件 = 同一经济公式。

每个开关独立（memory_switches.py 注册表 + GUI「记忆系统开关」面板逐项可回退）。
"""

from __future__ import annotations

from typing import Any


# ===========================================================================
# 公式化门控（全部纯函数、确定性；不调用任何模型，零费用）
# ===========================================================================


def pressure_ratio(*, window: int, l_hard_send: int, output_reserve: int, tail_budget: int) -> float:
    """压力门 = (l_hard_send − output_reserve − tail_budget) / window —— **窗口自适应**。

    设计（切换模型/窗口大小不一致时结果不串味）：
    - ``l_hard_send = window − reserve``（硬顶，随窗口变）。
    - ``output_reserve``：给本轮输出预留的 token（如 o_mean），保证「离硬顶留够输出余量才压」。
    - ``tail_budget``：必须保留的尾预算。
    三者都随窗口/模型调整，因此压力门是**相对窗口的比例**，任何模型下都「刚好在离硬顶
    留够输出+保尾余量时触发」，不会小窗口触发太晚、大窗口触发太早。

    （取代旧的 ``(l_max − tail_budget)/window``——l_max=alpha_win·window 在窗口大时
    与硬顶严重错位；改为用 l_hard_send 直接对齐「离硬顶的余量」。）
    """
    win = max(1, int(window))
    reserve = max(0, int(output_reserve))
    budget = max(0, int(tail_budget))
    num = int(l_hard_send) - reserve - budget
    return max(0.0, min(1.0, num / win))


def economic_gain_ok(
    *,
    region_chars: int,
    summary_chars: int,
    tail_chars: int,
    remaining_turns: int,
    margin: float,
    price_ratio: float,
    min_save_ratio: float = 0.0,
    min_gain_chars: int = 0,
) -> bool:
    """收益门：压缩当轮有一次性 miss，必须能被后续省掉的 token 摊平（经济公式）。

    沿用 ``try_extend_c2`` 第 4 闸（price_ratio=miss/hit 价比，margin=安全边际）：

    ``remaining_turns × saved_per_turn ≥ margin × price_ratio × transition_miss``

    - ``region_chars``：待压缩区字符（被左段摘要替换掉的部分）。
    - ``summary_chars``：左段摘要字符（新生成的冻结文本）。
    - ``tail_chars``：压缩后右尾字符（保留）。
    - ``transition_miss`` = (summary + tail) / 4 —— 改写当轮新写的 token（miss）。
    - ``saved_per_turn`` = region / 4 —— 每轮省下的输入 token。

    **Path A 定参**：``price_ratio`` 可被 ``save`` 缩放（见 runtime._c2_gain_enough）——
    它是经济公式里唯一线性敏感的参数，任何场景下改变它都会改变「多少倍 miss 才值得压」。

    另保留两个**保守下限**作为显式豁免（经济公式在某些退化场景给出 0 收益时，
    仍要求「明显缩小」才压缩）：
    - ``min_gain_chars``：region 比 summary 至少大这么多字符（否则重写无意义）。
    - ``min_save_ratio``：压缩后投影 (summary+tail) 相对全量 (region+tail) 至少
      省这么多比例（否则尾体积大，压缩形同虚设）。

    全部返回 True 才允许压缩；任何一项不满足即拒绝 → 回退 keep（字节稳定）。
    """
    region = max(0, int(region_chars))
    summary = max(0, int(summary_chars))
    tail = max(0, int(tail_chars))
    if region <= 0:
        return False
    # 底层保守下限（显式豁免；0 表示不启用该下限）
    if min_gain_chars > 0 and (region - summary) < min_gain_chars:
        return False
    full = region + tail
    compact = summary + tail
    if full > 0 and min_save_ratio > 0 and compact / full > (1.0 - min_save_ratio):
        return False
    # 经济公式：一次性 miss 必须能被剩余轮次 × 每轮省 token 摊平
    if not (margin > 0 and price_ratio > 0):
        return True
    transition_miss_tok = (summary + tail) / 4.0
    saved_per_turn_tok = region / 4.0
    if transition_miss_tok <= 0:
        return True
    budget = remaining_turns * saved_per_turn_tok
    need = margin * price_ratio * transition_miss_tok
    return budget >= need


def tail_budget_tokens(*, per_turn_tokens: float, retain_rounds: int) -> int:
    """保尾 ≈ 每轮均 token × 保留轮数（从真录统计 per_turn_tokens，别拍固定值）。"""
    return max(0, int(round(float(per_turn_tokens or 0.0) * max(1, int(retain_rounds)))))




# ===========================================================================
# params 派生（从 Params 读几何量）
# ===========================================================================




def l_hard_send_from(params: Any) -> int:
    """l_hard_send = window − reserve（窗口硬顶，随窗口变）；与 params.l_hard_send 属性一致。"""
    return int(getattr(params, "l_hard_send") or (
        int(getattr(params, "window_tokens")) - int(getattr(params, "reserve_tokens"))
    ))


def window_from(params: Any) -> int:
    return max(1, int(getattr(params, "window_tokens") or 0))


def price_ratio_margin(params: Any) -> tuple[float, float]:
    """(price_ratio, margin)，默认对齐 params（30.0, 2.0）。"""
    pr = float(getattr(params, "c2_extend_price_ratio", 30.0) or 30.0)
    mg = float(getattr(params, "c2_extend_safety_margin", 2.0) or 2.0)
    return pr, mg
