"""确定性多 Agent 调度器（非 LLM）。

DAG 事件驱动：依赖就绪且与运行中任务无文件 scope 冲突即可启动；
同文件串行、不同文件并行；独立信号量（不与 orchestration 共享）。
超时 wait_for + AbortController；checkpoint 按 session 落盘。
批次内工具白名单：按任务裁剪（空 scope 无写工具）；batch_tool_whitelist 取交集作缓存提示。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.abort import AbortController
from engine.write_store import WriteStore
from tools.meta import FORBIDDEN_SUB_TOOLS, SUBSET_TOOL_BASELINE, WRITE_PATH_TOOLS

MAX_PATCH_RETRIES = 3
MAX_DECOMPOSE_TASKS = 8
_MIN_TIMEOUT_S = 0.05


@dataclass
class TaskRunResult:
    """单次子 agent 执行结果（含 stale 信号，供 Patch 重试）。"""
    ok: bool
    reason: str = "ok"
    had_write_stale: bool = False


@dataclass
class Task:
    """一个多 Agent 子任务（调度单元）。"""
    id: str
    desc: str
    depends_on: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    timeout_s: float = 300.0
    status: str = "pending"
    agent_id: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    last_result: str = ""
    failure_reason: str = ""
    memories: list[dict[str, Any]] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "desc": self.desc, "depends_on": list(self.depends_on),
            "scope": list(self.scope), "required_tools": list(self.required_tools),
            "timeout_s": float(self.timeout_s), "status": self.status,
            "agent_id": self.agent_id, "started_at": float(self.started_at),
            "finished_at": float(self.finished_at), "last_result": str(self.last_result),
            "failure_reason": str(self.failure_reason),
            "memories": list(self.memories),
            "files_touched": list(self.files_touched),
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Task":
        try:
            timeout = float(raw.get("timeout_s") or 300)
        except (TypeError, ValueError):
            timeout = 300.0
        return Task(
            id=str(raw.get("id") or ""), desc=str(raw.get("desc") or ""),
            depends_on=[str(x) for x in raw.get("depends_on") or []
                        if isinstance(x, str)],
            scope=[str(x) for x in raw.get("scope") or [] if isinstance(x, str)],
            required_tools=[str(x) for x in raw.get("required_tools") or []
                            if isinstance(x, str)],
            timeout_s=max(_MIN_TIMEOUT_S, timeout),
            status=str(raw.get("status") or "pending"),
            agent_id=str(raw.get("agent_id") or ""),
            started_at=float(raw.get("started_at") or 0.0),
            finished_at=float(raw.get("finished_at") or 0.0),
            last_result=str(raw.get("last_result") or ""),
            failure_reason=str(raw.get("failure_reason") or ""),
            memories=[
                x for x in raw.get("memories") or [] if isinstance(x, dict)
            ],
            files_touched=[
                str(x) for x in raw.get("files_touched") or [] if isinstance(x, str)
            ],
        )


def _norm_scope_path(path: str, root: str | Path | None = None) -> str:
    """相对工作区归一：反斜杠→/、小写、剥 ./ 与绝对根前缀。"""
    p = (path or "").replace("\\", "/").strip().lower()
    if not p:
        return ""
    while p.startswith("./"):
        p = p[2:]
    if root is not None:
        root_s = str(Path(root).expanduser().resolve()).replace("\\", "/").strip().lower()
        if root_s and (p == root_s or p.startswith(root_s + "/")):
            p = p[len(root_s):].lstrip("/")
    return p


def toposort(tasks: list[Task]) -> list[Task]:
    """DAG 拓扑排序；环或缺失依赖返回空。"""
    by_id = {t.id: t for t in tasks}
    indeg = {t.id: 0 for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep in by_id:
                indeg[t.id] += 1
            else:
                return []
    ready = [t for t in tasks if indeg[t.id] == 0]
    out: list[Task] = []
    while ready:
        t = ready.pop(0)
        out.append(t)
        for other in tasks:
            if t.id in other.depends_on:
                indeg[other.id] -= 1
                if indeg[other.id] == 0:
                    ready.append(other)
    if len(out) != len(tasks):
        return []
    return out


def scope_conflicts(
    a: Task,
    b: Task,
    *,
    root: str | Path | None = None,
) -> bool:
    """文件级写范围冲突。

    - 任一方未声明 scope（空）→ 视为冲突（保守串行，避免未知写并行）。
    - 两边都有 scope：归一路径后有交集才冲突。
    """
    left = {_norm_scope_path(p, root) for p in a.scope if p}
    right = {_norm_scope_path(p, root) for p in b.scope if p}
    left.discard("")
    right.discard("")
    if not left or not right:
        return True
    return bool(left & right)


def _break_cycles(tasks: list[Task]) -> None:
    """只删回边破环；破不了才清空全部 depends_on。"""
    by_id = {t.id: t for t in tasks}
    safety = max(1, len(tasks) * len(tasks) + 1)
    while safety > 0 and not toposort(tasks):
        safety -= 1
        color = {t.id: 0 for t in tasks}
        cycle_edge: tuple[str, str] | None = None

        def dfs(u: str) -> bool:
            nonlocal cycle_edge
            color[u] = 1
            node = by_id[u]
            for v in node.depends_on:
                if v not in by_id:
                    continue
                if color[v] == 1:
                    cycle_edge = (u, v)
                    return True
                if color[v] == 0 and dfs(v):
                    return True
            color[u] = 2
            return False

        found = False
        for t in tasks:
            if color[t.id] == 0 and dfs(t.id):
                found = True
                break
        if not found or cycle_edge is None:
            for t in tasks:
                t.depends_on = []
            return
        u, v = cycle_edge
        by_id[u].depends_on = [d for d in by_id[u].depends_on if d != v]


def build_tool_whitelist(task: Task) -> list[str]:
    """按任务构建子 agent 工具白名单：基线 + required_tools，剔除禁止项。

    空 scope → 剔除全部 write_path 工具（Write/Edit/NotebookEdit…），只读工人硬门禁。
    """
    allow = set(SUBSET_TOOL_BASELINE) | set(task.required_tools)
    if not (task.scope or []):
        allow -= WRITE_PATH_TOOLS
    return sorted(n for n in allow if n not in FORBIDDEN_SUB_TOOLS)


def batch_tool_whitelist(tasks: list[Task]) -> list[str]:
    """批次共用白名单候选（A3 缓存提示）：取各任务 whitelist 的交集。

    空 scope 任务不含写工具；与可写任务混批时交集亦无写工具，避免只读工人看见 Write。
    无任务时回退基线（仍剔禁止项）。
    """
    if not tasks:
        return sorted(n for n in SUBSET_TOOL_BASELINE if n not in FORBIDDEN_SUB_TOOLS)
    sets = [set(build_tool_whitelist(t)) for t in tasks]
    shared = sets[0].intersection(*sets[1:]) if len(sets) > 1 else sets[0]
    return sorted(shared)


def repair_task_graph(
    tasks: list[Task],
    *,
    max_tasks: int = MAX_DECOMPOSE_TASKS,
) -> list[Task]:
    """把分解结果修成可调度图：去重 id、丢掉非法边/工具、破环、截断。"""
    cleaned: list[Task] = []
    seen: set[str] = set()
    for i, t in enumerate(tasks):
        tid = (t.id or "").strip() or f"t{i}"
        if tid in seen:
            tid = f"{tid}_{i}"
        seen.add(tid)
        t.id = tid
        t.required_tools = [
            n for n in (t.required_tools or []) if n not in FORBIDDEN_SUB_TOOLS
        ]
        cleaned.append(t)
    if len(cleaned) > max_tasks:
        cleaned = cleaned[:max_tasks]
    ids = {t.id for t in cleaned}
    for t in cleaned:
        t.depends_on = [d for d in t.depends_on if d in ids and d != t.id]
    if not toposort(cleaned):
        _break_cycles(cleaned)
    return cleaned


def turns_for_timeout(timeout_s: float) -> tuple[int, int]:
    """由超时推导子 agent max_turns / max_tool_calling（约 25s/轮，夹在 4–24）。"""
    turns = max(4, min(24, int(float(timeout_s) // 25) or 4))
    return turns, turns


class Scheduler:
    """确定性调度器（事件驱动 DAG + 文件级冲突 + 并发上限 + 超时 + 按 session checkpoint）。"""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        max_concurrency: int = 10,
        timeout_s: float = 300,
        write_store: WriteStore | None = None,
        runtime_provider: Any | None = None,
        main_session_id: str = "",
        agent_ids: dict[str, str] | None = None,
        progress_sink: Any | None = None,
        task_batch_id: str = "",
        ui_uids: dict[str, str] | None = None,
        user_goal: str = "",
        abort: AbortController | None = None,
        read_state: Any | None = None,
    ) -> None:
        self._root = Path(workspace_root).expanduser().resolve()
        self._max_concurrency = max(1, max_concurrency)
        self._default_timeout = max(_MIN_TIMEOUT_S, float(timeout_s))
        self._write_store = write_store or WriteStore(self._root)
        self._runtime_provider = runtime_provider
        self._main_session_id = main_session_id
        self._agent_ids = dict(agent_ids or {})
        self._progress_sink = progress_sink
        self._task_batch_id = (task_batch_id or "").strip()
        self._ui_uids = dict(ui_uids or {})
        self._user_goal = (user_goal or "").strip()
        self._batch_abort = abort
        # 与主会话同册（None = 自建，见 catalog.shared_read_state）。
        self._read_state = read_state
        self._tasks: dict[str, Task] = {}
        self._order: list[Task] = []
        self._original_desc: dict[str, str] = {}
        self._frozen_whitelist: list[str] = []
        self._task_aborts: dict[str, AbortController] = {}

    def _emit(self, payload: dict[str, Any]) -> None:
        cb = getattr(self, "_progress_sink", None)
        if not callable(cb):
            return
        try:
            cb(payload)
        except Exception:  # noqa: BLE001
            pass

    def abort_all(self) -> None:
        """Stop 信号：中止批次与所有运行中子 agent。"""
        if self._batch_abort is not None:
            self._batch_abort.abort()
        for ac in list(self._task_aborts.values()):
            ac.abort()

    def _batch_aborted(self) -> bool:
        ac = self._batch_abort
        return bool(ac is not None and getattr(ac, "aborted", False))

    def load(self, tasks: list[Task]) -> "Scheduler":
        ordering = toposort(tasks)
        if not ordering:
            raise ValueError("task graph invalid (cycle or missing dependency)")
        self._tasks = {t.id: t for t in tasks}
        self._order = ordering
        self._original_desc = {t.id: t.desc for t in tasks}
        self._frozen_whitelist = batch_tool_whitelist(tasks)
        return self

    def validate(self, tasks: list[Task]) -> list[str]:
        errors: list[str] = []
        by_id = {t.id for t in tasks}
        for t in tasks:
            for dep in t.depends_on:
                if dep not in by_id:
                    errors.append(f"task {t.id}: missing dep {dep}")
            for tool in t.required_tools:
                if tool in FORBIDDEN_SUB_TOOLS:
                    errors.append(f"task {t.id}: forbidden tool {tool}")
        if not toposort(tasks):
            errors.append("task graph has a cycle")
        return errors

    def _skip_failed_deps(self, failed_ids: set[str], settled_ids: set[str]) -> None:
        progressed = True
        while progressed:
            progressed = False
            for t in self._order:
                if t.status != "pending":
                    continue
                if not any(dep in failed_ids for dep in t.depends_on):
                    continue
                self._skip_dependency_failed(t)
                failed_ids.add(t.id)
                settled_ids.add(t.id)
                progressed = True

    def _can_start(self, t: Task, settled_ids: set[str], running: list[Task]) -> bool:
        if t.status != "pending":
            return False
        if not all(dep in settled_ids for dep in t.depends_on):
            return False
        for other in running:
            if scope_conflicts(t, other, root=self._root):
                return False
        return True

    async def run(self) -> None:
        """事件驱动 DAG：任务一落定立刻启动新就绪工作；同文件不并行。"""
        failed_ids: set[str] = {t.id for t in self._order if t.status == "failed"}
        settled_ids: set[str] = {
            t.id for t in self._order if t.status in ("done", "failed")
        }
        running: dict[str, asyncio.Task[None]] = {}
        inflight: dict[str, Task] = {}

        try:
            while True:
                if self._batch_aborted():
                    await self._cancel_running(running, inflight)
                    self._mark_pending_interrupted()
                    break

                self._skip_failed_deps(failed_ids, settled_ids)

                slots = self._max_concurrency - len(running)
                for t in self._order:
                    if slots <= 0:
                        break
                    if not self._can_start(t, settled_ids, list(inflight.values())):
                        continue
                    running[t.id] = asyncio.create_task(
                        self._dispatch(t), name=f"sched-{t.id}"
                    )
                    inflight[t.id] = t
                    slots -= 1

                if not running:
                    break

                abort_watcher = asyncio.create_task(self._watch_batch_abort())
                wait_set = set(running.values()) | {abort_watcher}
                done, _ = await asyncio.wait(
                    wait_set, return_when=asyncio.FIRST_COMPLETED
                )
                abort_hit = abort_watcher in done or self._batch_aborted()
                abort_watcher.cancel()
                try:
                    await abort_watcher
                except asyncio.CancelledError:
                    pass
                if abort_hit:
                    await self._cancel_running(running, inflight)
                    self._mark_pending_interrupted()
                    break
                for fut in done:
                    tid = next((k for k, v in running.items() if v is fut), "")
                    running.pop(tid, None)
                    task_obj = inflight.pop(tid, None)
                    try:
                        await fut
                    except asyncio.CancelledError:
                        if task_obj is not None and task_obj.status == "running":
                            task_obj.status = "pending"
                            task_obj.failure_reason = "interrupted"
                            self._persist()
                        if self._batch_aborted():
                            await self._cancel_running(running, inflight)
                            self._mark_pending_interrupted()
                            return
                        raise
                    if task_obj is not None:
                        settled_ids.add(task_obj.id)
                        if task_obj.status == "failed":
                            failed_ids.add(task_obj.id)
        except asyncio.CancelledError:
            self.abort_all()
            await self._cancel_running(running, inflight)
            self._mark_pending_interrupted()
            raise

    async def _watch_batch_abort(self) -> None:
        while not self._batch_aborted():
            await asyncio.sleep(0.05)

    async def _cancel_running(
        self,
        running: dict[str, asyncio.Task[None]],
        inflight: dict[str, Task],
    ) -> None:
        self.abort_all()
        for fut in running.values():
            fut.cancel()
        if running:
            await asyncio.gather(*running.values(), return_exceptions=True)
        for tid, t in list(inflight.items()):
            if t.status == "running":
                t.status = "pending"
                t.failure_reason = "interrupted"
        inflight.clear()
        running.clear()
        self._persist()

    def _mark_pending_interrupted(self) -> None:
        for t in self._order:
            if t.status == "running":
                t.status = "pending"
                t.failure_reason = "interrupted"
        self._persist()

    def _skip_dependency_failed(self, t: Task) -> None:
        self._finalize(t, ok=False, reason="dependency_failed")
        self._emit({
            "kind": "sched",
            "type": "task_finished",
            "task_id": t.id,
            "status": "failed",
            "reason": "dependency_failed",
            "result": "",
        })

    def _resolved_agent_id(self, t: Task) -> str:
        return self._agent_ids.get(t.id) or t.agent_id or f"agent-{t.id}"

    async def _dispatch(self, t: Task) -> None:
        agent_id_resolved = self._resolved_agent_id(t)
        abort = AbortController()
        self._task_aborts[t.id] = abort
        if self._batch_aborted():
            abort.abort()
        final_status = "failed"
        final_reason = ""
        stale_flag = False
        attempt = 0
        timeout = max(_MIN_TIMEOUT_S, float(t.timeout_s or self._default_timeout))

        try:
            for attempt in range(MAX_PATCH_RETRIES + 1):
                if abort.aborted or self._batch_aborted():
                    t.status = "pending"
                    t.failure_reason = "interrupted"
                    self._persist()
                    raise asyncio.CancelledError()

                t.status = "running"
                if attempt == 0:
                    t.started_at = time.time()
                    self._persist()
                    self._emit({
                        "kind": "sched",
                        "type": "task_started",
                        "task_id": t.id,
                        "status": "running",
                        "reason": "",
                        "result": "",
                        "desc": str(t.desc or "")[:120],
                    })
                else:
                    try:
                        from usage.multi_agent_metrics import record_patch_retry

                        record_patch_retry(
                            task_batch_id=self._task_batch_id,
                            session_id=self._main_session_id,
                            task_id=t.id,
                            agent_id=agent_id_resolved,
                            attempt=attempt,
                        )
                    except Exception:  # noqa: BLE001
                        logging.getLogger(__name__).debug(
                            "patch retry metric failed", exc_info=True
                        )

                run_fut = asyncio.create_task(
                    self._run_task(t, patch_attempt=attempt, abort=abort)
                )
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(run_fut), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    # 先 abort 再给子 agent 短暂收尾，避免仅 cancel 协程而 AbortController 未置位。
                    abort.abort()
                    try:
                        await asyncio.wait_for(run_fut, timeout=2.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        run_fut.cancel()
                        try:
                            await run_fut
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
                    self._finalize(t, ok=False, reason="timeout")
                    final_status = "failed"
                    final_reason = "timeout"
                    break
                except asyncio.CancelledError:
                    abort.abort()
                    if not run_fut.done():
                        run_fut.cancel()
                        try:
                            await run_fut
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
                    if t.status == "running":
                        t.status = "pending"
                        t.failure_reason = "interrupted"
                        self._persist()
                    raise
                except Exception as e:  # noqa: BLE001
                    from common.errors import friendly_error

                    if not run_fut.done():
                        abort.abort()
                        run_fut.cancel()
                        try:
                            await run_fut
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
                    self._finalize(t, ok=False, reason=friendly_error(e)[:160])
                    final_status = "failed"
                    final_reason = t.failure_reason
                    break

                stale_flag = stale_flag or result.had_write_stale

                if result.reason == "interrupted":
                    t.status = "pending"
                    t.failure_reason = "interrupted"
                    self._persist()
                    raise asyncio.CancelledError()

                if result.ok:
                    self._finalize(t, ok=True, reason="ok")
                    final_status = "done"
                    final_reason = ""
                    break

                if not result.had_write_stale or attempt >= MAX_PATCH_RETRIES:
                    reason = result.reason
                    if result.had_write_stale and attempt >= MAX_PATCH_RETRIES:
                        reason = "stale_exhausted"
                    self._finalize(t, ok=False, reason=reason)
                    final_status = "failed"
                    final_reason = reason
                    break

                t.desc = self._build_patch_desc(t.id, attempt + 1)
        finally:
            self._task_aborts.pop(t.id, None)

        if t.status not in ("done", "failed") and t.failure_reason == "interrupted":
            return

        self._emit({
            "kind": "sched",
            "type": "task_finished",
            "task_id": t.id,
            "status": str(t.status),
            "reason": str(t.failure_reason or final_reason or "")[:160],
            "result": str(t.last_result or "")[:800],
        })
        if t.status not in ("done", "failed"):
            return
        try:
            from usage.multi_agent_metrics import record_task_finished

            record_task_finished(
                task_batch_id=self._task_batch_id,
                session_id=self._main_session_id,
                task_id=t.id,
                agent_id=agent_id_resolved,
                status=t.status if t.status in ("done", "failed") else final_status,
                reason=t.failure_reason or final_reason,
                paths=list(t.scope or []),
                patch_attempt=attempt,
                had_write_stale=stale_flag,
            )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).debug(
                "task finished metric failed", exc_info=True
            )

    async def _run_task(
        self,
        t: Task,
        *,
        patch_attempt: int = 0,
        abort: AbortController | None = None,
    ) -> TaskRunResult:
        from engine.subagent_runner import run_subagent

        if abort is not None and abort.aborted:
            return TaskRunResult(ok=False, reason="interrupted")
        runtime = self._runtime_provider() if callable(self._runtime_provider) else None
        if runtime is None:
            t.failure_reason = "runtime_not_configured"
            return TaskRunResult(ok=False, reason="runtime_not_configured")
        agent_id_resolved = self._resolved_agent_id(t)
        recent = self._recent_changes_text(t)
        prompt = self._task_prompt_with_upstream(t)
        max_turns, max_tools = turns_for_timeout(t.timeout_s or self._default_timeout)

        def _push_delta(chunk_text: str) -> None:
            self._emit({
                "kind": "subagent_text",
                "task_id": t.id,
                "agent_id": agent_id_resolved,
                "text": chunk_text,
            })

        rr = await run_subagent(
            workspace_root=self._root,
            agent_id=agent_id_resolved,
            task_prompt=prompt,
            tool_whitelist=self.whitelist_for(t),
            model_client=runtime.model_client,
            prompt_assembler=runtime.prompt_assembler,
            write_store=self._write_store,
            main_session_id=self._main_session_id or t.id,
            append_system_prompt=runtime.append_system_prompt,
            date_iso=runtime.date_iso,
            recent_changes=recent,
            abort=abort,
            max_turns=max_turns,
            max_tool_calling=max_tools,
            on_text_delta=_push_delta if callable(self._progress_sink) else None,
            task_batch_id=self._task_batch_id,
            session_id=self._main_session_id,
            task_id=t.id,
            write_scope_paths=list(t.scope or []),
            read_state=self._read_state,
        )
        t.last_result = rr.conclusion
        t.memories = [m for m in (rr.memories or []) if isinstance(m, dict)]
        t.files_touched = list(rr.files_touched or [])
        had_stale = bool(rr.had_write_stale)
        if rr.is_error:
            from common.errors import sanitize_user_facing_text

            fail_reason = sanitize_user_facing_text(rr.conclusion) or sanitize_user_facing_text(
                rr.stop_reason or "subagent_error"
            ) or (rr.stop_reason or "subagent_error")
            if had_stale:
                fail_reason = "stale"
            if (rr.stop_reason or "") == "aborted" or fail_reason == "interrupted":
                fail_reason = "interrupted"
            return TaskRunResult(ok=False, reason=fail_reason, had_write_stale=had_stale)
        return TaskRunResult(ok=True, reason="ok", had_write_stale=had_stale)

    def _task_prompt_with_upstream(self, t: Task) -> str:
        """depends_on 数据面：把已完成上游结论注入下游 prompt。"""
        bits: list[str] = []
        for dep in t.depends_on:
            u = self._tasks.get(dep)
            if u is None or u.status != "done":
                continue
            body = (u.last_result or "").strip()
            if not body:
                continue
            if len(body) > 1500:
                body = body[:1500].rstrip() + "…"
            bits.append(
                f"### Upstream [{u.id}] {(u.desc or '')[:80]}\n{body}"
            )
        if not bits:
            return t.desc
        return (
            f"{t.desc}\n\n"
            "## Context from completed dependencies\n"
            + "\n\n".join(bits)
        )

    def _recent_changes_text(self, t: Task) -> str:
        from memory import journal
        from memory.memdir import workspace_id

        try:
            wsid = workspace_id(str(self._root))
        except Exception:  # noqa: BLE001
            wsid = self._root.name or "ws"
        prefix = t.scope[0] if t.scope else None
        rows = journal.recent_changes(
            wsid,
            path_prefix=prefix,
            workspace_root=str(self._root),
            limit=10,
        )
        return journal.format_changes_for_agent(rows)

    def _inject_resume_hint(self, t: Task) -> None:
        original = self._original_desc.get(t.id, t.desc)
        if str(t.desc or "").startswith("[Resume]"):
            return
        # 仅标记中断；是否重复工具由侧链历史约束，不在此堆砌禁令。
        t.desc = f"[Resume] You were interrupted.\n\n{original}"

    def _build_patch_desc(self, task_id: str, attempt: int) -> str:
        original = self._original_desc.get(task_id, "")
        t = self._tasks.get(task_id)
        paths = list((t.files_touched if t else []) or (t.scope if t else []) or [])
        # B5 裁决：只留 retry 计数与"哪些文件已被改动"的事实；重试动作由模型自决。
        fact = ""
        if paths:
            fact = (
                "Files modified since dispatch: "
                f"{', '.join(paths[:12])}\n\n"
            )
        return (
            f"[Patch retry {attempt}/{MAX_PATCH_RETRIES}] "
            f"{fact}"
            f"{original}"
        )

    def sweep_timeouts(self, now: float | None = None) -> list[str]:
        """后台巡检：超时任务 abort + 标失败。run() 已用 wait_for；此法作补扫描。"""
        now = now or time.time()
        timed_out: list[str] = []
        for t in self._tasks.values():
            limit = max(_MIN_TIMEOUT_S, float(t.timeout_s or self._default_timeout))
            if t.status == "running" and t.started_at and (now - t.started_at) > limit:
                ac = self._task_aborts.get(t.id)
                if ac is not None:
                    ac.abort()
                t.status = "failed"
                t.failure_reason = "timeout"
                timed_out.append(t.id)
        if timed_out:
            self._persist()
        return timed_out

    def _state_path(self) -> Path:
        return scheduler_state_path(self._root, self._main_session_id)

    def _persist(self) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        pending_n = sum(1 for t in self._tasks.values() if t.status == "pending")
        running_n = sum(1 for t in self._tasks.values() if t.status == "running")
        if self.all_succeeded():
            batch_status = "awaiting_synthesis"
        elif pending_n or running_n:
            batch_status = "incomplete"
        else:
            batch_status = "settled"
        payload = {
            "version": 2,
            "tasks": [t.to_dict() for t in self._tasks.values()],
            "agent_ids": dict(self._agent_ids),
            "ui_uids": dict(self._ui_uids),
            "original_desc": dict(self._original_desc),
            "parent_session_id": self._main_session_id,
            "task_batch_id": self._task_batch_id,
            "user_goal": self._user_goal,
            "cleanup_ttl": 7 * 24 * 3600,
            "written_at": round(time.time(), 3),
            "batch_status": batch_status,
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        if self._user_goal:
            write_last_user_goal(self._root, self._user_goal, self._main_session_id)


    def load_state(self) -> bool:
        raw = read_scheduler_checkpoint(self._root, self._main_session_id)
        if not raw:
            return False
        tasks = [Task.from_dict(x) for x in raw.get("tasks") or [] if isinstance(x, dict)]
        tasks = [t for t in tasks if t.id]
        if not tasks:
            return False
        ordering = toposort(tasks)
        if not ordering:
            return False
        self._tasks = {t.id: t for t in tasks}
        self._order = ordering
        self._frozen_whitelist = batch_tool_whitelist(tasks)
        agents = raw.get("agent_ids") or {}
        if isinstance(agents, dict):
            self._agent_ids = {str(k): str(v) for k, v in agents.items()}
        uids = raw.get("ui_uids") or {}
        if isinstance(uids, dict):
            self._ui_uids = {str(k): str(v) for k, v in uids.items()}
        original = raw.get("original_desc") or {}
        if isinstance(original, dict):
            self._original_desc = {str(k): str(v) for k, v in original.items()}
        else:
            self._original_desc = {t.id: t.desc for t in tasks}
        sid = str(raw.get("parent_session_id") or "").strip()
        if sid:
            self._main_session_id = sid
        bid = str(raw.get("task_batch_id") or "").strip()
        if bid:
            self._task_batch_id = bid
        goal = str(raw.get("user_goal") or "").strip()
        if goal:
            self._user_goal = goal
        for t in self._tasks.values():
            if not t.agent_id and t.id in self._agent_ids:
                t.agent_id = self._agent_ids[t.id]
        return True

    def prepare_for_resume(self) -> list[Task]:
        """续跑：running / interrupted pending / 可重试 failed → pending，并注入重读提示。"""
        retryable = frozenset({
            "interrupted", "timeout", "stale", "stale_exhausted",
        })
        for t in self._tasks.values():
            if t.status == "running":
                t.status = "pending"
                t.started_at = 0.0
                t.failure_reason = "interrupted"
                self._inject_resume_hint(t)
            elif t.status == "pending" and t.failure_reason == "interrupted":
                self._inject_resume_hint(t)
            elif t.status == "failed" and (t.failure_reason or "") in retryable:
                t.status = "pending"
                t.started_at = 0.0
                t.finished_at = 0.0
                t.failure_reason = ""
                self._inject_resume_hint(t)
        self._persist()
        return [t for t in self._order if t.status == "pending"]


    def all_succeeded(self) -> bool:
        """全部成功才清 checkpoint；有失败则保留以便 Continue 重试。"""
        return bool(self._tasks) and all(t.status == "done" for t in self._tasks.values())


    def whitelist_for(self, task: Task) -> list[str]:
        # 按任务裁剪：空 scope 工人绝不能因批次冻结表看见写工具。
        return build_tool_whitelist(task)

    def registry_for(self, task: Task) -> Any:
        from tools.catalog import build_subagent_registry

        return build_subagent_registry(
            cwd=str(self._root),
            tool_names=self.whitelist_for(task),
            read_state=self._read_state,
            write_store=self._write_store,
            agent_id=self._resolved_agent_id(task),
        )

    def _finalize(self, t: Task, *, ok: bool, reason: str) -> None:
        t.status = "done" if ok else "failed"
        t.finished_at = time.time()
        t.failure_reason = reason if not ok else ""
        self._persist()


def _safe_session_id(session_id: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in "._-" else "_" for ch in (session_id or "")
    ).strip("._") or ""


def scheduler_state_path(
    workspace_root: str | Path, session_id: str = ""
) -> Path:
    root = Path(workspace_root).expanduser().resolve() / ".xeyo"
    sid = _safe_session_id(session_id)
    if sid:
        return root / "scheduler" / f"{sid}.json"
    return root / "scheduler_state.json"


def _legacy_state_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve() / ".xeyo" / "scheduler_state.json"


def read_scheduler_checkpoint(
    workspace_root: str | Path, session_id: str = ""
) -> dict[str, Any] | None:
    """读该 session 的 checkpoint；兼容旧的 workspace 级单文件。"""
    path = scheduler_state_path(workspace_root, session_id)
    raw = _read_json_obj(path)
    if raw:
        if session_id:
            parent = str(raw.get("parent_session_id") or "").strip()
            if parent and parent != session_id:
                raw = None
            else:
                return raw
        else:
            return raw
    if not session_id:
        return None
    legacy = _read_json_obj(_legacy_state_path(workspace_root))
    if not legacy:
        return None
    parent = str(legacy.get("parent_session_id") or "").strip()
    if parent and parent != session_id:
        return None
    return legacy


def _read_json_obj(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def checkpoint_is_incomplete(raw: dict[str, Any] | None) -> bool:
    """可续跑：有未完成任务，或子任务已齐、尚待主会话合成。"""
    if not raw:
        return False
    if str(raw.get("batch_status") or "") == "awaiting_synthesis":
        return True
    tasks = raw.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        return False
    return any(
        isinstance(t, dict) and str(t.get("status") or "") != "done"
        for t in tasks
    )


def checkpoint_awaiting_synthesis(raw: dict[str, Any] | None) -> bool:
    """子任务已全部成功，只差主回复合成。"""
    if not raw:
        return False
    if str(raw.get("batch_status") or "") == "awaiting_synthesis":
        return True
    tasks = [t for t in (raw.get("tasks") or []) if isinstance(t, dict)]
    if not tasks:
        return False
    return all(str(t.get("status") or "") == "done" for t in tasks)


def clear_scheduler_checkpoint(
    workspace_root: str | Path, session_id: str = ""
) -> None:
    path = scheduler_state_path(workspace_root, session_id)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
    if session_id:
        legacy = _legacy_state_path(workspace_root)
        raw = _read_json_obj(legacy)
        parent = str((raw or {}).get("parent_session_id") or "").strip()
        if raw and (not parent or parent == session_id):
            try:
                if legacy.is_file():
                    legacy.unlink()
            except OSError:
                pass


def last_user_goal_path(
    workspace_root: str | Path, session_id: str = ""
) -> Path:
    root = Path(workspace_root).expanduser().resolve() / ".xeyo"
    sid = _safe_session_id(session_id)
    if sid:
        return root / "scheduler" / f"{sid}.goal.txt"
    return root / "last_multi_agent_goal.txt"


def write_last_user_goal(
    workspace_root: str | Path, goal: str, session_id: str = ""
) -> None:
    text = (goal or "").strip()
    if not text:
        return
    path = last_user_goal_path(workspace_root, session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass




def checkpoint_summary(raw: dict[str, Any]) -> dict[str, Any]:
    tasks = [t for t in (raw.get("tasks") or []) if isinstance(t, dict)]
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for t in tasks:
        st = str(t.get("status") or "pending")
        if st not in counts:
            st = "pending"
        counts[st] += 1
    return {
        "task_batch_id": str(raw.get("task_batch_id") or ""),
        "parent_session_id": str(raw.get("parent_session_id") or ""),
        "user_goal": str(raw.get("user_goal") or "")[:500],
        "written_at": raw.get("written_at"),
        "counts": counts,
        "tasks": [
            {
                "id": str(t.get("id") or ""),
                "desc": str(t.get("desc") or "")[:120],
                "status": str(t.get("status") or "pending"),
            }
            for t in tasks
        ],
    }


async def run_task_batch(
    tasks: list[Task] | None = None,
    *,
    workspace_root: str | Path,
    runtime_provider: Any,
    write_store: WriteStore | None = None,
    main_session_id: str = "",
    max_concurrency: int = 10,
    agent_ids: dict[str, str] | None = None,
    on_event: Any | None = None,
    task_batch_id: str = "",
    ui_uids: dict[str, str] | None = None,
    resume: bool = False,
    user_goal: str = "",
    abort: AbortController | None = None,
) -> list[Task]:
    """一次调度一批任务，返回带结果的 tasks。"""
    sched = Scheduler(
        workspace_root,
        max_concurrency=max_concurrency,
        write_store=write_store,
        runtime_provider=runtime_provider,
        main_session_id=main_session_id,
        agent_ids=agent_ids,
        progress_sink=on_event,
        task_batch_id=task_batch_id,
        ui_uids=ui_uids,
        user_goal=user_goal,
        abort=abort,
    )
    if resume:
        if not sched.load_state():
            return []
        if user_goal and not sched._user_goal:
            sched._user_goal = user_goal.strip()
        sched.prepare_for_resume()
    else:
        if not tasks:
            return []
        sched.load(tasks)
        if ui_uids:
            sched._ui_uids = dict(ui_uids)
        if agent_ids:
            for tid, aid in agent_ids.items():
                t = sched._tasks.get(tid)
                if t is not None and not t.agent_id:
                    t.agent_id = aid
        if user_goal:
            sched._user_goal = user_goal.strip()
        sched._persist()
    try:
        await sched.run()
    finally:
        # 全成功也不清盘：保留 awaiting_synthesis，供合成中断后续跑只合成。
        # 合成落盘成功后由 chat 层 clear_scheduler_checkpoint。
        sched._persist()
    return list(sched._tasks.values())
