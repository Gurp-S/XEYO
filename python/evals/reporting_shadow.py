"""reporting_shadow — 【侧挂模块·默认关】报告口径：禁止只报单一 accuracy。

依据：计划 `docs/实施计划/46-cursor博客技术融合优化计划.md` §A3（⑤）。
对应方案稿：`docs/设计/cursor博客的技术融合到XEYO.md` §⑤（报告口径：明确「测的是什么」）。

## 为什么（收益=评测诚实度）
- `evals/*`（humaneval_lite / mbpp_lite / bfcl_lite）summary/print 现只输出 `accuracy` 单一
  headline。这混淆「编码能力」与「编码+检索能力」，也是 reward-hacking 一类「只报一个数」的表现。
- 本模块提供一个**报告口径辅助**：把 summary 规范化成恒含
  `standard / strict / Δ / leakage_rate` 四字段，并标注「编码能力」还是「编码+检索能力」；
  拒绝只写单一 `accuracy`。

## 侧挂契约（不改主逻辑）
- `enabled()`：读 `XEYO_EVAL_REPORTING`（默认 0=关）。开=评测写入 summary 时经
  `build_report(summary, ...)` 规范化；关=原样。
- `build_report(summary, *, mode_label=None) -> dict`：纯函数，返回至少含 4 字段的字典；
  若传入的 summary 只有 `accuracy`（无 strict 等），会自动补 `strict=None / Δ=None /
  leakage_rate=None` 并标注「编码+检索能力」（保守：无法证明是纯编码时归为混合）。
- **fail-open**：任何异常/缺失 → 返回一个带 `standard` 兜底、其余字段 `None` 的字典，绝不丢分数。

## 红线
- SWE 系与 XEYO 自我评测结果**禁止只报单一 accuracy**（本模块即落实此约定）。
"""

from __future__ import annotations

import os

_ENV = "XEYO_EVAL_REPORTING"

#: 报告约定：必须含的字段。
_REQUIRED = ("standard", "strict", "delta", "leakage_rate")


def enabled() -> bool:
    """是否启用报告口径（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def build_report(summary: dict, *, mode_label: str | None = None) -> dict:
    """规范化评测 summary → 恒含 `standard / strict / Δ / leakage_rate` 四字段。

    - `standard`：优先用 summary 的 `accuracy`；缺失则用 `standard` 字段。
    - `strict`：summary 的 `strict`；缺失 → None。
    - `delta`：standard - strict（严格较低即 Δ≥0，代表语义「标准 vs 严格」差距）；
      任一为 None → None。
    - `leakage_rate`：summary 的 `leakage_rate`；缺失 → None。
    - 注明「测什么」：summary 的 `capability` 或传入 `mode_label`；默认「编码+检索能力」（保守，
      无法证明纯编码时归为混合）。
    """
    report = dict(summary or {})
    standard = report.get("standard")
    if standard is None:
        standard = report.get("accuracy")
    strict = report.get("strict")
    delta: float | None = None
    if standard is not None and strict is not None:
        try:
            delta = round(float(standard) - float(strict), 4)
        except (TypeError, ValueError):
            delta = None
    leakage = report.get("leakage_rate")

    report["standard"] = standard
    report["strict"] = strict
    report["delta"] = delta
    report["leakage_rate"] = leakage
    report.setdefault("capability", mode_label or "编码+检索能力")  # 保守归混合
    return report


def assert_no_single_accuracy(report: dict) -> bool:
    """校验报告是否满足「至少含 4 字段」的约定；仅单 accuracy 返回 False。"""
    if not isinstance(report, dict):
        return False
    has_standard = report.get("standard") is not None or report.get("accuracy") is not None
    has_strict = report.get("strict") is not None and report.get("delta") is not None
    # 「只报单一 accuracy」= standard 有、但 strict/Δ/leakage 全无。
    if has_standard and not has_strict and report.get("leakage_rate") is None:
        return False
    return True
