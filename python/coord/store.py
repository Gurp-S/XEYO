"""CoordStore 数据结构与纯操作：任务表 / scope 租约 / ask 队列。

本模块只定义结构与内存语义，不做任何 IO（文件化在 ``file_store.py``）。
设计契约（v1.1 计划 §2/§3）：
- 任务认领 = CAS（status pending → claimed，仅一次成功）；
- Task.base_commit：认领时记录 main head，退回重放的对齐基线；
- status 枚举含 ``PENDING_REVIEW``：ASK 挂起即释放 scope 租约 → 转此态；
  allow 后原 worker 优先恢复（claimed_by 保留，他人不可抢）；
- reopen 携带结构化 findings[]；reopen 硬顶 REOPEN_LIMIT，超限转 blocked（熔断）；
- scope 租约 = 路径归一后交集互斥（沿用 scheduler.scope_conflicts 语义：
  任一方为空视为冲突——保守串行）。
错误信息一律中性事实，不含建议/评价（引擎铁律）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

STATUS_PENDING = "pending"
STATUS_CLAIMED = "claimed"
STATUS_READY_TO_MERGE = "ready_to_merge"  # worker 已上交 worktree 分支，待 reconciler 收敛
STATUS_MERGED = "merged"  # reconciler 三路合并成功，已 fast-forward main
STATUS_PENDING_REVIEW = "PENDING_REVIEW"
STATUS_COMPLETED = "completed"
STATUS_REOPENED = "reopened"
STATUS_BLOCKED = "blocked"
STATUS_SUPERSEDED = "superseded"  # 被 replan 子任务替代（终态，不可认领）

#: reopen 熔断：允许 REOPEN_LIMIT 次打回重做；第 REOPEN_LIMIT+1 次不再重开，
#: 转 blocked 交人在环（v1.1 §3 阶段 2：打回-重做死循环防线）。
REOPEN_LIMIT = 3

SCOPE_LEASE_TTL_SEC = 10 * 60  # 与 session_presence FILE_OWNERSHIP_TTL 对齐
ASK_TTL_SEC = 10 * 60          # 无人值守等待人裁决的挂起时限
ASK_STATUS_PENDING = "pending"
ASK_STATUS_RESOLVED = "resolved"
ASK_STATUS_EXPIRED = "expired"  # 超 TTL 无人裁决（中性事实；任务仍挂起，不 deny 丢弃）


def norm_scope_path(p: str, root: str | Path | None = None) -> str:
    """归一 scope 路径为 posix 相对形式；无法归一返回原样小写 posix 化。"""
    raw = (p or "").strip().replace("\\", "/")
    if not raw:
        return ""
    try:
        path = Path(raw).expanduser()
        if path.is_absolute() and root is not None:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        if path.is_absolute():
            return path.resolve().as_posix()
        return path.as_posix()
    except (OSError, ValueError):
        return raw.lstrip("./")


def scope_conflicts(a: list[str], b: list[str]) -> bool:
    """路径级写范围冲突（coord 加严档，2026-09-10 热点洞修复）。

    任一方为空 → 冲突（保守串行）。非空时**前缀包含也判冲突**：
    ``src/`` vs ``src/a.py`` 会在合并层真撞车，精确字符串交集漏检 →
    双放行 → 冲突重试烧 token。与 ``engine/scheduler.scope_conflicts``
    （同会话串行调度，精确交集够用）**有意分歧**：跨进程派发层取严。"""
    left = {norm_scope_path(p).rstrip("/") for p in a if norm_scope_path(p)}
    right = {norm_scope_path(p).rstrip("/") for p in b if norm_scope_path(p)}
    left.discard("")
    right.discard("")
    if not left or not right:
        return True
    if left & right:
        return True
    for l in left:
        for r in right:
            if l.startswith(r + "/") or r.startswith(l + "/"):
                return True
    return False


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


@dataclass
class Task:
    task_id: str
    goal_id: str
    title: str
    scope: list[str] = field(default_factory=list)
    model: str = ""
    max_turns: int = 0
    required_tools: list[str] = field(default_factory=list)
    base_commit: str = ""
    status: str = STATUS_PENDING
    claimed_by: str = ""
    branch: str = ""  # worker 上交的 worktree 分支（coord/task/<短名>）
    parent_id: str = ""  # replan 产物的来源任务（scope 执法 + 溯源）
    brief: str = ""  # 任务卡正文（worker 会话首条消息来源，不进 T_now）
    revision: int = 0
    reopen_count: int = 0
    findings: list[dict] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "title": self.title,
            "scope": list(self.scope),
            "model": self.model,
            "max_turns": int(self.max_turns),
            "required_tools": list(self.required_tools),
            "base_commit": self.base_commit,
            "status": self.status,
            "claimed_by": self.claimed_by,
            "branch": self.branch,
            "parent_id": self.parent_id,
            "brief": self.brief,
            "revision": int(self.revision),
            "reopen_count": int(self.reopen_count),
            "findings": [dict(f) for f in self.findings if isinstance(f, dict)],
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        return cls(
            task_id=str(raw.get("task_id") or ""),
            goal_id=str(raw.get("goal_id") or ""),
            title=str(raw.get("title") or ""),
            scope=[str(p) for p in (raw.get("scope") or [])],
            model=str(raw.get("model") or ""),
            max_turns=int(raw.get("max_turns") or 0),
            required_tools=[str(t) for t in (raw.get("required_tools") or [])],
            base_commit=str(raw.get("base_commit") or ""),
            status=str(raw.get("status") or STATUS_PENDING),
            claimed_by=str(raw.get("claimed_by") or ""),
            branch=str(raw.get("branch") or ""),
            parent_id=str(raw.get("parent_id") or ""),
            brief=str(raw.get("brief") or ""),
            revision=int(raw.get("revision") or 0),
            reopen_count=int(raw.get("reopen_count") or 0),
            findings=[dict(f) for f in (raw.get("findings") or []) if isinstance(f, dict)],
            created_at=float(raw.get("created_at") or 0.0),
            updated_at=float(raw.get("updated_at") or 0.0),
        )


def new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def new_task(goal_id: str, title: str, scope: list[str], *, model: str = "",
             max_turns: int = 0, required_tools: list[str] | None = None,
             parent_id: str = "", brief: str = "") -> Task:
    now = time.time()
    return Task(
        task_id=new_task_id(),
        goal_id=str(goal_id or "").strip(),
        title=str(title or "").strip(),
        scope=[str(p) for p in (scope or [])],
        model=str(model or "").strip(),
        max_turns=int(max_turns or 0),
        required_tools=[str(t) for t in (required_tools or [])],
        parent_id=str(parent_id or "").strip(),
        brief=str(brief or ""),
        status=STATUS_PENDING,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def findings_files(findings: list[dict]) -> list[str]:
    """从结构化 findings 抽文件路径集合（去重、保序）——重规划 scope 白名单来源。"""
    seen: dict[str, None] = {}
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        for key in ("file", "path"):
            v = f.get(key)
            if isinstance(v, str) and v.strip():
                seen.setdefault(norm_scope_path(v), None)
    return list(seen.keys())


def enforce_replan_scope(parent: Task, proposed_scope: list[str]) -> bool:
    """机器执法（v1.1 §3 阶段 2）：重规划产物 scope ⊆ 原 scope ∪ findings.files。

    超界 → False（调用方拒收，返回中性结果；禁止 Reviewer/Planner 擅自扩大
    scope 重构）。空 proposed → False（无 scope 不可认领，保守）。"""
    allowed = {norm_scope_path(p) for p in parent.scope if norm_scope_path(p)}
    allowed |= {norm_scope_path(p) for p in findings_files(parent.findings) if norm_scope_path(p)}
    proposed = {norm_scope_path(p) for p in (proposed_scope or [])}
    proposed.discard("")
    if not proposed:
        return False
    return proposed.issubset(allowed)


def claim_task(task: Task, worker_id: str, base_commit: str) -> Task | None:
    """CAS 认领：pending / reopened（被打回待重做）可认领。其余态 → None。

    阶段 2（v1.1）：**无 scope 任务不可认领**——scope 声明强制由认领闸门
    机器执法（执行层拒绝，不写劝导文本）。"""
    if task.status not in (STATUS_PENDING, STATUS_REOPENED):
        return None
    if not any(norm_scope_path(p) for p in task.scope):
        return None
    now = time.time()
    return replace(
        task,
        status=STATUS_CLAIMED,
        claimed_by=str(worker_id or "").strip(),
        base_commit=str(base_commit or "").strip(),
        revision=task.revision + 1,
        updated_at=now,
    )


def mark_pending_review(task: Task, worker_id: str) -> Task | None:
    """ASK 挂起：claimed → PENDING_REVIEW（仅持有者本人可操作）。"""
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    return replace(task, status=STATUS_PENDING_REVIEW,
                   revision=task.revision + 1, updated_at=time.time())


def resume_task(task: Task, worker_id: str) -> Task | None:
    """allow 恢复：PENDING_REVIEW → claimed；仅原持有者（v1.1 §3 阶段 2）。"""
    if task.status != STATUS_PENDING_REVIEW or task.claimed_by != str(worker_id or "").strip():
        return None
    return replace(task, status=STATUS_CLAIMED,
                   revision=task.revision + 1, updated_at=time.time())


def suspend_release(task: Task, worker_id: str) -> Task | None:
    """ASK 无人裁决超 TTL：PENDING_REVIEW → pending，清 claimed_by（转 pending
    挂起，可被重新认领；非 deny 丢弃——v1.1 §3 阶段 2 网关超时语义）。"""
    if task.status != STATUS_PENDING_REVIEW or task.claimed_by != str(worker_id or "").strip():
        return None
    return replace(task, status=STATUS_PENDING, claimed_by="",
                   revision=task.revision + 1, updated_at=time.time())


def review_reopen(task: Task, worker_id: str, findings: list[dict]) -> Task | None:
    """ASK 裁决 deny/remind：PENDING_REVIEW → reopened(→blocked 熔断)。

    与 reopen_task（要求 claimed）互补——suspend 已把态转 PENDING_REVIEW，
    打回须从该态直接进 reopen 轨道（base_commit 保持不变，重做仍基于原基线）。"""
    if task.status != STATUS_PENDING_REVIEW or task.claimed_by != str(worker_id or "").strip():
        return None
    return _reopen_or_block(task, task.base_commit, findings)


def supersede_task(task: Task) -> Task | None:
    """replan 子任务接管后，原任务转 superseded（终态，清持有，不可认领）。"""
    if task.status not in (STATUS_REOPENED, STATUS_CLAIMED):
        return None
    return replace(task, status=STATUS_SUPERSEDED, claimed_by="",
                   revision=task.revision + 1, updated_at=time.time())


def complete_task(task: Task, worker_id: str) -> Task | None:
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    return replace(task, status=STATUS_COMPLETED,
                   revision=task.revision + 1, updated_at=time.time())


def _reopen_or_block(task: Task, base_commit: str, findings: list[dict]) -> Task:
    """打回共用实现：允许 REOPEN_LIMIT 次重开；第 REOPEN_LIMIT+1 次转 blocked。

    base_commit 对齐新基线（传空 = 保持原值）。"""
    count = task.reopen_count + 1
    now = time.time()
    clean = [dict(f) for f in (findings or []) if isinstance(f, dict)]
    base = str(base_commit or "") or task.base_commit
    if count > REOPEN_LIMIT:
        return replace(task, status=STATUS_BLOCKED, reopen_count=count,
                       base_commit=base, findings=clean,
                       revision=task.revision + 1, updated_at=now)
    return replace(task, status=STATUS_REOPENED, reopen_count=count,
                   base_commit=base, findings=clean,
                   revision=task.revision + 1, updated_at=now)


def reopen_task(task: Task, worker_id: str, findings: list[dict]) -> Task | None:
    """Reviewer 打回：claimed → reopened(→blocked 熔断)；base_commit 保持认领值。"""
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    return _reopen_or_block(task, task.base_commit, findings)


def submit_result(task: Task, worker_id: str, branch: str) -> Task | None:
    """worker 上交产物：claimed → ready_to_merge，附 worktree 分支（仅持有者本人）。"""
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    return replace(task, status=STATUS_READY_TO_MERGE,
                   branch=str(branch or "").strip(),
                   revision=task.revision + 1, updated_at=time.time())


def mark_merged(task: Task) -> Task | None:
    """reconciler 收敛成功（update-ref ff 完成后）：ready_to_merge → merged。"""
    if task.status != STATUS_READY_TO_MERGE:
        return None
    return replace(task, status=STATUS_MERGED,
                   revision=task.revision + 1, updated_at=time.time())


def reopen_conflict(task: Task, base_commit: str, findings: list[dict]) -> Task | None:
    """reconciler 三路合并真冲突：ready_to_merge → reopened(→blocked 熔断)。

    base_commit 写回**最新** main head（v1.1 §3：worker 基于新基线重放意图，
    杜绝基于旧快照的无效重试）。"""
    if task.status != STATUS_READY_TO_MERGE:
        return None
    return _reopen_or_block(task, base_commit, findings)


def worker_failed(task: Task, worker_id: str, findings: list[dict]) -> Task | None:
    """worker 执行异常：claimed → reopened(→blocked 熔断)，任务可被重试。"""
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    return _reopen_or_block(task, task.base_commit, findings)


# ---------------------------------------------------------------------------
# Scope lease
# ---------------------------------------------------------------------------


@dataclass
class ScopeLease:
    lease_id: str
    owner: str
    paths: list[str]
    acquired_at: float
    expires_at: float

    def to_dict(self) -> dict:
        return {
            "lease_id": self.lease_id,
            "owner": self.owner,
            "paths": list(self.paths),
            "acquired_at": float(self.acquired_at),
            "expires_at": float(self.expires_at),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "ScopeLease":
        return cls(
            lease_id=str(raw.get("lease_id") or ""),
            owner=str(raw.get("owner") or ""),
            paths=[str(p) for p in (raw.get("paths") or [])],
            acquired_at=float(raw.get("acquired_at") or 0.0),
            expires_at=float(raw.get("expires_at") or 0.0),
        )


def new_scope_lease(owner: str, paths: list[str], ttl: float = SCOPE_LEASE_TTL_SEC,
                    now: float | None = None) -> ScopeLease:
    ts = time.time() if now is None else float(now)
    return ScopeLease(
        lease_id=f"slease_{uuid.uuid4().hex[:12]}",
        owner=str(owner or "").strip(),
        paths=[norm_scope_path(p) for p in (paths or []) if norm_scope_path(p)],
        acquired_at=ts,
        expires_at=ts + float(ttl),
    )


def prune_leases(leases: list[ScopeLease], now: float | None = None) -> list[ScopeLease]:
    ts = time.time() if now is None else float(now)
    return [l for l in leases if l.expires_at > ts]


def acquire_scope(
    leases: list[ScopeLease], owner: str, paths: list[str],
    ttl: float = SCOPE_LEASE_TTL_SEC, now: float | None = None,
) -> tuple[list[ScopeLease], ScopeLease] | None:
    """在活动租约上追加：与他会话路径交集 → None（拒绝）；同 owner 重叠 → 续约合并。

    返回 ``(替换后的全量租约列表, 本次生效的 lease)``。"""
    ts = time.time() if now is None else float(now)
    active = prune_leases(leases, ts)
    candidate = new_scope_lease(owner, paths, ttl, ts)
    if not candidate.paths:
        return None
    for l in active:
        if l.owner == candidate.owner:
            continue
        if scope_conflicts(l.paths, candidate.paths):
            return None
    # 同 owner 重叠：合并进现有租约（续约语义），避免同 worker 反复 acquire 堆积。
    merged: ScopeLease | None = None
    out: list[ScopeLease] = []
    for l in active:
        if l.owner == candidate.owner and merged is None:
            merged = replace(l, paths=sorted(set(l.paths) | set(candidate.paths)),
                             expires_at=ts + float(ttl))
            out.append(merged)
        elif l.owner == candidate.owner and merged is not None:
            merged = replace(merged, paths=sorted(set(merged.paths) | set(l.paths)),
                             expires_at=ts + float(ttl))
        else:
            out.append(l)
    if merged is None:
        out.append(candidate)
    return out, merged if merged is not None else candidate


def release_scope(leases: list[ScopeLease], lease_id: str, owner: str) -> list[ScopeLease]:
    return [l for l in leases if not (l.lease_id == lease_id and l.owner == owner)]


def release_scope_paths(leases: list[ScopeLease], owner: str,
                        paths: list[str]) -> list[ScopeLease]:
    """从该 owner 的活动租约移除指定路径（任务离开 hands 时闭环）；租约清空则删除。

    同 owner 的多任务租约会合并成一条（acquire_scope 续约语义），因此释放必须
    按路径粒度，而不是整条租约——否则误放同 worker 其他在途任务的 scope。"""
    drop = {norm_scope_path(p) for p in (paths or []) if norm_scope_path(p)}
    if not drop:
        return leases
    out: list[ScopeLease] = []
    for l in leases:
        if l.owner != owner:
            out.append(l)
            continue
        remain = [p for p in l.paths if p not in drop]
        if remain:
            out.append(replace(l, paths=remain))
    return out


# ---------------------------------------------------------------------------
# Ask queue
# ---------------------------------------------------------------------------


@dataclass
class AskItem:
    ask_id: str
    root: str
    worker_id: str
    kind: str
    payload: str
    task_id: str = ""
    lease_id: str = ""
    status: str = ASK_STATUS_PENDING
    created_at: float = 0.0
    resolved_at: float = 0.0
    choice: str = ""

    def to_dict(self) -> dict:
        return {
            "ask_id": self.ask_id,
            "root": self.root,
            "worker_id": self.worker_id,
            "kind": self.kind,
            "payload": self.payload,
            "task_id": self.task_id,
            "lease_id": self.lease_id,
            "status": self.status,
            "created_at": float(self.created_at),
            "resolved_at": float(self.resolved_at),
            "choice": self.choice,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "AskItem":
        return cls(
            ask_id=str(raw.get("ask_id") or ""),
            root=str(raw.get("root") or ""),
            worker_id=str(raw.get("worker_id") or ""),
            kind=str(raw.get("kind") or ""),
            payload=str(raw.get("payload") or ""),
            task_id=str(raw.get("task_id") or ""),
            lease_id=str(raw.get("lease_id") or ""),
            status=str(raw.get("status") or ASK_STATUS_PENDING),
            created_at=float(raw.get("created_at") or 0.0),
            resolved_at=float(raw.get("resolved_at") or 0.0),
            choice=str(raw.get("choice") or ""),
        )


def new_ask(root: str, worker_id: str, kind: str, payload: str, *,
            task_id: str = "", lease_id: str = "") -> AskItem:
    return AskItem(
        ask_id=f"ask_{uuid.uuid4().hex[:12]}",
        root=str(root or ""),
        worker_id=str(worker_id or "").strip(),
        kind=str(kind or "").strip(),
        payload=str(payload or ""),
        task_id=str(task_id or "").strip(),
        lease_id=str(lease_id or "").strip(),
        status=ASK_STATUS_PENDING,
        created_at=time.time(),
    )


__all__ = [
    "ASK_STATUS_EXPIRED",
    "ASK_STATUS_PENDING",
    "ASK_STATUS_RESOLVED",
    "ASK_TTL_SEC",
    "AskItem",
    "REOPEN_LIMIT",
    "SCOPE_LEASE_TTL_SEC",
    "STATUS_BLOCKED",
    "STATUS_CLAIMED",
    "STATUS_COMPLETED",
    "STATUS_MERGED",
    "STATUS_PENDING",
    "STATUS_PENDING_REVIEW",
    "STATUS_READY_TO_MERGE",
    "STATUS_REOPENED",
    "STATUS_SUPERSEDED",
    "ScopeLease",
    "Task",
    "acquire_scope",
    "claim_task",
    "complete_task",
    "enforce_replan_scope",
    "findings_files",
    "mark_merged",
    "mark_pending_review",
    "new_ask",
    "new_scope_lease",
    "new_task",
    "new_task_id",
    "norm_scope_path",
    "prune_leases",
    "release_scope",
    "release_scope_paths",
    "reopen_conflict",
    "reopen_task",
    "resume_task",
    "review_reopen",
    "scope_conflicts",
    "submit_result",
    "supersede_task",
    "suspend_release",
    "worker_failed",
]
