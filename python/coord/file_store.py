"""CoordFileStore：coord 状态的文件持久化（``<ws>/.xeyo/coord/``）。

目录布局::

    <ws>/.xeyo/coord/
      presence/<roothash>.json     # session_presence 状态（按 workspace root 分片）
      presence/index.json          # session_id -> roothash（无 cwd 反查用）
      tasks/<task_id>.json         # 任务（CAS：revision 递增）
      scope/<roothash>.json        # 活动 scope 租约
      asks/<roothash>.json         # ask 队列
      locks/<name>.lock            # 临界区锁（FileGuard）

原子性：写 = tmp + ``os.replace``；跨进程互斥 = FileGuard（毫秒级临界区）。
降级铁律：任何 IO/锁失败只记 debug 并按"尽力持久化"处理，不挡主路径
（最坏情况 = 退化为进程内行为，即 memory 后端语义）。
本模块不 import engine（依赖方向：engine.session_presence 延迟 import coord）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from coord.locking import FileGuard
from coord.store import (
    AskItem,
    ScopeLease,
    Task,
    acquire_scope as _acquire_scope,
    claim_task as _claim_task,
    complete_task as _complete_task,
    mark_merged as _mark_merged,
    mark_pending_review as _mark_pending_review,
    new_ask as _new_ask,
    prune_leases,
    release_scope as _release_scope,
    reopen_conflict as _reopen_conflict,
    reopen_task as _reopen_task,
    resume_task as _resume_task,
    submit_result as _submit_result,
    worker_failed as _worker_failed,
)

_log = logging.getLogger("xeyo.coord.file")


def root_hash(root: str | Path) -> str:
    return hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log.debug("coord read failed at %s: %s", path, exc)
        return None


def _atomic_write_json(path: Path, data: Any) -> bool:
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        _log.debug("coord write failed at %s: %s", path, exc)
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return False


class CoordFileStore:
    """workspace 级 coord 状态仓。所有方法尽力而为：失败返回安全值并记 debug。"""

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        self.coord_dir = self.root / ".xeyo" / "coord"

    # -- 通用 ---------------------------------------------------------------

    def _guard(self, name: str) -> FileGuard:
        return FileGuard(self.coord_dir / "locks" / f"{name}.lock")

    # -- presence -----------------------------------------------------------

    def _presence_path(self, root: str | Path) -> Path:
        return self.coord_dir / "presence" / f"{root_hash(root)}.json"

    def load_presence(self, root: str | Path) -> dict | None:
        raw = _read_json(self._presence_path(root))
        return raw if isinstance(raw, dict) else None

    def save_presence(self, root: str | Path, state: dict) -> bool:
        return _atomic_write_json(self._presence_path(root), state)

    def _index_path(self) -> Path:
        return self.coord_dir / "presence" / "index.json"

    def note_session_root(self, session_id: str, root: str | Path) -> None:
        """维护 session_id -> {hash, root} 索引（写操作时顺带更新）。读-改-写在锁内。"""
        sid = (session_id or "").strip()
        if not sid:
            return
        root_str = str(Path(root).resolve())
        h = root_hash(root_str)
        with self._guard("pindex") as ok:
            if not ok:
                return
            data = _read_json(self._index_path())
            data = data if isinstance(data, dict) else {}
            cur = data.get(sid)
            if isinstance(cur, dict) and cur.get("hash") == h and cur.get("root") == root_str:
                return
            data[sid] = {"hash": h, "root": root_str}
            if len(data) > 4096:
                # 限幅：超限时丢弃先入的一半（近似 LRU，索引仅用于反查，丢项无害）。
                for k in list(data.keys())[: len(data) - 2048]:
                    data.pop(k, None)
            _atomic_write_json(self._index_path(), data)

    def root_of_session(self, session_id: str) -> str | None:
        """session_id 最近登记的 workspace root 真实路径；未知返回 None。"""
        data = _read_json(self._index_path())
        if not isinstance(data, dict):
            return None
        cur = data.get((session_id or "").strip())
        if isinstance(cur, dict):
            root = cur.get("root")
            if isinstance(root, str) and root:
                return root
        return None

    def remove_session_root(self, session_id: str) -> None:
        """仅删索引项（session_id -> root）。状态删除见 remove_session_from_presence。"""
        sid = (session_id or "").strip()
        if not sid:
            return
        with self._guard("pindex") as ok:
            if not ok:
                return
            data = _read_json(self._index_path())
            if isinstance(data, dict) and sid in data:
                data.pop(sid, None)
                _atomic_write_json(self._index_path(), data)

    def remove_session_from_presence(self, root: str | Path, session_id: str) -> None:
        """从指定 root 的 presence 状态文件里删除该 session（读-改-写在锁内）。"""
        sid = (session_id or "").strip()
        if not sid:
            return
        h = root_hash(root)
        path = self.coord_dir / "presence" / f"{h}.json"
        with self._guard(f"presence-{h}") as ok:
            if not ok:
                return
            data = _read_json(path)
            if isinstance(data, dict):
                sessions = data.get("sessions")
                if isinstance(sessions, dict) and sid in sessions:
                    sessions.pop(sid, None)
                    data["sessions"] = sessions
                    _atomic_write_json(path, data)

    def drop_session(self, session_id: str) -> None:
        """单仓场景便捷方法：状态与索引在同一 coord_dir 时使用。"""
        sid = (session_id or "").strip()
        if not sid:
            return
        h = self.root_of_session_hash(sid)
        if h:
            self.remove_session_from_presence_by_hash(h, sid)
        self.remove_session_root(sid)

    def root_of_session_hash(self, session_id: str) -> str | None:
        data = _read_json(self._index_path())
        if not isinstance(data, dict):
            return None
        cur = data.get((session_id or "").strip())
        if isinstance(cur, dict):
            h = cur.get("hash")
            if isinstance(h, str) and h:
                return h
        return None

    def remove_session_from_presence_by_hash(self, h: str, sid: str) -> None:
        path = self.coord_dir / "presence" / f"{h}.json"
        with self._guard(f"presence-{h}") as ok:
            if not ok:
                return
            data = _read_json(path)
            if isinstance(data, dict):
                sessions = data.get("sessions")
                if isinstance(sessions, dict) and sid in sessions:
                    sessions.pop(sid, None)
                    data["sessions"] = sessions
                    _atomic_write_json(path, data)

    # -- tasks --------------------------------------------------------------

    def _task_path(self, task_id: str) -> Path:
        return self.coord_dir / "tasks" / f"{task_id}.json"

    def create_task(self, task: Task) -> Task:
        _atomic_write_json(self._task_path(task.task_id), task.to_dict())
        return task

    def load_task(self, task_id: str) -> Task | None:
        raw = _read_json(self._task_path(task_id))
        if not isinstance(raw, dict) or not raw.get("task_id"):
            return None
        return Task.from_dict(raw)

    def list_tasks(self, status: str | None = None) -> list[Task]:
        out: list[Task] = []
        try:
            paths = sorted((self.coord_dir / "tasks").glob("task_*.json"))
        except OSError:
            return out
        for p in paths:
            raw = _read_json(p)
            if not isinstance(raw, dict):
                continue
            t = Task.from_dict(raw)
            if status is None or t.status == status:
                out.append(t)
        return out

    def _save_task(self, task: Task) -> None:
        _atomic_write_json(self._task_path(task.task_id), task.to_dict())

    def claim_task(self, task_id: str, worker_id: str, base_commit: str) -> Task | None:
        """CAS 认领：并发下恰好一个成功；锁竞争超时 → None（守方重试）。"""
        with self._guard(f"task-{task_id}") as ok:
            if not ok:
                return None
            task = self.load_task(task_id)
            if task is None:
                return None
            claimed = _claim_task(task, worker_id, base_commit)
            if claimed is None:
                return None
            self._save_task(claimed)
            return claimed

    def task_transition(self, task_id: str, worker_id: str, action: str,
                        findings: list[dict] | None = None) -> Task | None:
        """状态转换统一入口：action ∈ review|resume|complete|reopen。"""
        with self._guard(f"task-{task_id}") as ok:
            if not ok:
                return None
            task = self.load_task(task_id)
            if task is None:
                return None
            if action == "review":
                nxt = _mark_pending_review(task, worker_id)
            elif action == "resume":
                nxt = _resume_task(task, worker_id)
            elif action == "complete":
                nxt = _complete_task(task, worker_id)
            elif action == "reopen":
                nxt = _reopen_task(task, worker_id, findings or [])
            else:
                return None
            if nxt is None:
                return None
            self._save_task(nxt)
            return nxt

    # -- 阶段 1：worker 上交 / reconciler 收敛 ------------------------------

    def _task_cas(self, task_id: str, fn) -> Task | None:
        """锁内 load → 纯函数转换 → save 的通用骨架。fn 返回 None 即拒绝。"""
        with self._guard(f"task-{task_id}") as ok:
            if not ok:
                return None
            task = self.load_task(task_id)
            if task is None:
                return None
            nxt = fn(task)
            if nxt is None:
                return None
            self._save_task(nxt)
            return nxt

    def submit_result(self, task_id: str, worker_id: str, branch: str) -> Task | None:
        """worker 上交：claimed → ready_to_merge，附 worktree 分支（仅持有者本人）。"""
        return self._task_cas(task_id, lambda t: _submit_result(t, worker_id, branch))

    def mark_merged(self, task_id: str) -> Task | None:
        """reconciler 收敛成功：ready_to_merge → merged。"""
        return self._task_cas(task_id, _mark_merged)

    def reopen_conflict(self, task_id: str, base_commit: str,
                        findings: list[dict]) -> Task | None:
        """三路合并真冲突打回：ready_to_merge → reopened(→blocked)，base_commit=最新 main head。"""
        return self._task_cas(task_id, lambda t: _reopen_conflict(t, base_commit, findings or []))

    def worker_failed(self, task_id: str, worker_id: str,
                      findings: list[dict]) -> Task | None:
        """worker 执行异常：claimed → reopened(→blocked)，可被重试。"""
        return self._task_cas(task_id, lambda t: _worker_failed(t, worker_id, findings or []))

    # -- scope leases -------------------------------------------------------

    def _scope_path(self, root: str | Path) -> Path:
        return self.coord_dir / "scope" / f"{root_hash(root)}.json"

    def active_leases(self, root: str | Path) -> list[ScopeLease]:
        raw = _read_json(self._scope_path(root))
        if not isinstance(raw, dict):
            return []
        leases = [ScopeLease.from_dict(d) for d in raw.get("leases", [])
                  if isinstance(d, dict)]
        return prune_leases(leases)

    def acquire_scope(self, root: str | Path, owner: str, paths: list[str],
                      ttl: float | None = None) -> ScopeLease | None:
        h = root_hash(root)
        with self._guard(f"scope-{h}") as ok:
            if not ok:
                return None
            current = self.active_leases(root)
            res = _acquire_scope(current, owner, paths) if ttl is None else \
                _acquire_scope(current, owner, paths, ttl=ttl)
            if res is None:
                return None
            leases, lease = res
            _atomic_write_json(self._scope_path(root),
                               {"leases": [l.to_dict() for l in leases]})
            return lease

    def release_scope(self, root: str | Path, lease_id: str, owner: str) -> bool:
        h = root_hash(root)
        with self._guard(f"scope-{h}") as ok:
            if not ok:
                return False
            current = self.active_leases(root)
            remain = _release_scope(current, lease_id, owner)
            _atomic_write_json(self._scope_path(root),
                               {"leases": [l.to_dict() for l in remain]})
            return len(remain) != len(current)

    # -- ask queue ----------------------------------------------------------

    def _asks_path(self, root: str | Path) -> Path:
        return self.coord_dir / "asks" / f"{root_hash(root)}.json"

    def put_ask(self, root: str | Path, worker_id: str, kind: str, payload: str) -> AskItem:
        item = _new_ask(str(root), worker_id, kind, payload)
        h = root_hash(root)
        with self._guard(f"asks-{h}") as ok:
            if not ok:
                return item  # 降级：仅返回对象，不持久化
            data = _read_json(self._asks_path(root))
            items = [AskItem.from_dict(d) for d in (data.get("asks") if isinstance(data, dict) else [])
                     if isinstance(d, dict)]
            items.append(item)
            items = items[-256:]
            _atomic_write_json(self._asks_path(root),
                               {"asks": [a.to_dict() for a in items]})
        return item

    def pending_asks(self, root: str | Path) -> list[AskItem]:
        data = _read_json(self._asks_path(root))
        items = [AskItem.from_dict(d) for d in (data.get("asks") if isinstance(data, dict) else [])
                 if isinstance(d, dict)]
        return [a for a in items if a.status == "pending"]

    def resolve_ask(self, root: str | Path, ask_id: str, choice: str) -> bool:
        h = root_hash(root)
        with self._guard(f"asks-{h}") as ok:
            if not ok:
                return False
            data = _read_json(self._asks_path(root))
            items = [AskItem.from_dict(d) for d in (data.get("asks") if isinstance(data, dict) else [])
                     if isinstance(d, dict)]
            hit = False
            for a in items:
                if a.ask_id == ask_id and a.status == "pending":
                    a.status = "resolved"
                    a.choice = str(choice or "")
                    a.resolved_at = time.time()
                    hit = True
            if hit:
                _atomic_write_json(self._asks_path(root),
                                   {"asks": [a.to_dict() for a in items]})
            return hit


__all__ = ["CoordFileStore", "root_hash"]
