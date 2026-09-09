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
STATUS_PENDING_REVIEW = "PENDING_REVIEW"
STATUS_COMPLETED = "completed"
STATUS_REOPENED = "reopened"
STATUS_BLOCKED = "blocked"

#: reopen 熔断：第 REOPEN_LIMIT 次打回后不再重开，转 blocked 交人在环。
REOPEN_LIMIT = 3

SCOPE_LEASE_TTL_SEC = 10 * 60  # 与 session_presence FILE_OWNERSHIP_TTL 对齐
ASK_STATUS_PENDING = "pending"
ASK_STATUS_RESOLVED = "resolved"


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
    """路径级写范围冲突。语义与 ``engine/scheduler.scope_conflicts`` 一致：
    任一方为空 → 冲突（保守串行）；否则归一后有交集才冲突。"""
    left = {norm_scope_path(p) for p in a if norm_scope_path(p)}
    right = {norm_scope_path(p) for p in b if norm_scope_path(p)}
    left.discard("")
    right.discard("")
    if not left or not right:
        return True
    return bool(left & right)


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
            revision=int(raw.get("revision") or 0),
            reopen_count=int(raw.get("reopen_count") or 0),
            findings=[dict(f) for f in (raw.get("findings") or []) if isinstance(f, dict)],
            created_at=float(raw.get("created_at") or 0.0),
            updated_at=float(raw.get("updated_at") or 0.0),
        )


def new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def new_task(goal_id: str, title: str, scope: list[str], *, model: str = "",
             max_turns: int = 0, required_tools: list[str] | None = None) -> Task:
    now = time.time()
    return Task(
        task_id=new_task_id(),
        goal_id=str(goal_id or "").strip(),
        title=str(title or "").strip(),
        scope=[str(p) for p in (scope or [])],
        model=str(model or "").strip(),
        max_turns=int(max_turns or 0),
        required_tools=[str(t) for t in (required_tools or [])],
        status=STATUS_PENDING,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def claim_task(task: Task, worker_id: str, base_commit: str) -> Task | None:
    """CAS 认领：pending / reopened（被打回待重做）可认领。其余态 → None。"""
    if task.status not in (STATUS_PENDING, STATUS_REOPENED):
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


def complete_task(task: Task, worker_id: str) -> Task | None:
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    return replace(task, status=STATUS_COMPLETED,
                   revision=task.revision + 1, updated_at=time.time())


def reopen_task(task: Task, worker_id: str, findings: list[dict]) -> Task | None:
    """Reviewer 打回：claimed → reopened(→pending 可再认领)；含熔断。

    返回 (task, blocked: bool) 语义由调用方拆：本函数直接给出终态。"""
    if task.status != STATUS_CLAIMED or task.claimed_by != str(worker_id or "").strip():
        return None
    count = task.reopen_count + 1
    now = time.time()
    clean = [dict(f) for f in (findings or []) if isinstance(f, dict)]
    if count >= REOPEN_LIMIT:
        return replace(task, status=STATUS_BLOCKED, reopen_count=count,
                       findings=clean, revision=task.revision + 1, updated_at=now)
    return replace(task, status=STATUS_REOPENED, reopen_count=count,
                   findings=clean, revision=task.revision + 1, updated_at=now)


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
            status=str(raw.get("status") or ASK_STATUS_PENDING),
            created_at=float(raw.get("created_at") or 0.0),
            resolved_at=float(raw.get("resolved_at") or 0.0),
            choice=str(raw.get("choice") or ""),
        )


def new_ask(root: str, worker_id: str, kind: str, payload: str) -> AskItem:
    return AskItem(
        ask_id=f"ask_{uuid.uuid4().hex[:12]}",
        root=str(root or ""),
        worker_id=str(worker_id or "").strip(),
        kind=str(kind or "").strip(),
        payload=str(payload or ""),
        status=ASK_STATUS_PENDING,
        created_at=time.time(),
    )


__all__ = [
    "ASK_STATUS_PENDING",
    "ASK_STATUS_RESOLVED",
    "AskItem",
    "REOPEN_LIMIT",
    "SCOPE_LEASE_TTL_SEC",
    "STATUS_BLOCKED",
    "STATUS_CLAIMED",
    "STATUS_COMPLETED",
    "STATUS_PENDING",
    "STATUS_PENDING_REVIEW",
    "STATUS_REOPENED",
    "ScopeLease",
    "Task",
    "acquire_scope",
    "claim_task",
    "complete_task",
    "mark_pending_review",
    "new_ask",
    "new_scope_lease",
    "new_task",
    "new_task_id",
    "norm_scope_path",
    "prune_leases",
    "release_scope",
    "reopen_task",
    "resume_task",
    "scope_conflicts",
]
