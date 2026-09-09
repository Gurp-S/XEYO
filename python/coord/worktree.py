"""worker worktree 生命周期（阶段 1 L1 执行层，计划 §3）。

每个 task 一个 git worktree：从认领时 base_commit 建立隔离工作区，
worker 会话 cwd = worktree（独立 index，天然不碰主仓 index.lock），
完成后由 reconciler 三路合并收敛、worktree 即弃（task 结束即删）。

- worktree 根：``<repo>/.xeyo/worktrees/wt_<task短名>``（``.xeyo/`` 已被
  .gitignore 覆盖，不入库）；
- 分支名：``coord/task/<task短名>``——短名取 task_id 的字母数字前 16 位
  （Windows 短名防路径长度）；
- 所有 git 调用带 ``GIT_OPTIONAL_LOCKS=0``，不写可选锁文件；
- commit 作者统一 ``coord-worker <coord@local>``，产物可按作者识别。

本模块只做 git 子进程封装，不碰 CoordStore（依赖方向：reconciler /
worker_pool 编排两者）。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: git 子进程环境：禁可选锁（index.lock 事故防线之一）。
GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}

GIT_TIMEOUT_SEC = 120


class WorktreeError(RuntimeError):
    """git 子进程失败（message 为中性事实，供上报 findings）。"""


def git(cwd: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """跑一条 git 命令；check=True 时失败抛 WorktreeError。"""
    try:
        r = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(cwd), env=GIT_ENV, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"git_timeout: {' '.join(args[:3])} exceeded {GIT_TIMEOUT_SEC}s") from exc
    except OSError as exc:
        raise WorktreeError(f"git_spawn_failed: {exc}") from exc
    if check and r.returncode != 0:
        raise WorktreeError(
            f"git_failed ({r.returncode}): {' '.join(args[:3])} :: {r.stderr.strip()[:300]}"
        )
    return r


def task_short(task_id: str) -> str:
    """task 短名：字母数字前 16 位（Windows 路径长度防线）。"""
    raw = (task_id or "").strip()
    if raw.startswith("task_"):
        raw = raw[len("task_"):]
    safe = "".join(c for c in raw if c.isalnum())
    return (safe or "t")[:16]


def worktree_path(repo: str | Path, task_id: str) -> Path:
    return Path(repo) / ".xeyo" / "worktrees" / f"wt_{task_short(task_id)}"


def branch_name(task_id: str) -> str:
    return f"coord/task/{task_short(task_id)}"


@dataclass
class WorktreeHandle:
    repo: Path
    path: Path
    branch: str
    task_id: str


class WorktreeManager:
    """worktree add → checkout(base) → commit → remove 的单仓生命周期管理。"""

    def __init__(self, repo: str | Path) -> None:
        self.repo = Path(repo).resolve()

    # -- 生命周期 -----------------------------------------------------------

    def create(self, task_id: str, base_commit: str) -> WorktreeHandle:
        """从 base_commit 建隔离 worktree + 专用分支；有残留先清（重做场景）。"""
        path = worktree_path(self.repo, task_id)
        branch = branch_name(task_id)
        if path.exists():
            self.remove(task_id)
        git(self.repo, "worktree", "add", "-b", branch, str(path), base_commit or "HEAD")
        return WorktreeHandle(repo=self.repo, path=path, branch=branch, task_id=task_id)

    def load(self, task_id: str) -> WorktreeHandle:
        """按约定路径推导既有 handle（reconciler 用）；不存在抛 WorktreeError。"""
        path = worktree_path(self.repo, task_id)
        if not path.exists():
            raise WorktreeError(f"worktree_missing: {path}")
        return WorktreeHandle(repo=self.repo, path=path,
                              branch=branch_name(task_id), task_id=task_id)

    def exists(self, task_id: str) -> bool:
        return worktree_path(self.repo, task_id).exists()

    def remove(self, task_id: str) -> None:
        """完成即弃：删 worktree + 专用分支（尽力而为，失败不挡主路径）。"""
        path = worktree_path(self.repo, task_id)
        branch = branch_name(task_id)
        if path.exists():
            git(self.repo, "worktree", "remove", "--force", str(path), check=False)
        git(self.repo, "worktree", "prune", check=False)
        git(self.repo, "branch", "-D", branch, check=False)

    # -- 内容操作 -----------------------------------------------------------

    def head(self, handle: WorktreeHandle) -> str:
        return git(handle.path, "rev-parse", "HEAD").stdout.strip()

    def commit_all(self, handle: WorktreeHandle, message: str = "") -> str | None:
        """add -A + commit（worktree 内）；无改动返回 None，有改动返回新 head。"""
        status = git(handle.path, "status", "--porcelain")
        if not status.stdout.strip():
            return None
        git(handle.path, "add", "-A")
        git(handle.path, "-c", "user.name=coord-worker", "-c", "user.email=coord@local",
            "commit", "-m", message or f"coord: task {handle.task_id}")
        return self.head(handle)

    def conflict_files(self, handle: WorktreeHandle) -> list[str]:
        """rebase 中断态的未合并路径（中性事实，供 findings）。"""
        r = git(handle.path, "diff", "--name-only", "--diff-filter=U", check=False)
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]


__all__ = ["GIT_ENV", "WorktreeError", "WorktreeHandle", "WorktreeManager",
           "branch_name", "git", "task_short", "worktree_path"]
