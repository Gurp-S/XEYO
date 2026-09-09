"""Planner 认领闸门（阶段 2，计划 §3）。

职责边界：Planner **会话**本身由编排层（goal_round_driver，阶段 2 后段）
驱动产出 Task DAG；本模块只做 coord 层的两件机器执法：

1. ``plan_round``——接收任务 spec 列表入表：
   - **scope 声明强制**：无 scope 任务拒收（中性拒绝 ``missing_scope``；
     对应 v1.1"不可认领"——claim_task 同轨执法，双保险）；
   - deps 引用校验（不存在 → 拒收，防悬空 DAG）；
   - 同轮内 scope 交集任务标注（不拒——交集互斥由租约在认领时裁决，
     Planner 的 DAG 允许描述"先后依赖"而非"并行冲突"）。
2. ``claim_next``——worker 拉取认领（租约先行）：
   - 先 ``acquire_scope``（交集被他人持有 → 该任务不可并行认领，试下一个）；
   - 再 ``claim_task`` CAS（被抢 → 释放刚拿的租约，试下一个）；
   - 认领成功 = 任务 claimed + 租约已持有（同一 worker_id 维度）。

阶段 2 验收对应：「scope 交集任务由 CoordStore 拒绝并行认领」；
「ASK 挂起释放租约期间，其他 worker 可正常认领相邻 scope」——相邻=无交集，
``acquire_scope`` 放行；相交=拒绝，由 ``ask_gate.suspend`` 释放后自然解堵。

错误措辞一律中性事实（引擎铁律）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from coord.file_store import CoordFileStore
from coord.store import (
    STATUS_PENDING,
    STATUS_REOPENED,
    Task,
    new_task_id,
    norm_scope_path,
)


class Planner:
    """任务入表 + 认领闸门。租约互斥由 CoordFileStore（L2 总线）裁决。"""

    def __init__(self, repo: str | Path, store: CoordFileStore) -> None:
        self.repo = Path(repo).resolve()
        self.store = store

    # -- 入表 ---------------------------------------------------------------

    def plan_round(self, specs: list[dict], *, goal_id: str = "") -> dict:
        """任务 spec → CoordStore。返回中性报告 {created, rejected}。

        spec 形态::
            {title, scope[], model?, max_turns?, required_tools?, deps?, parent_id?}
        可选 pre-id：含 task_id 则沿用（replan 产物溯源用），否则自动生成。
        """
        created: list[str] = []
        rejected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        t0 = time.time()
        # 第一遍：校验 + 建表（不判跨轮 deps——允许先建后链，第二遍补验）。
        drafts: list[tuple[Task, list[str]]] = []
        for sp in specs or []:
            if not isinstance(sp, dict):
                continue
            title = str(sp.get("title") or "").strip()
            scope = [str(p) for p in (sp.get("scope") or []) if str(p).strip()]
            if not scope:
                rejected.append({"title": title, "reason": "missing_scope"})
                continue
            task = Task(
                task_id=str(sp.get("task_id") or "").strip() or _gen_id(),
                goal_id=str(sp.get("goal_id") or goal_id or "").strip(),
                title=title,
                scope=scope,
                model=str(sp.get("model") or ""),
                max_turns=int(sp.get("max_turns") or 0),
                required_tools=[str(t) for t in (sp.get("required_tools") or [])],
                parent_id=str(sp.get("parent_id") or ""),
                status=STATUS_PENDING,
                revision=1,
                created_at=t0,
                updated_at=t0 + len(drafts) * 0.001,
            )
            if task.task_id in seen_ids:
                rejected.append({"title": title, "reason": "duplicate_task_id"})
                continue
            seen_ids.add(task.task_id)
            drafts.append((task, [str(d) for d in (sp.get("deps") or [])]))

        for task, deps in drafts:
            for d in deps:
                if d not in seen_ids and self.store.load_task(d) is None:
                    rejected.append({"title": task.title,
                                     "reason": f"unknown_dep:{d}"})
                    break
            else:
                self.store.create_task(task)
                created.append(task.task_id)
        return {"created": created, "rejected": rejected}

    # -- 认领闸门 -----------------------------------------------------------

    def claim_next(self, *, root: str, worker_id: str,
                   base_commit: str = "") -> Task | None:
        """按提交序尝试认领一个可并行任务（租约先行，交集拒认领）。

        可认领集 = pending ∪ reopened（打回重做优先，FIFO 交错无碍——
        reconciler 的 updated_at 排序负责收敛序）。"""
        candidates = (self.store.list_tasks(STATUS_REOPENED)
                      + self.store.list_tasks(STATUS_PENDING))
        candidates.sort(key=lambda t: t.updated_at)
        for t in candidates:
            lease = self.store.acquire_scope(root, worker_id, t.scope)
            if lease is None:
                continue  # 相邻可试，相交（含空 scope）拒并行
            claimed = self.store.claim_task(t.task_id, worker_id, base_commit)
            if claimed is None:
                self.store.release_scope(root, lease.lease_id, worker_id)
                continue
            return claimed
        return None

    def claim_specific(self, *, root: str, task_id: str, worker_id: str,
                       base_commit: str) -> Task | None:
        """定向认领（replan 后原 worker 续做自己的任务）：同样租约先行。"""
        lease = self.store.acquire_scope(root, worker_id,
                                         _scope_of(self.store, task_id))
        if lease is None and _scope_of(self.store, task_id):
            return None
        claimed = self.store.claim_task(task_id, worker_id, base_commit)
        if claimed is None and lease is not None:
            self.store.release_scope(root, lease.lease_id, worker_id)
        return claimed


def _gen_id() -> str:
    return new_task_id()


def _scope_of(store: CoordFileStore, task_id: str) -> list[str]:
    t = store.load_task(task_id)
    return [norm_scope_path(p) for p in t.scope] if t else []


__all__ = ["Planner"]
