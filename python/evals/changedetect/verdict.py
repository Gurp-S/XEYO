"""verdict —— 把 L0/L1/L2/应试性合到一张判决书上。

判决书的结构：
  deterministic   L0 + L1 的纯差异事实 + 影响面提示
  statistical     L2 的统计裁决 + MDE + 分辨力自报
  compliance      应试性自动扫描的命中
  overall         fail / pass / inconclusive 的合并结论

合并规则（保守优先）：
  - compliance fail → 整体 fail（任一 R2/R4 fail 直接挡住）
  - L0/L1 改了 + 没有 L2 实跑 → inconclusive（必须解释每一处变化）
  - L2 实跑有结论 → 与 compliance 联合：
      positive + 无 fail → pass
      negative → fail
      inconclusive → inconclusive
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from . import canon, compliance

# 改一类文本对全量的影响面（粗估，够用）
_IMPACT: dict[str, str] = {
    "system": "影响每一轮请求的左段：缓存前缀、身份定位、围栏边界",
    "tools": "影响模型对工具的选择/参数生成：直接改变行为能力面",
    "tnow": "影响 T_now 块注入：仅在被触发的轮次生效；改登记表/硬顶 = 准入线",
    "slash": "影响斜杠命令清单：GUI/TUI 的可发现性，与已绑定事件不自动同步",
    "meta": "侦测器自身口径变了：旧的 MDE/裁决边界可能不再适用",
    "trace": "确定性重放的决策轨迹变了：引擎分支条件变化（无对应文本改动）",
}

_VERDICT_RANK = {"pass": 0, "inconclusive": 1, "fail": 2}
_RANK_VERDICT = {v: k for k, v in _VERDICT_RANK.items()}


@dataclass
class Verdict:
    overall: str = "inconclusive"
    deterministic: dict[str, Any] = field(default_factory=dict)
    statistical: dict[str, Any] = field(default_factory=dict)
    compliance: dict[str, Any] = field(default_factory=dict)
    summary_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "deterministic": self.deterministic,
            "statistical": self.statistical,
            "compliance": self.compliance,
            "summary_lines": self.summary_lines,
        }


def _group_impact(group: str) -> str:
    return _IMPACT.get(group, "影响范围未分类：人工核")


def build(
    *,
    surface_changes: list[Any],
    trace_changes: list[Any],
    ab_report: dict[str, Any] | None = None,
    diff_text: str = "",
    diff_paths: list[str] | None = None,
    run_compliance: bool = True,
) -> Verdict:
    v = Verdict()
    # deterministic
    by_group: dict[str, list[str]] = {}
    for ch in surface_changes + trace_changes:
        by_group.setdefault(ch.get("group", "-"), []).append(ch["name"])
    v.deterministic = {
        "changed": bool(surface_changes or trace_changes),
        "surface_count": len(surface_changes),
        "trace_count": len(trace_changes),
        "by_group": by_group,
        "impact_hints": {g: _group_impact(g) for g in by_group},
    }

    # statistical
    v.statistical = {"present": bool(ab_report)}
    if ab_report:
        ps = (ab_report.get("statistical") or {}).get("pass_pair") or {}
        v.statistical = {
            "present": True,
            "verdict": ps.get("verdict", "?"),
            "n_pairs": ps.get("n_pairs", 0),
            "delta": ps.get("delta", 0.0),
            "p_value": ps.get("p_value", 1.0),
            "mde": ps.get("mde", 0.0),
            "discordant_rate": ps.get("discordant_rate", 0.0),
            "live": ab_report.get("live", False),
            "estimated_total_cny": ab_report.get("estimated_total_cny", 0.0),
            "note": ps.get("resolution_note", ""),
        }

    # compliance
    if run_compliance:
        if diff_text:
            hits = compliance.scan_added_lines(diff_text)
            v.compliance = compliance.summarize(hits)
        elif diff_paths is not None:
            v.compliance = compliance.scan_git_diff(diff_paths)
        else:
            v.compliance = compliance.summarize(
                compliance.scan_added_lines("")
            )
    else:
        v.compliance = {"hit_count": 0, "hits": []}

    # 总结行
    if v.deterministic["changed"]:
        groups = ", ".join(sorted(by_group))
        v.summary_lines.append(
            f"确定性层：检测到 {len(surface_changes) + len(trace_changes)} 处变化"
            f"（{groups}）——每一处必须能在 PR 说明里答出'为什么'。"
        )
    else:
        v.summary_lines.append("确定性层：无变化。L0+L1 一切如旧。")

    if v.statistical.get("present"):
        s = v.statistical
        live_tag = "实跑" if s.get("live") else "干跑"
        v.summary_lines.append(
            f"统计层（{live_tag}）：{s.get('n_pairs', 0)} 对样本，"
            f"Δ {s.get('delta', 0):+.1%}，p={s.get('p_value', 1):.4f}，"
            f"裁决 **{s.get('verdict', '?')}**。"
        )
        v.summary_lines.append(s.get("note", ""))
    else:
        v.summary_lines.append("统计层：未实跑。仅确定性结论可用。")

    if v.compliance.get("hit_count"):
        v.summary_lines.append(
            f"应试性扫描：{v.compliance['hit_count']} 条命中（"
            f"{v.compliance.get('by_severity', {})}）——每条必须在 PR 里解释。"
        )
    else:
        v.summary_lines.append("应试性扫描：无命中。")

    # 合并
    rank = _VERDICT_RANK["inconclusive"]
    if v.compliance.get("has_fail"):
        rank = max(rank, _VERDICT_RANK["fail"])
    if v.statistical.get("verdict") in _VERDICT_RANK:
        rank = max(rank, _VERDICT_RANK[v.statistical["verdict"]])
    if v.deterministic["changed"] and not v.statistical.get("present"):
        # 改了什么却没跑统计 → 不允许被读成"pass"
        rank = max(rank, _VERDICT_RANK["inconclusive"])
    v.overall = _RANK_VERDICT[rank]
    return v


def render_markdown(v: Verdict) -> str:
    lines = ["# 变更收益裁决", "", f"**结论：{v.overall}**", ""]
    for ln in v.summary_lines:
        lines.append(f"- {ln}")
    if v.deterministic.get("changed"):
        lines.append("")
        lines.append("## 确定性层（L0+L1）变化面")
        for grp, names in (v.deterministic.get("by_group") or {}).items():
            hint = v.deterministic.get("impact_hints", {}).get(grp, "")
            lines.append(f"### {grp}（{len(names)} 处） — {hint}")
            for n in names[:10]:
                lines.append(f"- `{n}`")
            if len(names) > 10:
                lines.append(f"- …（其余 {len(names) - 10} 处）")
    if v.compliance.get("hits"):
        lines.append("")
        lines.append("## 应试性扫描结果")
        for h in v.compliance["hits"]:
            lines.append(
                f"- **{h['rule']} {h['severity']}** "
                f"in `{h['where']}` — {h['line'][:120]}"
            )
    return "\n".join(lines) + "\n"
