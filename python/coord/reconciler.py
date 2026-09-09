"""Reconciler：单点串行收敛（阶段 1 L0，计划 §2/§3）。

唯一允许写主分支的角色。收敛语义 = **三路合并**（merge-base），不是裸
``git diff | git apply``——A 删文件 X / B 改文件 X 时，按序 apply 会
pathspec 失配，三路合并才能给出明确冲突判定。

流程（每个 ready_to_merge 任务）：
1. worktree 内 ``git rebase main``（非重叠改动自动合并）；
2. 成功 → 主仓 ``git update-ref refs/heads/main <new_head>``（fast-forward，
   不碰主仓 index / 工作树）→ ``merged`` → worktree 即弃；
3. 真冲突（含 modify/delete）→ ``rebase --abort`` → ``reopen_conflict``：
   最新 main head 写回 base_commit + 结构化 findings（冲突文件清单），
   reopen 硬顶 REOPEN_LIMIT 熔断转 blocked；
4. ``git cat-file -t`` 自检新 head 在对象库，再推进 ref。

互斥：FileGuard 串行锁（``reconciler.lock``）——同一 repo 同时只有一个
reconciler 在收敛；锁忙则跳过本轮（守方稍后重试）。
所有 git 调用带 GIT_OPTIONAL_LOCKS=0。错误措辞一律中性事实。
"""

from __future__ import annotations

import logging
from pathlib import Path

from coord.file_store import CoordFileStore
from coord.locking import FileGuard
from coord.store import (
    STATUS_BLOCKED,
    STATUS_READY_TO_MERGE,
    STATUS_REOPENED,
    Task,
)
from coord.worktree import WorktreeError, WorktreeManager, git

_log = logging.getLogger("xeyo.coord.reconcile")
RECONCILER_LOCK = "reconciler"


class Reconciler:
    """串行收敛器：把 worker 上交的 worktree 分支三路合并进 main。"""

    def __init__(self, repo: str | Path, store: CoordFileStore, *,
                 lock_timeout: float = 10.0, push_remote: str = "") -> None:
        self.repo = Path(repo).resolve()
        self.store = store
        self.wt = WorktreeManager(self.repo)
        self.lock_timeout = float(lock_timeout)
        self.push_remote = str(push_remote or "")

    # -- helpers ------------------------------------------------------------

    def _main_head(self) -> str:
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def _lock_path(self) -> Path:
        return self.repo / ".xeyo" / "coord" / "locks" / f"{RECONCILER_LOCK}.lock"

    def _release(self, owner: str, scope: list[str]) -> None:
        """任务离开 hands → 释放其 scope 租约（同 owner 其他任务路径不动）。"""
        if owner and scope:
            try:
                self.store.release_task_scope(self.repo, owner, scope)
            except Exception:  # noqa: BLE001
                _log.debug("reconcile release lease failed", exc_info=True)

    def _classify(self, task_id: str, nxt, report: dict, *,
                  owner: str = "", scope: list[str] | None = None) -> None:
        if nxt is None:
            report["rejected"].append({"task_id": task_id, "reason": "cas_rejected"})
        elif nxt.status == STATUS_REOPENED:
            report["reopened"].append({"task_id": task_id, "base_commit": nxt.base_commit[:12]})
        elif nxt.status == STATUS_BLOCKED:
            report["blocked"].append({"task_id": task_id, "reopen_count": nxt.reopen_count})
        # 任务离开 hands（reopened/blocked）→ 释放租约。
        self._release(owner, scope or [])

    # -- 主入口 -------------------------------------------------------------

    def reconcile_ready(self) -> dict:
        """收敛全部 ready_to_merge 任务（串行、单点）。返回中性报告。"""
        report: dict = {"merged": [], "reopened": [], "blocked": [], "rejected": [], "skipped": ""}
        with FileGuard(self._lock_path(), timeout=self.lock_timeout) as ok:
            if not ok:
                report["skipped"] = "reconciler_lock_busy"
                return report
            tasks = self.store.list_tasks(STATUS_READY_TO_MERGE)
            tasks.sort(key=lambda t: t.updated_at)  # 按上交先后收敛
            for t in tasks:
                self._reconcile_one(t, report)
        return report

    def _reconcile_one(self, task: Task, report: dict) -> None:
        task_id = task.task_id
        owner, scope = task.claimed_by, list(task.scope)
        main_head = self._main_head()
        try:
            handle = self.wt.load(task_id)
        except WorktreeError as exc:
            nxt = self.store.reopen_conflict(
                task_id, main_head,
                [{"file": "", "line": 0, "error": f"worktree_missing: {exc}"}])
            self._classify(task_id, nxt, report, owner=owner, scope=scope)
            return

        try:
            r = git(handle.path, "rebase", "main", check=False)
        except WorktreeError as exc:  # 超时/spawn 失败按冲突退回
            nxt = self.store.reopen_conflict(
                task_id, main_head,
                [{"file": "", "line": 0, "error": f"rebase_error: {exc}"}])
            self._classify(task_id, nxt, report, owner=owner, scope=scope)
            self.wt.remove(task_id)
            return

        if r.returncode != 0:
            files = self.wt.conflict_files(handle)
            git(handle.path, "rebase", "--abort", check=False)
            findings = [{"file": f, "line": 0, "error": "rebase_conflict"} for f in files]
            if not findings:
                findings = [{"file": "", "line": 0,
                             "error": f"rebase_failed: {r.stderr.strip()[:200]}"}]
            nxt = self.store.reopen_conflict(task_id, main_head, findings)
            self._classify(task_id, nxt, report, owner=owner, scope=scope)
            self.wt.remove(task_id)  # 完成即弃（重做时重建）
            return

        new_head = self.wt.head(handle)
        chk = git(self.repo, "cat-file", "-t", new_head, check=False)
        if chk.returncode != 0:
            # 对象不在主库（异常形态）：不推进 ref，按冲突退回
            nxt = self.store.reopen_conflict(
                task_id, main_head,
                [{"file": "", "line": 0, "error": "object_missing_after_rebase"}])
            self._classify(task_id, nxt, report, owner=owner, scope=scope)
            self.wt.remove(task_id)
            return

        git(self.repo, "update-ref", "refs/heads/main", new_head)  # ff：不碰 index/工作树
        self.store.mark_merged(task_id)
        report["merged"].append({"task_id": task_id, "head": new_head[:12]})
        if self.push_remote:
            git(self.repo, "push", self.push_remote, "main", check=False)
        self.wt.remove(task_id)
        self._release(owner, scope)  # merged：任务离开 hands → 释放租约


__all__ = ["Reconciler"]
