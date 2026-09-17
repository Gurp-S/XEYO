"""T14 子代理结算通知：子代理结束时，在主循环 turn 边界注入可归因的 T_now 块。

正常路径 AgentTool 的 tool_result 会把结果带回主会话，无需通知；
当子代理**没能**把结果带回（父回合 abort / 异常逃逸）时记录一条结算，
下一轮在 T_now 注入 `# 子代理结算（background only）`，status + 一行摘要。

进程内存储（同 server 进程内 turn 边界即生效）；每会话封顶 16 条，先进先出。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

_MAX_PER_SESSION = 16


@dataclass
class AgentSettlement:
    agent_id: str
    task_id: str
    status: str  # done / failed / stopped / interrupted
    summary: str
    settled_at: float = 0.0


_pending: dict[str, list[AgentSettlement]] = {}
_lock = threading.Lock()


def record_agent_settlement(
    session_id: str,
    *,
    agent_id: str,
    task_id: str = "",
    status: str = "done",
    summary: str = "",
) -> None:
    sid = (session_id or "").strip()
    aid = (agent_id or "").strip()
    if not sid or not aid:
        return
    item = AgentSettlement(
        agent_id=aid,
        task_id=(task_id or "").strip(),
        status=(status or "done").strip(),
        summary=(summary or "").strip().replace("\n", " ")[:200],
        settled_at=time.time(),
    )
    with _lock:
        bucket = _pending.setdefault(sid, [])
        bucket.append(item)
        del bucket[: max(0, len(bucket) - _MAX_PER_SESSION)]


def drain_agent_settlements(session_id: str) -> list[AgentSettlement]:
    """取走该会话的全部待注入结算（幂等：取走即清）。"""
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _lock:
        return _pending.pop(sid, [])


def format_settlement_block(notices: list[AgentSettlement]) -> str:
    """渲染 T_now 块；空列表 → 空串（无通知不挂块）。"""
    rows: list[str] = []
    for n in notices or []:
        task = f" · task {n.task_id}" if n.task_id else ""
        body = f"：{n.summary}" if n.summary else ""
        rows.append(f"- [{n.status}] `{n.agent_id}`{task}{body}")
    if not rows:
        return ""
    return (
        "# 子代理结算（background only）\n"
        "结果未进入主会话时的结算状态：\n"
        + "\n".join(rows)
    )


def pending_count(session_id: str) -> int:
    with _lock:
        return len(_pending.get((session_id or "").strip(), []))
