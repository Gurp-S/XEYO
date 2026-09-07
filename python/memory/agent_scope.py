"""多 Agent 记忆范围：共享 / 隔离 / 回传。

设计见记忆体系设计 #10 §5、记忆体系落地 #11 Wave 6。
子 Agent 完整 transcript 走侧链；主会话只追加一条回传摘要（+ 可选 MemoryCandidate）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from memory.governance import MemoryCandidate
from msgtypes.message import Message, assistant_text_message, tool_result_message, user_message

if TYPE_CHECKING:
    from session.message_store import MessageStore

MAIN_AGENT_ID = "main"
_MEMDIR_WRITE_TOOLS = frozenset({"Memory"})


@dataclass(frozen=True)
class AgentScope:
    """子 Agent 与主会话的记忆边界。"""

    agent_id: str = MAIN_AGENT_ID  # main 或子 Agent id
    can_write_memdir: bool = True  # 主会话可写；子 Agent 默认 False
    can_write_session_md: bool = True  # 仅主会话可写 session.md / compact_cursor
    share_kv_prefix: bool = False  # 禁止与主会话共用一条 KV 前缀


@dataclass
class SubagentHandoff:
    """子 Agent 结束回传主会话的结构化载荷。"""

    agent_id: str
    summary: str
    files_touched: list[str] = field(default_factory=list)
    memories: list[Any] = field(default_factory=list)  # MemoryCandidate | dict
    is_error: bool = False


def is_main_agent(agent_id: str | None) -> bool:
    """是否主会话 agent（空 / main 视为主）。"""
    aid = (agent_id or "").strip()
    return not aid or aid == MAIN_AGENT_ID


def scope_for(agent_id: str | None) -> AgentScope:
    """按 agent_id 返回隔离规则：子 Agent 只读 memdir、不写主 session.md。"""
    aid = (agent_id or "").strip() or MAIN_AGENT_ID
    if is_main_agent(aid):
        return AgentScope(
            agent_id=MAIN_AGENT_ID,
            can_write_memdir=True,
            can_write_session_md=True,
            share_kv_prefix=True,
        )
    return AgentScope(
        agent_id=aid,
        can_write_memdir=False,
        can_write_session_md=False,
        share_kv_prefix=False,
    )


def _safe_segment(raw: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in "._-" else "_" for ch in (raw or "")
    ).strip("._") or "x"


def scoped_session_id(main_session_id: str, agent_id: str | None) -> str:
    """L3/L5b 落盘用的 session 键：主会话用 main id；子 Agent 用隔离键，避免污染主 session.md。"""
    main = (main_session_id or "").strip()
    if not main or is_main_agent(agent_id):
        return main
    return f"{_safe_segment(main)}__agent__{_safe_segment(agent_id or '')}"


def may_write_memdir(agent_id: str | None) -> bool:
    """当前 agent 是否允许直接写 memdir（Memory 工具 / topics）。"""
    return scope_for(agent_id).can_write_memdir


def may_touch_session_md(agent_id: str | None) -> bool:
    """当前 agent 是否允许更新 session.md 或推进 compact_cursor 到主会话域。"""
    return scope_for(agent_id).can_write_session_md


def filter_tool_names_for_scope(
    tool_names: list[str] | tuple[str, ...],
    agent_id: str | None,
) -> list[str]:
    """按记忆边界裁剪工具白名单（子 Agent 默认剔除 Memory）。"""
    scope = scope_for(agent_id)
    if scope.can_write_memdir:
        return list(tool_names)
    return [n for n in tool_names if n not in _MEMDIR_WRITE_TOOLS]


def _memory_candidate_lines(memories: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in memories:
        if item is None:
            continue
        if isinstance(item, dict):
            content = str(item.get("content") or "").strip()
        else:
            content = str(getattr(item, "content", "") or "").strip()
        if content:
            lines.append(f"- {content[:240]}")
    return lines


def format_subagent_summary(handoff: SubagentHandoff | str) -> str:
    """把回传载荷格式化为单条摘要文本（供 tool_result 或 SSE 摘要）。"""
    if isinstance(handoff, str):
        return handoff.strip()
    parts: list[str] = []
    body = (handoff.summary or "").strip()
    if body:
        parts.append(body)
    if handoff.files_touched:
        parts.append("Files: " + ", ".join(handoff.files_touched[:20]))
    mem_lines = _memory_candidate_lines(handoff.memories)
    if mem_lines:
        parts.append("Memory candidates:\n" + "\n".join(mem_lines))
    if handoff.is_error and not parts:
        parts.append("(subagent failed)")
    return "\n".join(parts).strip()


def attach_subagent_result(
    main_store: MessageStore,
    handoff: SubagentHandoff | str,
    *,
    tool_use_id: str | None = None,
    tool_name: str = "Agent",
) -> Message:
    """子 Agent 结束时只向主历史追加一条回传，禁止把子全文写入主 JSONL。

    - 有 ``tool_use_id``：追加标准 ``role=tool``（AgentTool 路径，配对 assistant.tool_calls）。
    - 无 ``tool_use_id``：追加带前缀的 user 消息（multi-agent 批量路径，无配对 tool_use 时）。
    """
    if isinstance(handoff, str):
        payload = SubagentHandoff(agent_id="", summary=handoff)
    else:
        payload = handoff
    text = format_subagent_summary(payload)
    prefix = f"[Subagent {payload.agent_id}]\n" if payload.agent_id else ""
    tid = (tool_use_id or "").strip()
    if tid:
        msg = tool_result_message(
            tid,
            tool_name,
            text,
            is_error=payload.is_error,
        )
    else:
        msg = user_message(f"{prefix}{text}".strip())
    main_store.append(msg)
    return msg


def handoff_from_run_result(
    *,
    agent_id: str,
    conclusion: str,
    files_touched: list[str] | None = None,
    memories: list[Any] | None = None,
    is_error: bool = False,
) -> SubagentHandoff:
    """从 ``SubagentRunResult`` / ``SubagentOutput`` 字段构建 ``SubagentHandoff``。"""
    return SubagentHandoff(
        agent_id=agent_id,
        summary=conclusion,
        files_touched=list(files_touched or []),
        memories=list(memories or []),
        is_error=is_error,
    )


def normalize_memory_candidates(
    raw: list[Any],
    *,
    main_session_id: str,
    agent_id: str,
) -> list[MemoryCandidate]:
    """把子 Agent 回传的 memory 载荷规范化为 ``MemoryCandidate``。"""
    out: list[MemoryCandidate] = []
    sid = (main_session_id or "").strip()
    aid = (agent_id or "").strip()
    for item in raw or []:
        if item is None:
            continue
        if isinstance(item, MemoryCandidate):
            out.append(item)
            continue
        if isinstance(item, dict):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            source = {
                **source,
                "kind": str(source.get("kind") or "agent"),
                "session_id": str(source.get("session_id") or sid),
                "agent_id": str(source.get("agent_id") or aid),
            }
            evidence = list(item.get("evidence") or [])
            out.append(MemoryCandidate(content=content, source=source, evidence=evidence))
    return out


def enqueue_subagent_candidates(
    workspace_cwd: str,
    handoffs: list[SubagentHandoff],
    *,
    main_session_id: str,
) -> int:
    """把子 Agent 回传的 MemoryCandidate 追加到工作区 candidates.jsonl（待主会话/NightShift 晋升）。"""
    if not handoffs:
        return 0
    try:
        from memory.memdir import workspace_id
        from memory.nightshift import append_candidates
    except ImportError:
        return 0
    wsid = workspace_id(workspace_cwd)
    batch: list[MemoryCandidate] = []
    for h in handoffs:
        batch.extend(
            normalize_memory_candidates(
                h.memories,
                main_session_id=main_session_id,
                agent_id=h.agent_id,
            )
        )
    if not batch:
        return 0
    try:
        return append_candidates(wsid, batch)
    except OSError:
        return 0


def _ensure_user_message(
    store: MessageStore,
    user_text: str,
    *,
    user_message_id: str | None = None,
) -> None:
    """multi-agent 路径：保证当前用户消息已进主 store（幂等）。"""
    text = (user_text or "").strip()
    if not text:
        return
    mid = (user_message_id or "").strip()
    items = store.items
    if mid and any(getattr(m, "id", "") == mid for m in items):
        return
    if items:
        last = items[-1]
        if last.role == "user":
            last_text = last.content if isinstance(last.content, str) else str(last.content)
            if text in last_text or last_text.strip() == text:
                return
    store.append(user_message(text, message_id=mid or None))


async def persist_multi_agent_turn(
    engine: Any,
    *,
    user_text: str,
    user_message_id: str | None,
    task_rows: list[dict[str, Any]],
    summary_md: str,
) -> None:
    """multi-agent 批量结束后：用户消息 + 各子 Agent 单条回传 + 汇总 assistant → 主 JSONL。"""
    session = getattr(engine, "_session", None)
    if session is None:
        return
    store = session.messages
    _ensure_user_message(store, user_text, user_message_id=user_message_id)

    handoffs: list[SubagentHandoff] = []
    for row in task_rows:
        status = str(row.get("status") or "")
        body = str(row.get("result") or row.get("reason") or "").strip()
        handoffs.append(
            handoff_from_run_result(
                agent_id=str(row.get("agent_id") or ""),
                conclusion=body,
                files_touched=list(row.get("files_touched") or []),
                memories=list(row.get("memories") or []),
                is_error=status != "done",
            )
        )

    summary = (summary_md or "").strip()
    if summary:
        store.append(assistant_text_message(summary))

    cwd = str(getattr(session, "cwd", "") or "")
    sid = str(getattr(session, "session_id", "") or "")
    enqueue_subagent_candidates(cwd, handoffs, main_session_id=sid)

    if getattr(session, "is_session_persistence_disabled", lambda: False)():
        return
    try:
        from session import record_transcript
        from session.record_transcript import flush_transcript
        from session.persistence import transcript_path

        known = getattr(session, "transcript_known_ids", None)
        idx = int(getattr(session, "transcript_persist_index", 0) or 0)
        pending = store.items[idx:]
        if not pending:
            return
        await record_transcript(
            pending,
            session_id=sid,
            session_persistence_disabled=session.is_session_persistence_disabled(),
            known_ids=known,
        )
        if hasattr(session, "transcript_persist_index"):
            session.transcript_persist_index = len(store.items)
        flush_transcript(transcript_path(sid))
    except Exception:
        pass


__all__ = [
    "MAIN_AGENT_ID",
    "AgentScope",
    "SubagentHandoff",
    "attach_subagent_result",
    "enqueue_subagent_candidates",
    "filter_tool_names_for_scope",
    "format_subagent_summary",
    "handoff_from_run_result",
    "is_main_agent",
    "may_touch_session_md",
    "may_write_memdir",
    "normalize_memory_candidates",
    "persist_multi_agent_turn",
    "scoped_session_id",
    "scope_for",
]
