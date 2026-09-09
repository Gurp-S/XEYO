"""Worker 池（阶段 1 L1，计划 §2/§3）：claim → worktree → 执行 → 上交。

``run_task`` 流程：
1. 认领：若任务已被本 worker ``claimed``（阶段 2 planner.claim_next 认领并持
   租约）→ 续跑，沿用认领时 base_commit；否则读 main head 作 base 自认领
   （pending / reopened，双进程下恰好一个成功）；
2. ``worktree add -b coord/task/<短名> <base>``——worker 会话 cwd 指向
   worktree（独立 index，不碰主仓 index.lock）；
3. 执行 ``work_fn(worktree_path)``（阶段 1 为注入回调；阶段 2 接
   agent_tool/subagent_runner 派生真会话）；
4. ``commit_all``（无改动 = 空 diff 也合法，committed=False）；
5. ``submit_result``（claimed → ready_to_merge，附分支名，交 reconciler）。

异常路径：work_fn 抛错 → ``worker_failed``（reopen 熔断同轨，任务可被
重试）+ worktree 清理。scope 租约互斥属 L2 协调层（``acquire_scope`` /
planner.claim_next），本模块不重复做认领闸门。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from coord.file_store import CoordFileStore
from coord.store import STATUS_CLAIMED
from coord.worktree import WorktreeError, WorktreeManager, git


@dataclass
class WorkerOutcome:
    task_id: str
    ok: bool
    committed: bool = False
    branch: str = ""
    error: str = ""


class WorkerPool:
    """单 repo 的 worker 执行入口；实例无共享可变状态，可跨线程/进程各自持有。"""

    def __init__(self, repo: str | Path, store: CoordFileStore) -> None:
        self.repo = Path(repo).resolve()
        self.store = store
        self.wt = WorktreeManager(self.repo)

    def _head(self) -> str:
        try:
            return git(self.repo, "rev-parse", "main").stdout.strip()
        except WorktreeError:
            return ""

    def run_task(self, task_id: str, worker_id: str,
                 work_fn: Callable[[Path], None], *, message: str = "") -> WorkerOutcome:
        cur = self.store.load_task(task_id)
        # 已认领（planner.claim_next 认领并持租约）→ 续跑，沿用认领时 base；
        # 否则自认领（读 main head 作 base）。
        if cur is not None and cur.status == STATUS_CLAIMED and cur.claimed_by == worker_id:
            base = cur.base_commit or self._head()
        else:
            try:
                base = git(self.repo, "rev-parse", "main").stdout.strip()
            except WorktreeError as exc:
                return WorkerOutcome(task_id=task_id, ok=False, error=f"main_head: {exc}")
            if self.store.claim_task(task_id, worker_id, base) is None:
                return WorkerOutcome(task_id=task_id, ok=False,
                                     error="claim_failed: not claimable or lock busy")

        handle = self.wt.create(task_id, base)
        try:
            work_fn(handle.path)
            head = self.wt.commit_all(handle, message or f"coord: task {task_id}")
        except Exception as exc:  # noqa: BLE001 — worker 任意异常统一退回
            err = f"worker_error: {exc}"
            self.store.worker_failed(task_id, worker_id,
                                     [{"file": "", "line": 0, "error": err}])
            self.wt.remove(task_id)
            return WorkerOutcome(task_id=task_id, ok=False, error=err)

        nxt = self.store.submit_result(task_id, worker_id, handle.branch)
        if nxt is None:
            self.wt.remove(task_id)
            return WorkerOutcome(task_id=task_id, ok=False,
                                 error="submit_failed: not claimed by self")
        return WorkerOutcome(task_id=task_id, ok=True,
                             committed=head is not None, branch=handle.branch)


__all__ = ["WorkerOutcome", "WorkerPool"]
