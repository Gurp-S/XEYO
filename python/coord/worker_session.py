"""worker 真会话接线（阶段 2→主链路，计划 §3 阶段 1「worker 会话派生」）。

把"一个真 XEYO 会话在 worktree 里完成一张任务卡"包成 :class:`WorkerPool`
的 ``work_fn``——worktree 生命周期 / commit / submit / 异常兜底全复用阶段 1
已测闭环，本模块只负责会话侧：

- ``build_default_engine(cwd=worktree, ...)`` 起独立 QueryEngine：
  worktree 是独立物理目录 → ReadFileState 新鲜度检查按绝对路径天然隔离，
  跨 worker 互斥不靠 OCC，靠 coord 租约 + reconciler 三路合并（架构不变）；
- 权限 ``never``：作用域内常规写免确认（policy.py `_AUTO_WRITE_MODES`），
  headless 无 coordinator → 不产生 PermissionPendingEvent，不会挂起等待；
  引擎无交互 ask_user 注入路径（surface=cli 时 AskUser 诚实降级，不阻塞）；
- surface 设 ``cli``（进程内派生是明确非 GUI 面）；
- session_id 带 ``__worker__`` 段（presence 归属可辨，同池互为 peer）；
- 首条消息 = 任务卡（title + brief + scope 事实）；错误措辞中性；
- ``model_client`` 可注入（离线 scripted e2e）；None 时走 build_default_engine
  按 provider/model/api_key 起真后端——**flag 关闭时本模块根本不被 import**。

不做的事（边界）：不派生 asyncio 任务进 FastAPI event loop——coord 锁是同步
自旋（FileGuard），worker 以独立进程运行（`xeyo coord run` CLI），线程模型由
CLI 侧决定，本模块保持纯同步入口。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

_log = logging.getLogger("xeyo.coord.session")

WORKER_SESSION_PREFIX = "__worker__"


def worker_session_id(worker_id: str, task_id: str) -> str:
    """worker 会话 id：带 __worker__ 段 + task 短后缀（presence/审计可辨）。"""
    return f"{WORKER_SESSION_PREFIX}{worker_id}-{task_id[-6:]}"


def task_card_text(task: Any) -> str:
    """任务卡 → 会话首条消息（信息，不导演：只给状态/范围/事实）。"""
    lines = [f"[coord task {task.task_id}]", f"# {task.title}"]
    if getattr(task, "brief", ""):
        lines.append(task.brief)
    if getattr(task, "scope", None):
        lines.append("scope: " + ", ".join(task.scope))
    if getattr(task, "findings", None):
        lines.append("findings: " + "; ".join(
            f"{f.get('file', '')}:{f.get('line', 0)} {f.get('error', '')}"
            for f in task.findings if isinstance(f, dict)))
    return "\n".join(lines)


async def _drain_session(engine: Any, prompt: str, *, timeout_sec: float) -> dict[str, Any]:
    """跑一个回合到 ResultEvent；返回 {ok, text, events}。超时/interrupt 中性收尾。"""
    from msgtypes.events import ResultEvent, StoppedEvent

    text_parts: list[str] = []
    result: dict[str, Any] = {"ok": False, "text": "", "subtype": ""}
    stream = engine.submit(prompt, {"agent_mode": "agent"})

    async def _run() -> None:
        async for ev in stream:
            if hasattr(ev, "text") and getattr(ev, "type", "") == "final":
                text_parts.append(str(ev.text))
            if isinstance(ev, StoppedEvent):
                result.update(ok=False, subtype=str(getattr(ev, "reason", "stopped")))
                return
            if isinstance(ev, ResultEvent):
                result.update(ok=not bool(getattr(ev, "is_error", False)),
                              subtype=str(getattr(ev, "subtype", "")))
                return

    try:
        await asyncio.wait_for(_run(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        try:
            engine.interrupt()
        except Exception:  # noqa: BLE001
            pass
        result.update(ok=False, subtype="timeout")
    except Exception as exc:  # noqa: BLE001 — 会话异常以事实上报（worker_failed 轨道）
        _log.debug("worker session failed", exc_info=True)
        result.update(ok=False, subtype=f"error:{exc}")
    result["text"] = "".join(text_parts)
    return result


def run_worker_session(worktree: Path, task: Any, *,
                       provider: str | None = None,
                       model: str | None = None,
                       api_key: str | None = None,
                       model_client: Any | None = None,
                       timeout_sec: float = 600.0) -> dict[str, Any]:
    """在 worktree 起真会话执行任务卡。返回 {ok, text, subtype}。

    ``model_client`` 注入 = 离线 scripted e2e；否则 build_default_engine 按
    provider/model 走真后端（api_key 缺省读环境，同 CLI 语义）。"""
    from permissions.policy import set_agent_mode, set_permission_mode, set_surface

    from engine.query_engine import build_default_engine

    sid = worker_session_id(getattr(task, "claimed_by", "") or "w", task.task_id)
    max_turns = int(getattr(task, "max_turns", 0) or 20)

    engine = build_default_engine(
        cwd=str(worktree),
        model_backend=("fake" if model_client is not None else provider) or None,
        session_id=sid,
        api_key=api_key or None,
        provider=provider,
        model=model or None,
        max_turns=max_turns,
    )
    if model_client is not None:
        engine._model = model_client  # scripted 注入（fake 后端已建 echo 工具面）

    set_permission_mode("never")
    set_agent_mode("agent")
    set_surface("cli")
    return asyncio.run(_drain_session(
        engine, task_card_text(task), timeout_sec=timeout_sec))


def session_work_fn(task: Any, *, provider: str | None = None,
                    model: str | None = None, api_key: str | None = None,
                    model_client: Any | None = None,
                    timeout_sec: float = 600.0) -> Callable[[Path], None]:
    """WorkerPool.run_task 的 work_fn 工厂：真会话执行任务卡；失败抛 RuntimeError。"""

    def work_fn(p: Path) -> None:
        out = run_worker_session(p, task, provider=provider, model=model,
                                 api_key=api_key, model_client=model_client,
                                 timeout_sec=timeout_sec)
        if not out.get("ok"):
            raise RuntimeError(f"session_{out.get('subtype', 'failed')}")

    return work_fn


__all__ = ["WORKER_SESSION_PREFIX", "session_work_fn",
           "run_worker_session", "task_card_text", "worker_session_id"]
