"""会话上下文用量一行事实（T_now 块 ``context_usage`` 的正文来源）。

为什么必须在上下文：模型无法从自身输入推断"这一枪有多大"，也拿不到会话的容量分母
⇒ 只能把"还早 / 该收了"这类判断留成未判断（与 ``time_now`` 缺基准同形，
实测那次模型把一批时效判断留成"未核对"）。

口径与禁区：
- 分母**不取** ``params.window_tokens``：离线校准常量（恒 128k），本仓多处明令
  不得当判据（会让 C2 误以为窗口只有 128k）。分母只认**用户在设置里登记的**上下文
  窗口（``declared_window_tokens``）；未登记只报分子，不编分母。
- **阈值类配置不进这一行**（2026-10-08 用户裁定）：水位/压缩比是配置常量、单位与
  测量值还不同，并排摆会让"每枪都动的测量值"看起来像常量；压力阈值由引擎在执行层用。
- 纯数字事实，不含"接近上限 / 该压缩了 / 注意余量"一类编排文本
  （引擎铁律：限制只在执行层表达）。
- 任何异常 → 空串：该块本轮缺席，绝不阻断主循环。
"""

from __future__ import annotations

import json
import os
from typing import Any

#: 没有厂商真值时是否允许退回估算。默认**关**：est 与随后出现的 vendor 会在同一轮
#: 里给出两个互相矛盾的数字（实测 world_state 段同时印出 est 251k 与 vendor 294k），
#: 错的锚比没有锚更坏。只在"该后端从不回 usage"时才显式打开。
ENV_ALLOW_EST = "XEYO_CONTEXT_USAGE_ALLOW_EST"


def _allow_est() -> bool:
    return os.environ.get(ENV_ALLOW_EST, "").strip().lower() in {"1", "true", "yes", "on"}

#: 粗估比例：4 字符 ≈ 1 token。只用于给出规模量级，不做配额判定（配额在执行层）。
_CHARS_PER_TOKEN = 4


def estimate_tokens(projected: list[dict[str, Any]]) -> int:
    """本次 payload 的估算 token；算不出返回 0。"""
    try:
        text = json.dumps(projected, ensure_ascii=False)
    except (TypeError, ValueError):
        return 0
    return max(0, len(text) // _CHARS_PER_TOKEN)


def vendor_input_tokens(last_usage: dict[str, Any] | None) -> int:
    """上一次请求的**输入** token（厂商回传，含 system+tools+全历史）；没有返回 0。

    这是"这一枪有多大"的权威值：``est`` 只看本次 payload，**不含**系统前缀与工具
    schema，只是下界。键名按主流两家（``prompt_tokens`` / ``input_tokens``）取，
    明细分组（cache hit/miss）求和兜底。
    """
    if not isinstance(last_usage, dict):
        return 0
    for key in ("prompt_tokens", "input_tokens"):
        value = last_usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    for key in ("prompt_tokens_details", "input_tokens_details"):
        detail = last_usage.get(key)
        if isinstance(detail, dict):
            total = sum(
                v for v in detail.values() if isinstance(v, (int, float)) and v > 0
            )
            if total > 0:
                return int(total)
    return 0


def render(
    projected: list[dict[str, Any]],
    last_usage: dict[str, Any] | None = None,
    folds: dict[str, Any] | None = None,
    window_tokens: int = 0,
) -> str:
    """一行事实：``本会话上下文: vendor 366k tok / 1.0M (35%) | 早期内容已收纳 3 段 | soft …``。

    ``folds`` = ``memory.wsc_folds.snapshot()``：收纳段数只增不减（一轮内单调），
    所以不会出现"同一轮两个版本"的自我推翻（对照 vendor/est 的教训）。措辞用日常
    说法，不用内部词"折叠"——模型不认识我们自造的名词。

    ``window_tokens`` = **用户登记的**分母；未登记（0）⇒ 只报分子、不报占比——没有
    权威分母时宁可缺一个数，也不编一个（"感觉快到顶了"这种判断就是这么长出来的）。

    优先厂商真值（上次请求的 input tokens）；拿不到才退回本次 payload 的估算
    （标注 ``est``，是下界）。两个数都取不到 → 空串（该块本轮缺席）。
    """
    try:
        exact = vendor_input_tokens(last_usage)
        if exact <= 0:
            if not _allow_est():
                return ""
            est = estimate_tokens(projected)
            if est <= 0:
                return ""
            label = f"payload 估算 {_human(est)}"
        else:
            label = f"上次请求输入 {_human(exact)}"
        window = int(window_tokens or 0)
        share = ""
        if window > 0:
            numerator = exact if exact > 0 else est
            if numerator > 0:
                share = f" / {_human(window)} ({round(numerator * 100 / window)}%)"
        parts = [f"本会话上下文: {label} tok{share}"]
        folded = int((folds or {}).get("folds") or 0)
        if folded > 0:
            subject = str((folds or {}).get("last_subject") or "").strip()
            # 日常说法（不用"折叠"这类内部词）：早期内容不再逐字可见，但没丢。
            tail = f"（最近: {subject}）" if subject else ""
            parts.append(f"早期内容已收纳 {folded} 段{tail}")
        return " | ".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def _human(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens // 1_000}k"
    return str(tokens)


__all__ = [
    "estimate_tokens",
    "render",
]
