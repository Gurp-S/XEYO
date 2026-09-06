"""禀赋③：失败 → 惯例记忆的最小写入器（复用 memdir 布局与 memindex 检索）。

用法（adapter 结算点调用）:
    from memory.failure_note import note_failure_convention
    note_failure_convention(cwd=task_cwd, task="build-pmars",
                            failure_class="agent_timeout", detail="...")

写入规则：向该 cwd 对应 workspace 的 MEMORY.md 追加一条带 frontmatter 的
convention 段（memindex 既有检索自动可见）。治理审批的接入是后续项——当前
仅记录"事件级教训"，不写任何指令性内容。
"""

from __future__ import annotations

import time
from typing import Any

from memory.memdir import ensure_layout, workspace_id

_FAILURE_TO_CONVENTION = {
    "agent_timeout": "长任务先估算耗时：>60s 的命令立即后台化；预算 80% 时优先落盘交付物。",
    "verifier_timeout": "判分/验证依赖（模型下载、外部源）应在开工时预取，不要留在验收阶段。",
    "wrong_deliverable": "写码前先声明交付物精确路径与格式；完成后对照原始要求逐项核对。",
    "isolation_fail": "交付物必须能在只含声明输入的干净目录里运行；先 run_isolated 再交卷。",
    "metric_below_threshold": "任务给了量化指标（准确率/阈值）时，不达标不许停止——先迭代到达标或明确报告差距。",
}


def failure_class_of(exception_type: str | None, reward: float | None) -> str | None:
    """从异常/判分推断失败惯例类别；无对应惯例返回 None。"""
    if reward == 1.0:
        return None
    et = (exception_type or "").lower()
    if "timeout" in et:
        return "agent_timeout"
    if "verifier" in et:
        return "verifier_timeout"
    return None


def note_failure_convention(
    *,
    cwd: str,
    task: str,
    failure_class: str | None,
    detail: str = "",
    now: float | None = None,
) -> str | None:
    """向 workspace MEMORY.md 追加一条失败惯例；返回写入的段落或 None。"""
    convention = _FAILURE_TO_CONVENTION.get(failure_class or "")
    if not convention:
        return None
    ts = time.strftime("%Y-%m-%d", time.localtime(now if now is not None else time.time()))
    try:
        wsid = workspace_id(cwd)
        memdir = ensure_layout(wsid, canonical_path=cwd)
        entry = (
            f"\n## Convention: {convention}\n"
            f"- 来源: 任务 {task}（{failure_class}，{ts}）\n"
            f"- 惯例: {convention}\n"
            + (f"- 细节: {detail[:200]}\n" if detail else "")
        )
        with open(memdir / "MEMORY.md", "a", encoding="utf-8") as f:
            f.write(entry)
        return convention
    except Exception:  # noqa: BLE001 — 记忆写入绝不阻塞主流程
        return None
