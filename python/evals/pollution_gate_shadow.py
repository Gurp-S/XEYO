"""pollution_gate_shadow — 【侧挂模块·默认关】评测环境污染门。

先例：v61 落地收益与证据门报告的「源健康门」（病态源直接报错拒绝）——本门
扩展为「环境污染门」，在跑 SWE / 长任务（含 `python/scripts/memory_stack_eval.py`）前校验环境。

## 为什么（收益=评测诚实度）
- 任务镜像若在缺陷修复**后**构建、或环境中显式藏了镜像页/隐藏测试/标准补丁/`check(...)` 断言串，
  模型会从环境泄密推断「issue 已解决」→ 转去查修复而非推导（reward-hacking 的「环境泄漏」）。
- 本门在入口拒绝这些污染环境，把泄漏面挡在评测外。

## 侧挂契约（不改主逻辑）
- `enabled()`：读 `XEYO_EVAL_POLLUTION_GATE`（默认 0=关；评测置 1 才启用）。开=评测入口先跑
  `check_environment(...)`，违例即拒；关=不拦（逐位不变）。
- 纯函数校验（可独立调用/单测）：`check_environment(env) -> GateVerdict`。
- **fail-open**：校验本身异常 → 返回「无法证实（fail-open）」并按评测配置决定拦或不拦
  （默认拦——污染门宁可误拦不假放；但绝不影响非评测主流程）。

## 校验维度（每项可独立标记）
- `pre_fix_mirror`：任务镜像应是**修复前**快照（非修复后）。
- `mirror_page_exposed`：环境不含镜像页（golden patch/hidden 解答说明页）。
- `hidden_test_exposed`：无隐藏测试与标准补丁的明文暴露。
- `check_assertion_exposed`：无 `check(...)` 断言串暴露通道（被测代码里能 grep 到判题断言）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

_ENV = "XEYO_EVAL_POLLUTION_GATE"
#: 常见污染迹象关键词（示例集，可按需扩充）。
_MIRROR_PAGE_TOKENS = ("golden patch", "reference solution", "solution.md", "hidden_test")
_CHECK_TOKENS = ("check(", "assert ", "test_acceptance", "verify_output")


@dataclass
class GateVerdict:
    """污染门判定：pass=可跑；block=拒绝进入评测（带 reason）。"""

    ok: bool
    reasons: list[str] = field(default_factory=list)
    skip: bool = False  # True = 门被关闭/非评测，未判定


def enabled() -> bool:
    """是否启用环境污染门（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def check_environment(
    env: dict,
    *,
    path_text: str = "",
    fail_open_block: bool = True,
) -> GateVerdict:
    """校验评测环境是否污染。

    参数：
    - env：评测环境元数据字典，键见 `_validate_*`。
    - path_text：被测目录/文件中可 grep 的文本（用于检测 check 断言/镜像页泄露）。
    - fail_open_block：校验异常时是否按「拒不通过」处理（真评测建议 True，宁可误拦不假放）。
    """
    if not enabled():
        return GateVerdict(ok=True, skip=True)

    reasons: list[str] = []
    # ① 镜像须是修复前快照。
    if not _validate_pre_fix(env.get("snapshot_is_pre_fix")):
        reasons.append("任务镜像不是「修复前」快照（snapshot_is_pre_fix=False/缺失）")
    # ② 无镜像页暴露。
    if _exposed(path_text, _MIRROR_PAGE_TOKENS):
        reasons.append("环境文本含镜像页/golden patch/参考解答痕迹")
    if env.get("mirror_page_exposed"):
        reasons.append("环境显式标记存在镜像页（mirror_page_exposed=True）")
    # ③ 无隐藏测试/标准补丁暴露。
    if env.get("hidden_test_exposed"):
        reasons.append("环境显式标记存在隐藏测试/标准补丁暴露（hidden_test_exposed=True）")
    # ④ 无 check(...) 断言串暴露通道。
    if _exposed(path_text, _CHECK_TOKENS):
        reasons.append("被测文本含 `check(...)`/断言串暴露通道")

    if not reasons:
        return GateVerdict(ok=True)
    return GateVerdict(ok=False, reasons=reasons)


def _validate_pre_fix(val) -> bool:
    """snapshot_is_pre_fix 应为 True（修复前）。缺失/False/非真值 → 判不通过。"""
    return val is True


def _exposed(text: str, tokens: tuple[str, ...]) -> bool:
    """文本是否含任一污染 token（大小写不敏感）。空文本视为未暴露。"""
    if not text:
        return False
    lowered = text.lower()
    return any(tok.lower() in lowered for tok in tokens)
