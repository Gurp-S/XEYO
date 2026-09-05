"""R 估算：把「剩余轮数」从**预测值**降级为**约束条件**（P1 缺失3）。

背景：旧实现把 R 当一个标量预测值（``estimate_remaining``），R 估错就整个决策偏向
某档 horizon——估大了提前压缩、估小了尾部无限长。且 R 一旦当作唯一选择器，
J/vote 对 R 的敏感性会被放大。

本模块输出一个**决策分级**而不是单值：``{4: bool, 8: bool, 16: bool}``，表示各档
horizon 在当前窗口压力 / 待读工作量下**是否可行**。它只当约束喂给 ``decide``，
q 值 J 与投票逻辑不动（「不得把 R 当作唯一选择器」）。

规则（对齐交接提示词）：
- 窗口使用率 >70% 必允许 16（保窗口优先，窗口快满时宁可用更长的前瞻来压缩）。
- ``count_unread_files ≥ 3``：待读文件够多 → 8/16 可行（还有不少活，远 horizon 有意义）。
- ``result[4]=True`` 永远给短收尾留活路（R=4 永远可作为收尾末段优化）。
- 若全 False → ``force_hardtop=True``（先保窗口，交给 HardTop 强制压缩）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: 窗口使用率硬阈值：> 该值必允许 16 档（window 快满，长前瞻更划算）。
WINDOW_HARD_RATIO = 0.70
#: 待读文件阈值：≥ 该值判定为「还有不少活」，8/16 档可行。
UNREAD_THRESHOLD = 3
#: 决策分级的 horizon 集合（与 params.horizons 对齐）。
HORIZONS: tuple[int, ...] = (4, 8, 16)
#: 环境变量覆盖阈值（便于线上微调，不改公式）。
_WINDOW_RATIO_ENV = "XEYO_R_GATE_WINDOW_RATIO"
_UNREAD_ENV = "XEYO_R_GATE_UNREAD_THRESHOLD"


@dataclass(frozen=True)
class RGate:
    """剩余轮数的决策分级（约束条件）。

    ``allow``：{4,8,16} → 是否可行。``force_hardtop``：是否必须走 HardTop
    （仅当所有档都不可行时，先保窗口——按规则 allow[4] 恒真，因此通常为 False，
    属防御性兜底）。
    """

    allow: dict[int, bool]

    @property
    def allowed_horizons(self) -> tuple[int, ...]:
        return tuple(sorted(h for h, ok in self.allow.items() if ok))

    @property
    def force_hardtop(self) -> bool:
        return not any(self.allow.values())


def _threshold_window_ratio() -> float:
    raw = os.environ.get(_WINDOW_RATIO_ENV, "").strip()
    if raw:
        try:
            v = float(raw)
            if 0.5 <= v <= 0.99:
                return v
        except ValueError:
            pass
    return WINDOW_HARD_RATIO


def _threshold_unread() -> int:
    raw = os.environ.get(_UNREAD_ENV, "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return UNREAD_THRESHOLD


def _dynamic_enabled() -> bool:
    """B3 证据门（优化3）：动态 R_base 参与档位分级。默认关=静态规则。

    走 memory_switches.get_value（settings.memory 唯一权威，env 不参与）。
    """
    from memory.memory_switches import get_value

    return get_value("XEYO_V61_DYNAMIC_R") == "1"


def dynamic_r_base(
    *,
    current_tokens: float,
    window_tokens: float,
    avg_turn_tokens: float,
    cap: float = 24.0,
) -> float:
    """B3：R_base = min((L_limit − L_current)/ΔL_avg, 24)——按窗口余量与
    近期增速估「还能装下几轮」，比静态待读数更贴近真实剩余工作量。"""
    avg = max(1.0, float(avg_turn_tokens or 0.0))
    headroom = max(0.0, float(window_tokens or 0.0) - float(current_tokens or 0.0))
    return min(float(cap), headroom / avg)


def estimate_r_gate(
    usage_ratio: float,
    unread_count: int,
    *,
    params=None,
    avg_turn_tokens: float | None = None,
    window_tokens: int | None = None,
    current_tokens: int | None = None,
) -> RGate:
    """按窗口使用率 + 待读文件数给出 {4,8,16} 决策分级。

    ``usage_ratio``：当前投影 token 长度 / 窗口 token 预算（0..1）。
    ``unread_count``：待读文件数。
    ``params``：可为 None（用默认阈值），保留给未来接 Params 覆盖。

    B3（XEYO_V61_DYNAMIC_R=1 且给了增速/窗口输入）：在静态规则之上**加性**放宽——
    R_base ≥ 6 → 8 档可行；R_base ≥ 14 → 16 档参与。中长任务（静态规则两不沾、
    单档投票退化为 keep）由此获得有效投票档位；不收紧静态结论（P1 验收不变）。
    """
    _ = params
    usage = max(0.0, min(1.0, float(usage_ratio or 0.0)))
    unread = max(0, int(unread_count or 0))
    hard_ratio = _threshold_window_ratio()
    unread_thr = _threshold_unread()
    allow16 = usage > hard_ratio or unread >= unread_thr
    allow8 = unread >= unread_thr
    allow4 = True  # 永远给短收尾留活路
    if _dynamic_enabled() and avg_turn_tokens and window_tokens and current_tokens is not None:
        try:
            r_base = dynamic_r_base(
                current_tokens=current_tokens,
                window_tokens=window_tokens,
                avg_turn_tokens=avg_turn_tokens,
            )
        except (TypeError, ValueError):
            r_base = 0.0
        if r_base >= 6.0:
            allow8 = True
        if r_base >= 14.0:
            allow16 = True
    return RGate(allow={4: allow4, 8: allow8, 16: allow16})


def count_unread_files(read_state: dict) -> int:
    """粗略统计「待读文件」数：取 read_file_state 里的路径条目数（启发式信号）。

    每个被 Read 跟踪的路径都算一个潜在待读（模型可能还要接着读/确认）。
    纯确定性、无 I/O；供 ``estimate_r_gate`` 的 ``unread_count`` 输入。
    """
    if not isinstance(read_state, dict):
        return 0
    return max(0, len(read_state))


def usage_ratio_from_tokens(current_tokens: int, window_tokens: int) -> float:
    """当前投影 token 长度相对窗口预算的比例（0..1）。"""
    win = max(1, int(window_tokens or 0))
    return max(0.0, min(1.0, float(current_tokens or 0) / float(win)))
