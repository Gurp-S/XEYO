"""子代理工作区隔离：git worktree + 可回滚的三方合并回收。

为什么需要它（2026 开源 agent 共性趋势）：多个子代理并行改**同一批文件**时，
共享 checkout 的收敛手段只有「后写覆盖」或「content-hash stale 拒绝重试」。
worktree 隔离把「冲突」从**写入时刻**推迟到**回收时刻**，于是两个改同一方法
不同行的子代理可以各自完成、再合并——这是 codex / Qwen Code 的做法，也是
``coord/worktree.py`` 已经在跨进程层做过的事。本模块把它下沉到**单个子代理**粒度。

与 ``coord/`` 的分工：
- ``coord/`` 是**跨进程 worker 池**（任务表 + CAS 认领 + 唯一 reconciler），默认
  ``backend=memory`` 未启用；本模块**不碰任务表**，只服务「模型显式要求隔离的
  那一次 ``Agent`` 调用」。
- 回收策略**有意与 Reconciler 不同**：Reconciler 推进 ``refs/heads/main``（不碰
  工作树，适合 headless）；本模块把改动**落进主工作树**（适合交互式会话，主会话
  本来就不提交、直接改文件）。

合并策略（三步，全程可回滚）：
1. worktree 内 ``commit_all`` → 得到新 head（无改动则直接回收）；
2. 主仓 ``git apply --check`` 干净应用 → 直接落地；
3. 不干净则 ``git apply --3way`` 做真三方合并（**这一步才可能自动合上"同一文件
   不同行"**）；若仍失败，按 patch 文件清单**逐文件还原到尝试前的字节**，保留
   worktree 与分支，把冲突文件作为中性事实报回。

「真冲突不写冲突标记」是有意的：与 ``coord/reconciler.py``「冲突即 abort + 退回
重做，不尝试自动解决」同一条立场——交互式会话里往用户文件塞 ``<<<<<<<`` 是
把决策成本转嫁给用户，而不是替他解决。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coord.worktree import (
    GIT_ENV,
    GIT_TIMEOUT_SEC,
    WorktreeError,
    WorktreeManager,
    git,
)

#: 隔离产物的提交作者（可按作者识别，与 coord 的 coord-worker 区分）。
ISOLATION_AUTHOR = ("xeyo-subagent", "subagent@local")


class IsolationUnavailable(RuntimeError):
    """无法建立隔离工作区（非 git 仓库 / git 不可用）。"""


@dataclass
class IsolationOutcome:
    """一次隔离回收的结果（全部为中性事实）。"""

    ok: bool
    merged: bool = False
    no_changes: bool = False
    branch: str = ""
    worktree: str = ""
    changed_files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    detail: str = ""

    def summary(self) -> str:
        """一行中性事实（供 Agent tool_result 正文）。"""
        if self.no_changes:
            return "worktree isolation: no file changes"
        if self.merged:
            files = ", ".join(self.changed_files[:8]) or "(none)"
            more = "" if len(self.changed_files) <= 8 else f" (+{len(self.changed_files) - 8})"
            return f"worktree isolation: applied {files}{more}"
        if self.conflicts:
            files = ", ".join(self.conflicts[:8]) or "(unknown)"
            return (
                f"worktree isolation: not applied (conflict); isolated copy kept at "
                f"{self.worktree} on branch {self.branch}; conflicting files: {files}"
            )
        return f"worktree isolation: not applied ({self.detail or 'unknown'})"


def _git_stdin(
    cwd: str | Path, args: list[str], payload: bytes, *, check: bool = False
) -> subprocess.CompletedProcess:
    """跑一条需要 stdin 的 git 命令（apply 用）。"""
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(cwd),
            env=GIT_ENV,
            input=payload,
            capture_output=True,
            timeout=GIT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"git_timeout: {' '.join(args[:3])}") from exc
    except OSError as exc:
        raise WorktreeError(f"git_spawn_failed: {exc}") from exc
    if check and result.returncode != 0:
        raise WorktreeError(
            f"git_failed ({result.returncode}): {' '.join(args[:3])} :: "
            f"{result.stderr.decode('utf-8', 'replace').strip()[:300]}"
        )
    return result


def _is_git_repo(repo: str | Path) -> bool:
    try:
        result = git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    except WorktreeError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _snapshot(repo: Path, files: list[str]) -> dict[str, bytes | None]:
    """记录 patch 涉及文件在**尝试合并前**的字节（None = 文件不存在）。"""
    snapshot: dict[str, bytes | None] = {}
    for name in files:
        target = repo / name
        try:
            snapshot[name] = target.read_bytes()
        except OSError:
            snapshot[name] = None
    return snapshot


def _restore(repo: Path, snapshot: dict[str, bytes | None]) -> None:
    """把文件还原到快照状态（只动 patch 涉及的文件，不碰其它未提交改动）。"""
    for name, payload in snapshot.items():
        target = repo / name
        try:
            if payload is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
        except OSError:  # noqa: BLE001 — 还原尽力而为，失败不掩盖主结论
            continue


class WorktreeIsolation:
    """一次子代理运行的隔离工作区（上下文管理器）。

    用法::

        with WorktreeIsolation(repo, task_id) as iso:
            run_subagent(workspace_root=iso.path, ...)
        iso.outcome   # IsolationOutcome
    """

    def __init__(self, repo: str | Path, task_id: str, *, message: str = "") -> None:
        self.repo = Path(repo).resolve()
        self.task_id = str(task_id or "sub")
        self.message = message or f"subagent: {self.task_id}"
        self.path: Path = self.repo
        self.branch = ""
        self.base = ""
        self.outcome = IsolationOutcome(ok=False, detail="not started")
        self._manager: WorktreeManager | None = None
        self._active = False

    # -- 生命周期 -----------------------------------------------------------

    def __enter__(self) -> "WorktreeIsolation":
        if not _is_git_repo(self.repo):
            raise IsolationUnavailable(
                f"not a git repository: {self.repo}"
            )
        try:
            self.base = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        except WorktreeError as exc:
            raise IsolationUnavailable(f"cannot resolve HEAD: {exc}") from exc
        self._manager = WorktreeManager(self.repo)
        try:
            handle = self._manager.create(self.task_id, self.base)
        except WorktreeError as exc:
            raise IsolationUnavailable(f"worktree create failed: {exc}") from exc
        self.path = handle.path
        self.branch = handle.branch
        self._active = True
        self.outcome = IsolationOutcome(
            ok=True, branch=self.branch, worktree=str(self.path), detail="running"
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if not self._active or self._manager is None:
            return False
        try:
            if exc is not None:
                # 子代理中途失败：不合并（半成品不该落地），保留隔离副本供检查。
                self.outcome = IsolationOutcome(
                    ok=False,
                    branch=self.branch,
                    worktree=str(self.path),
                    detail=f"subagent failed: {type(exc).__name__}",
                )
                return False
            self._collect()
        except Exception as inner:  # noqa: BLE001 — 回收失败不掩盖子代理结论
            self.outcome = IsolationOutcome(
                ok=False,
                branch=self.branch,
                worktree=str(self.path),
                detail=f"collect failed: {type(inner).__name__}: {inner}",
            )
        finally:
            self._active = False
        return False

    # -- 回收 ---------------------------------------------------------------

    def _collect(self) -> None:
        assert self._manager is not None
        handle = self._manager.load(self.task_id)
        try:
            head = self._manager.commit_all(handle, self.message)
        except WorktreeError as exc:
            self.outcome = IsolationOutcome(
                ok=False,
                branch=self.branch,
                worktree=str(self.path),
                detail=f"commit failed: {exc}",
            )
            return
        if head is None:
            self.outcome = IsolationOutcome(
                ok=True, no_changes=True, branch=self.branch,
                worktree=str(self.path), detail="no changes",
            )
            self._discard()
            return

        files = self._changed_files(head)
        self.outcome = IsolationOutcome(
            ok=True, branch=self.branch, worktree=str(self.path),
            changed_files=files, detail="",
        )
        if not files:
            self._discard()
            return

        patch = self._patch(head)
        snapshot = _snapshot(self.repo, files)
        if _git_stdin(self.repo, ["apply", "--check"], patch).returncode == 0:
            if _git_stdin(self.repo, ["apply"], patch).returncode == 0:
                self.outcome.merged = True
                self._discard()
                return
        # 干净应用不行 → 真三方合并（这一步才可能自动合上"同文件不同行"）。
        if _git_stdin(self.repo, ["apply", "--3way"], patch).returncode == 0:
            self.outcome.merged = True
            self._discard()
            return
        # 真冲突：把 patch 涉及的文件还原到尝试前的字节，保留隔离副本。
        _restore(self.repo, snapshot)
        self.outcome.conflicts = list(files)
        self.outcome.detail = "three-way merge reported conflicts"

    def _changed_files(self, head: str) -> list[str]:
        result = git(self.repo, "diff", "--name-only", self.base, head, check=False)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _patch(self, head: str) -> bytes:
        try:
            result = subprocess.run(
                [
                    "git", "-c", "core.quotepath=false",
                    "diff", "--binary", self.base, head,
                ],
                cwd=str(self.repo),
                env=GIT_ENV,
                capture_output=True,
                timeout=GIT_TIMEOUT_SEC,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise WorktreeError(f"git diff failed: {exc}") from exc
        return result.stdout or b""

    def _discard(self) -> None:
        """完成即弃：删 worktree + 分支（尽力而为）。"""
        if self._manager is None:
            return
        try:
            self._manager.remove(self.task_id)
        except Exception:  # noqa: BLE001 — 清理失败不影响已合并的事实
            pass


__all__ = [
    "ISOLATION_AUTHOR",
    "IsolationOutcome",
    "IsolationUnavailable",
    "WorktreeIsolation",
    "is_git_repo",
]


def is_git_repo(repo: str | Path) -> bool:
    """公开判定：该路径是否在 git 工作树内（隔离可用性前置）。"""
    return _is_git_repo(repo)
