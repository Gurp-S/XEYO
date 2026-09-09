"""Reviewer：提交门评审 + findings 机器执法（阶段 2，计划 §3）。

Cursor 教训：删除"集成者"、评审是**独立角色**，输出必须是**结构化机器检查
清单**而非评价式文本（引擎铁律：注意力只放信息，不放导演）。本模块只做 coord
层的两件执法：

1. ``reject``——评审不通过打回：
   - findings 必须结构化（每项含 ``file`` + ``error``；``line`` 可选）——
     非结构 → 拒绝提交（``invalid_findings``），杜绝"感觉没做好"式打回；
   - 转 ``reopen_task``（claimed→reopened，含 REOPEN_LIMIT 熔断转 blocked）。
2. ``plan_replacement``——被打回后的重规划产物入库：
   - **scope 强制子集**：新 task 的 scope ⊆ 原 scope ∪ findings.files
     （``enforce_replan_scope``）——超界直接拒收（``scope_expansion_denied``），
     这是"禁止 Reviewer/Planner 擅自扩大 scope 重构"的执行层落地；
   - 通过则建父子链（``parent_id`` 指向原任务），进 pending 待认领。

熔断与租约不在本模块重复实现（reopen_task 已含计数、claim 闸门已含租约）。
错误措辞一律中性事实（引擎铁律：不写"不要扩大范围"式劝导）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from coord.file_store import CoordFileStore
from coord.store import (
    STATUS_BLOCKED,
    Task,
    enforce_replan_scope,
    findings_files,
    new_task,
    norm_scope_path,
)

_log = logging.getLogger("xeyo.coord.reviewer")


def _valid_findings(findings: list[dict]) -> bool:
    """结构化校验：每项必须是 dict，含非空 ``file`` 或 ``error``，且无自由文本夹带。"""
    if not findings:
        return False
    for f in findings:
        if not isinstance(f, dict):
            return False
        has_file = isinstance(f.get("file"), str)
        has_err = isinstance(f.get("error"), str) and bool(str(f.get("error")).strip())
        if not (has_err or has_file):
            return False
        if "line" in f and not isinstance(f["line"], (int, float)):
            return False
    return True


class Reviewer:
    """单 repo 的评审执法器。无状态；产物写回 CoordStore。"""

    def __init__(self, repo: str | Path, store: CoordFileStore) -> None:
        self.repo = Path(repo).resolve()
        self.store = store

    # -- 打回 ---------------------------------------------------------------

    def _release(self, owner: str, scope: list[str]) -> None:
        """任务离开 hands → 释放其 scope 租约（无租约时 no-op）。"""
        if owner and scope:
            try:
                self.store.release_task_scope(self.repo, owner, scope)
            except Exception:  # noqa: BLE001
                _log.debug("reviewer release lease failed", exc_info=True)

    def reject(self, *, task_id: str, worker_id: str,
               findings: list[dict]) -> dict[str, Any]:
        """评审不通过：结构化校验 → reopen（含熔断）→ 释放租约。返回中性报告。"""
        task = self.store.load_task(task_id)
        if task is None:
            return {"ok": False, "reason": "task_not_found"}
        if not _valid_findings(findings):
            return {"ok": False, "reason": "invalid_findings"}
        nxt = self.store.task_transition(task_id, worker_id, "reopen",
                                         findings=findings)
        if nxt is None:
            return {"ok": False, "reason": "transition_rejected"}
        self._release(task.claimed_by or worker_id, task.scope)
        return {"ok": True, "status": nxt.status, "reopen_count": nxt.reopen_count,
                "blocked": nxt.status == STATUS_BLOCKED}

    # -- 重规划执法 ---------------------------------------------------------

    def plan_replacement(self, *, parent_task_id: str, proposed_scope: list[str],
                         title: str = "", goal_id: str = "") -> dict[str, Any]:
        """被打回后的重规划任务入库；scope 必须 ⊆ 原 scope ∪ findings.files。

        超界 → ``scope_expansion_denied``（执行层强制，不进劝导文本）。"""
        parent = self.store.load_task(parent_task_id)
        if parent is None:
            return {"ok": False, "reason": "parent_not_found"}
        clean_scope = [norm_scope_path(p) for p in (proposed_scope or []) if norm_scope_path(p)]
        if not clean_scope:
            return {"ok": False, "reason": "missing_scope"}
        if not enforce_replan_scope(parent, clean_scope):
            allowed = sorted({norm_scope_path(p) for p in parent.scope}
                             | {norm_scope_path(p) for p in _finding_paths(parent)})
            return {"ok": False, "reason": "scope_expansion_denied",
                    "proposed": clean_scope, "allowed": allowed}
        child = new_task(
            goal_id=goal_id or parent.goal_id,
            title=title or f"replan:{parent.title}",
            scope=clean_scope,
            model=parent.model,
            max_turns=parent.max_turns,
            required_tools=list(parent.required_tools),
            parent_id=parent.task_id,
        )
        self.store.create_task(child)
        # 子任务接管 → 父任务转 superseded（终态，不再与子任务竞争认领）。
        self.store.task_transition(parent.task_id, parent.claimed_by, "supersede")
        return {"ok": True, "task_id": child.task_id, "parent_id": parent.task_id}


def _finding_paths(task: Task) -> list[str]:
    return findings_files(task.findings)


__all__ = ["Reviewer"]
