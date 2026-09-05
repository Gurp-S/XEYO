"""回溯 v3 热路径路由（跳过 preview）。

- ``POST /v1/sessions/{sid}/rewind`` —— transcript 提交后立即返回，
  工作区恢复在后台线程（评审合同：忙时不 interrupt，直接 409）。
- ``POST /v1/sessions/{sid}/rewind/{rewind_id}/undo``
- ``GET  /v1/sessions/{sid}/rewind/{rewind_id}``

v2 的 ``/rollback/*`` 路由保持原样作测试/降级路径，本文件不依赖它。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from rewind.hotpath import (
    RewindHotpath,
    RewindHotpathError,
    RewindNotFoundError,
    RewindStateError,
    RewindValidationError,
)
from server.deps import _pool, api_error
from server.local_gate import require_loopback
from common.errors import safe_error_detail

# T33：回滚面（改写 transcript 与工作区）仅 loopback。
router = APIRouter(tags=["rewind"], dependencies=[Depends(require_loopback)])


class RewindRequest(BaseModel):
    mode: str
    target_message_id: str
    checkpoint_id: str | None = None
    edited_text: str | None = None
    idempotency_key: str | None = None
    confirmed: bool = False


class RewindUndoRequest(BaseModel):
    confirmed: bool = False


def _raise_rewind_api_error(exc: Exception) -> None:
    # T34：detail 经 safe_error_detail 过滤，内部异常痕迹不出 API。
    if isinstance(exc, RewindNotFoundError):
        raise api_error(404, safe_error_detail(exc), "rewind_not_found") from exc
    if isinstance(exc, RewindValidationError):
        raise api_error(400, safe_error_detail(exc), "rewind_invalid") from exc
    if isinstance(exc, RewindStateError):
        raise api_error(409, safe_error_detail(exc), "rewind_conflict") from exc
    if isinstance(exc, RewindHotpathError):
        raise api_error(500, safe_error_detail(exc), "rewind_error") from exc
    raise api_error(500, safe_error_detail(exc), "rewind_error") from exc


def _hotpath(session_id: str) -> RewindHotpath:
    sid = (session_id or "").strip()
    if not sid:
        raise api_error(400, "session_id is empty")
    cwd = _pool.session_cwd(sid) or _pool.cwd
    if not (cwd or "").strip():
        raise api_error(400, "session has no workspace")
    # 双闸第一道：pool 租约。注意 api_error 返回 HTTPException（是函数不是类），
    # 不能写 ``except api_error``——那会在命中时变 TypeError→500（原有潜在 bug）。
    is_busy = getattr(_pool, "is_busy", None)
    if is_busy is not None:
        try:
            busy_now = bool(is_busy(sid)) if callable(is_busy) else False
        except Exception:  # noqa: BLE001 — 忙探测失败不阻断回溯
            busy_now = False
        if busy_now:
            raise api_error(409, "session is busy; stop the running turn first", "session_busy")
    # 双闸第二道（与 chat.py /compact 同口径）：pool 租约在长工具运行超过
    # stale 窗（默认 300s 无事件帧）时会被回收，单查 is_busy 会让回溯穿透
    # 活跃 turn——改写 transcript + replace_history 与运行中回合直接竞态。
    try:
        from engine.turn_runner import get_turn_runner

        turn_running = bool(get_turn_runner().is_running(sid))
    except Exception:  # noqa: BLE001 — turn runner 不可用时不阻断
        turn_running = False
    if turn_running:
        raise api_error(409, "session is busy; stop the running turn first", "session_busy")
    return RewindHotpath(sid, workspace_root=cwd)


def _flush_transcript_writes() -> None:
    """回溯改写 transcript 前必须排空异步写队列。

    引擎经 ``submit_async_append`` 后台批量落盘（50ms 轮询）；回溯的
    「读 rows → 原子替换」若与 writer 竞态，队列里被删后缀的行会在替换后
    被 append 回去（被删回合复活），且 undo 的行数守卫会把 transcript
    永久判为不可撤销。
    """
    try:
        from session.record_transcript import flush_pending_sync

        flush_pending_sync(timeout=5.0)
    except Exception:  # noqa: BLE001 — 排空失败不阻断回溯（writer 幂等去重兜底）
        import logging

        logging.getLogger(__name__).warning(
            "transcript writer flush before rewind failed", exc_info=True
        )


def _detach_auto_drivers(session_id: str) -> None:
    """回溯提交后与自驱动子系统解耦（continue 改写了对话上下文）。

    - goal 驱动器 drop：被回溯掉的旧目标不得在截断上下文上自动续跑
      （disarm + 清 per-session 内存态）；
    - inbox 队列清空：mid-turn 排队消息属于已不存在的上下文；
    - 合成轮请求环境清空（2026-09-05）：env 属于回溯前上下文，清掉后
      需下一次人类请求重新落位，避免陈旧 env 驱动续跑。
    """
    try:
        from server.goal_round_driver import get_goal_round_driver

        get_goal_round_driver().drop_session(session_id)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).debug("goal driver drop failed", exc_info=True)
    try:
        from server.inbox_registry import get_inbox_registry

        get_inbox_registry().drop_session(session_id)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).debug("inbox clear failed", exc_info=True)
    try:
        from server.synthetic_round import clear_request_env

        clear_request_env(session_id)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).debug(
            "request env clear failed", exc_info=True
        )


def _resync_memory(session_id: str, mode: str) -> bool:
    """回溯改写了对话（continue 截断 / undo 回放）后，把内存态对齐磁盘。

    hotpath 只重写 transcript 文件；常驻 engine 的历史、working/session.md
    sidecar 若不同步，下一轮 LLM 仍会看到被回溯掉的回合（v2 经
    on_commit=_pool.drop 覆盖此契约，v3 热路径曾漏接）。restore 模式不动
    transcript，无需对齐。
    """
    if mode != "continue":
        return True
    try:
        return bool(_pool.resync_after_rewind(session_id))
    except Exception:  # noqa: BLE001 — 对齐失败不阻断回溯响应
        import logging

        logging.getLogger(__name__).warning(
            "post-rewind memory resync failed", exc_info=True
        )
        return False


@router.post("/v1/sessions/{session_id}/rewind")
def rewind_session(session_id: str, body: RewindRequest) -> dict[str, Any]:
    try:
        _flush_transcript_writes()
        result = _hotpath(session_id).rewind(
            mode=body.mode,
            target_message_id=body.target_message_id,
            checkpoint_id=body.checkpoint_id,
            edited_text=body.edited_text,
            idempotency_key=body.idempotency_key,
            confirmed=body.confirmed,
        )
    except RewindHotpathError as exc:
        _raise_rewind_api_error(exc)
    # 成功路径必须返回 result，否则落到下方 AssertionError("unreachable")
    # → 前端弹窗收到 500「unreachable」，Restore 永远到不了「回溯完成」。
    memory_resync = _resync_memory(session_id, body.mode)
    if body.mode == "continue":
        _detach_auto_drivers(session_id)
    payload = result.to_dict()
    payload["memory_resync"] = memory_resync
    return payload


@router.post("/v1/sessions/{session_id}/rewind/{rewind_id}/undo")
def rewind_undo(session_id: str, rewind_id: str, body: RewindUndoRequest) -> dict[str, Any]:
    try:
        _flush_transcript_writes()
        result = _hotpath(session_id).undo(rewind_id, confirmed=body.confirmed)
    except RewindHotpathError as exc:
        _raise_rewind_api_error(exc)
    # undo 把 orphan 行回放进 transcript：内存历史同样要对齐回来。
    memory_resync = _resync_memory(session_id, "continue")
    result["memory_resync"] = memory_resync
    return result


class RewindRecoverRequest(BaseModel):
    action: str
    confirmed: bool = False


@router.post("/v1/sessions/{session_id}/rewind/{rewind_id}/recover")
def rewind_recover(
    session_id: str,
    rewind_id: str,
    body: RewindRecoverRequest,
) -> dict[str, Any]:
    """处理 ``recovery_required`` 中间态（§9.2）：retry / abandon。"""
    try:
        return _hotpath(session_id).recover(
            rewind_id, action=body.action, confirmed=body.confirmed
        )
    except RewindHotpathError as exc:
        _raise_rewind_api_error(exc)
    raise AssertionError("unreachable")


@router.get("/v1/sessions/{session_id}/rewind/{rewind_id}")
def rewind_status(session_id: str, rewind_id: str) -> dict[str, Any]:
    try:
        event = _hotpath(session_id).get_event(rewind_id)
    except RewindHotpathError as exc:
        _raise_rewind_api_error(exc)
    if event is None:
        raise api_error(404, f"rewind event not found: {rewind_id}", "rewind_not_found")
    return event


@router.get("/v1/sessions/{session_id}/rewind")
def rewind_list_events(session_id: str) -> list[dict[str, Any]]:
    """切点 pill hydrate 数据源：本会话全部回溯事件（latest-wins）。"""
    return _hotpath(session_id).list_events()


@router.get("/v1/sessions/{session_id}/rewind/checkpoint/{message_id}")
def rewind_checkpoint_lookup(session_id: str, message_id: str) -> dict[str, Any]:
    """弹窗打开时查询某条 user 消息的 checkpoint（无则 Restore 禁用）。"""
    from rewind.index import find_checkpoint_for_message

    sid = (session_id or "").strip()
    if not sid:
        raise api_error(400, "session_id is empty")
    cp = find_checkpoint_for_message(sid, message_id)
    if cp is None:
        return {"checkpoint_id": None}
    from rewind.index import get_checkpoint_anchor

    return {
        "checkpoint_id": cp.checkpoint_id,
        "entry_count": len(cp.entries),
        "anchor": get_checkpoint_anchor(sid, message_id),
    }


class CheckpointAnchorRequest(BaseModel):
    anchor: bool = True


@router.post("/v1/sessions/{session_id}/rewind/checkpoint/{message_id}/anchor")
def rewind_checkpoint_anchor(
    session_id: str,
    message_id: str,
    body: CheckpointAnchorRequest,
) -> dict[str, Any]:
    """给某条 user 消息的 checkpoint 打/取消锚点（§9.1 锚点写入方）。"""
    from rewind.index import mark_checkpoint_anchor

    sid = (session_id or "").strip()
    if not sid:
        raise api_error(400, "session_id is empty")
    cp_id = mark_checkpoint_anchor(sid, message_id, anchor=body.anchor)
    if cp_id is None:
        raise api_error(404, f"no checkpoint for message: {message_id}", "rewind_not_found")
    return {"ok": True, "checkpoint_id": cp_id, "anchor": body.anchor}
