"""xeyo coord — worker 池 runner 与状态观测（接线并入，feature-flag 门）。

子命令：
- ``run``   本机 worker 循环：claim_next → 真会话(worktree) → 上交；后台可并行多实例。
            每轮顺带 reconcile_ready（无 reconciler 独立进程时自收敛）。
- ``status``打印任务表 / scope 租约 / ask 队列快照（只读，诊断用）。

铁律：``coord.workers`` 未开（workspace/home settings.json）即拒绝执行并退出——
**主链路默认零激活**。--once 便于脚本/冒烟；--tasks N 限制处理数后退出。
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import NoReturn

from rich.console import Console

from cli.cwdutil import ensure_utf8_stdio, resolve_cwd

console = Console(stderr=True)


def _require_enabled(cwd: str) -> None:
    from coord.config import coord_workers_enabled

    if not coord_workers_enabled(cwd):
        console.print(
            "[red]coord.workers is disabled for this workspace — refusing to run. "
            "Enable via <workspace>/.xeyo/settings.json → "
            '{"coord": {"workers": true}}.[/red]'
        )
        raise SystemExit(2)


def run_coord_run(
    *,
    cwd: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    idle_poll_sec: float = 2.0,
    max_tasks: int = 0,
    once: bool = False,
    reconcile_only: bool = False,
    work_fn_factory=None,  # 注入点：默认 session_work_fn；离线测试可传 scripted 工厂
) -> NoReturn:
    ensure_utf8_stdio()
    root = resolve_cwd(cwd)
    _require_enabled(root)

    from coord.file_store import CoordFileStore
    from coord.planner import Planner
    from coord.reconciler import Reconciler
    from coord.worker_pool import WorkerPool
    from coord.worker_session import session_work_fn
    from coord.worktree import git

    store = CoordFileStore(root)
    planner = Planner(root, store)
    pool = WorkerPool(root, store)
    rec = Reconciler(root, store)
    factory = work_fn_factory or (
        lambda task: session_work_fn(task, provider=provider, model=model, api_key=api_key))
    wid = f"cli_{os.getpid()}"
    done = 0

    console.print(f"[dim]coord run: root={root} worker={wid} "
                  f"max_tasks={max_tasks or '∞'} once={once}[/dim]")

    try:
        while True:
            # 1) 收敛既有上交（每轮先做，防 reconciler 不在跑时堆积）
            rep = rec.reconcile_ready()
            if rep["merged"] or rep["reopened"] or rep["blocked"]:
                console.print(f"[dim]reconcile: {json.dumps(rep, ensure_ascii=False)}[/dim]")

            if reconcile_only:
                if once:
                    break
                time.sleep(idle_poll_sec)
                continue

            # 2) 认领一张任务卡
            base = git(root, "rev-parse", "main").stdout.strip()
            task = planner.claim_next(root=root, worker_id=wid, base_commit=base)
            if task is None:
                if once:
                    console.print("[dim]no claimable task (once) — exit[/dim]")
                    break
                time.sleep(idle_poll_sec)
                continue

            # 3) 起真会话干活（worktree 内），上交
            out = pool.run_task(task.task_id, wid, factory(task))
            done += 1
            console.print(
                f"[{'green' if out.ok else 'red'}]task {task.task_id} → "
                f"{'submitted' if out.ok else out.error}[/]")
            if max_tasks and done >= max_tasks:
                console.print(f"[dim]reached --tasks {max_tasks} — exit[/dim]")
                break
            if once:
                break
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
    finally:
        # 正常退出/Ctrl-C 均补一次收敛，防最后上交的 task 卡在 ready_to_merge。
        rec.reconcile_ready()
    raise SystemExit(0)


def run_coord_status(*, cwd: str | None = None, as_json: bool = False) -> NoReturn:
    ensure_utf8_stdio()
    root = resolve_cwd(cwd)
    from coord.config import coord_backend, coord_workers_enabled
    from coord.file_store import CoordFileStore

    store = CoordFileStore(root)
    counts: dict[str, int] = {}
    for t in store.list_tasks():
        counts[t.status] = counts.get(t.status, 0) + 1
    leases = store.active_leases(root)
    asks = store.pending_asks(root)
    snap = {
        "root": root,
        "backend": coord_backend(root),
        "workers_enabled": coord_workers_enabled(root),
        "tasks": counts,
        "leases": [{"owner": l.owner, "paths": l.paths} for l in leases],
        "pending_asks": [{"ask_id": a.ask_id, "task_id": a.task_id,
                          "kind": a.kind} for a in asks],
    }
    if as_json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        console.print(f"[bold]coord status[/]  root={root}")
        console.print(f"  backend={snap['backend']}  workers_enabled={snap['workers_enabled']}")
        console.print(f"  tasks: {json.dumps(counts, ensure_ascii=False) or '(none)'}")
        console.print(f"  leases: {len(leases)}  pending_asks: {len(asks)}")
    raise SystemExit(0)
