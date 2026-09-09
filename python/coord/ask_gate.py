"""AskGate：人在环三选 ASK 的队列化 + 挂起释放租约（阶段 2，计划 §2/§3）。

核心机制（v1.1 §3 阶段 2 修订②）：worker 等待人裁决期间**必须主动释放
scope 租约并同步 presence**（busy=false、owned_files 清除），任务转
``PENDING_REVIEW``——否则一个 worker 卡在 ASK 上 10 分钟，同 scope 的其他
worker 全部堵死。

- ``suspend``：worker 触到需要人裁决的 ASK →
  释放其活动 scope 租约 → presence 清 busy/owned → task claimed→PENDING_REVIEW
  → put_ask 入队（关联 task_id + 释放的 lease_id 列表）。返回 None=降级/竞态失败。
- ``allow``：人裁决放行 → resolve_ask(allow) → task PENDING_REVIEW→claimed
  （仅原持有者，claimed_by 保留，他人不可抢）。**重新竞争租约 + 过 OCC 由
  编排层（worker 侧）负责**——gate 只管队列 + 状态 + 释放，不越权重取。
- ``deny`` / ``remind``：走收尾（reopen 打回，携带中性 findings）。
- ``sweep_expired``：无人值守超 TTL 的 pending ask → 标 expired + 任务转
  pending 挂起（``suspend_release``，可被重新认领），**非 deny 丢弃**——
  对应计划"超时转 pending 挂起而非 deny 丢弃"。

错误措辞一律中性事实（引擎铁律）。coord IO/锁失败只记 debug，不挡主路径。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from coord.file_store import CoordFileStore
from coord.store import ASK_STATUS_PENDING, ASK_TTL_SEC, AskItem

_log = logging.getLogger("xeyo.coord.ask")


class AskGate:
    """单 repo 的人在环 ASK 网关。无共享可变状态；presence 可注入（默延迟取全局）。"""

    def __init__(self, repo: str | Path, store: CoordFileStore, *,
                 presence=None, ttl: float = ASK_TTL_SEC) -> None:
        self.repo = Path(repo).resolve()
        self.store = store
        self._presence = presence
        self.ttl = float(ttl)

    @property
    def presence(self):
        if self._presence is None:
            from engine.session_presence import default_session_presence

            self._presence = default_session_presence()
        return self._presence

    # -- 挂起 ---------------------------------------------------------------

    def suspend(self, *, root: str, task_id: str, worker_id: str,
                kind: str, payload: str) -> AskItem | None:
        """worker 卡在需人裁决的 ASK：释放租约 + 清 presence + 转 PENDING_REVIEW + 入队。"""
        # 1. 先转状态（claimed→PENDING_REVIEW，仅持有者）；失败=竞态/非本人，不动租约。
        nxt = self.store.task_transition(task_id, worker_id, "review")
        if nxt is None:
            return None
        # 2. 释放本任务的 scope 路径（挂起期间不占坑；同 owner 其他任务路径不动）。
        released: list[str] = []
        try:
            task = self.store.load_task(task_id)
            if task is not None:
                n = self.store.release_task_scope(root, worker_id, task.scope)
                if n:
                    released.append(f"paths={n}")
        except Exception:  # noqa: BLE001
            _log.debug("ask suspend release_scope failed", exc_info=True)
        # 3. presence 同步：busy=false + 清除持有文件（同 scope worker 立即解堵）。
        try:
            self.presence.touch_busy(root, worker_id, busy=False)
            self.presence.clear_owned(root, worker_id)
        except Exception:  # noqa: BLE001
            _log.debug("ask suspend presence clear failed", exc_info=True)
        # 4. 入队（关联 task + 已释放租约，供审计与恢复）。
        item = self.store.put_ask(root, worker_id, kind, payload,
                                  task_id=task_id, lease_id=",".join(released))
        return item

    # -- 裁决 ---------------------------------------------------------------

    def allow(self, *, root: str, ask_id: str, worker_id: str,
              task_id: str = "") -> bool:
        """放行：原 worker 恢复 claimed，成功才落 resolve。重新竞争租约由编排层做。"""
        a = self._ask_by_id(root, ask_id)
        tid = task_id or (a.task_id if a else "")
        if not tid:
            return False
        nxt = self.store.task_transition(tid, worker_id, "resume")  # 校验 claimed_by
        if nxt is None:
            return False
        self.store.resolve_ask(root, ask_id, "allow")
        return True

    def deny(self, *, root: str, ask_id: str, worker_id: str,
             findings: list[dict] | None = None) -> bool:
        """拒绝：原持有者任务 reopen 打回（携带中性 findings），成功才落 resolve。"""
        a = self._ask_by_id(root, ask_id)
        if not a or not a.task_id:
            return False
        nxt = self.store.task_transition(a.task_id, worker_id, "review_reopen",
                                         findings=findings or [
                                             {"file": "", "line": 0,
                                              "error": "ask_denied"}])
        if nxt is None:
            return False
        self.store.resolve_ask(root, ask_id, "deny")
        return nxt is not None

    def remind(self, *, root: str, ask_id: str, worker_id: str,
               findings: list[dict] | None = None) -> bool:
        """提醒后继续：resolve(remind) + reopen（原 worker 重做，语义同 deny 收尾）。"""
        a = self._ask_by_id(root, ask_id)
        if not a or not a.task_id:
            return False
        nxt = self.store.task_transition(a.task_id, worker_id, "review_reopen",
                                         findings=findings or [
                                             {"file": "", "line": 0,
                                              "error": "ask_remind"}])
        if nxt is None:
            return False
        self.store.resolve_ask(root, ask_id, "remind")
        return True

    # -- 超时清扫 -----------------------------------------------------------

    def sweep_expired(self, *, root: str, now: float | None = None) -> dict:
        """扫 pending ask 超 TTL → expired + 任务转 pending 挂起（非 deny 丢弃）。"""
        ts = time.time() if now is None else float(now)
        report = {"expired": [], "released": []}
        for ask in self.store.pending_asks(root):
            if ask.status != ASK_STATUS_PENDING:
                continue
            if ts - ask.created_at < self.ttl:
                continue
            if self.store.expire_ask(root, ask.ask_id):
                report["expired"].append(ask.ask_id)
            if ask.task_id and ask.worker_id:
                nxt = self.store.task_transition(ask.task_id, ask.worker_id, "suspend")
                if nxt is not None:
                    report["released"].append(ask.task_id)
        return report

    # -- helpers ------------------------------------------------------------

    def _ask_by_id(self, root: str, ask_id: str) -> AskItem | None:
        data = self.store.load_asks(root)
        for a in data:
            if a.ask_id == ask_id:
                return a
        return None


__all__ = ["AskGate"]
