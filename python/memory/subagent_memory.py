"""子 Agent 记忆候选采集：从侧链对话提取 MemoryCandidate（P0 确定性，不 fork 模型）。

子 Agent 不得直接写 memdir；若任务中发现值得长期保留的事实，用约定标记输出，
本模块在 run 结束时解析并回传主会话 / candidates.jsonl。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from memory.governance import MemoryCandidate
from msgtypes.message import Message

# 追加到子 Agent 任务尾部（短、稳定）；动态内容只在 system 尾部。
SUBAGENT_MEMORY_INSTRUCTION = (
    "若发现值得跨会话保留的工作区事实，每行输出：\n"
    "MEMORY_CANDIDATE: <用用户语言写的简短事实>\n"
    "子 Agent 不能用 Memory 工具写库。无可保留则不要输出该标记。"
)

_LINE_PREFIX = re.compile(r"^MEMORY_CANDIDATE:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_FENCE = re.compile(
    r"```memory_candidate\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)
# 主会话自然语言「请记住」类触发（中英）
_REMEMBER_RE = re.compile(
    r"(?:请记住|记住(?:这个|一下)?|以后都|下次记得|remember(?:\s+that)?|please\s+remember)\s*[:：]?\s*(.+)",
    re.IGNORECASE,
)
_MAX_CANDIDATES = 8
_MIN_CONTENT_LEN = 8


def _text_of_message(msg: Message | dict[str, Any] | Any) -> str:
    if isinstance(msg, Message):
        content = msg.content
    elif isinstance(msg, dict):
        content = msg.get("content")
    else:
        content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts)
    return ""


def _iter_tool_uses(msg: Message | Any) -> Iterable[tuple[str, dict[str, Any]]]:
    content = msg.content if isinstance(msg, Message) else getattr(msg, "content", None)
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = str(block.get("name") or "")
            raw_input = block.get("input")
            inp = raw_input if isinstance(raw_input, dict) else {}
            yield name, inp


def collect_files_touched(messages: Iterable[Any]) -> list[str]:
    """从子 Agent 侧链扫描 Write/Edit 工具调用，收集 touched 文件路径。"""
    seen: set[str] = set()
    out: list[str] = []
    for msg in messages:
        role = msg.role if isinstance(msg, Message) else getattr(msg, "role", "")
        if role != "assistant":
            continue
        for name, inp in _iter_tool_uses(msg):
            if name not in {"Write", "Edit"}:
                continue
            path = str(
                inp.get("file_path") or inp.get("path") or inp.get("filePath") or ""
            ).strip()
            if path and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _parse_marker_text(text: str) -> list[str]:
    found: list[str] = []
    for m in _LINE_PREFIX.finditer(text or ""):
        line = (m.group(1) or "").strip()
        if len(line) >= _MIN_CONTENT_LEN:
            found.append(line)
    for m in _FENCE.finditer(text or ""):
        blob = (m.group(1) or "").strip()
        if not blob:
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            if len(blob) >= _MIN_CONTENT_LEN:
                found.append(blob)
            continue
        if isinstance(parsed, str) and len(parsed.strip()) >= _MIN_CONTENT_LEN:
            found.append(parsed.strip())
        elif isinstance(parsed, dict):
            content = str(parsed.get("content") or "").strip()
            if len(content) >= _MIN_CONTENT_LEN:
                found.append(content)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str) and len(item.strip()) >= _MIN_CONTENT_LEN:
                    found.append(item.strip())
                elif isinstance(item, dict):
                    content = str(item.get("content") or "").strip()
                    if len(content) >= _MIN_CONTENT_LEN:
                        found.append(content)
    return found


def strip_memory_markers(text: str) -> str:
    """从可见结论文本中移除 MEMORY_CANDIDATE 标记（避免回传摘要重复）。"""
    cleaned = _FENCE.sub("", text or "")
    lines: list[str] = []
    for line in cleaned.splitlines():
        if _LINE_PREFIX.match(line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _dedupe_contents(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        key = raw.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(raw.strip())
    return out[:_MAX_CANDIDATES]


def harvest_subagent_memories(
    messages: Iterable[Message],
    working: Any,
    *,
    main_session_id: str,
    agent_id: str,
    conclusion: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """从侧链消息 + working.speculation + 结论中采集 MemoryCandidate 载荷。

    返回 ``(memories_as_dicts, cleaned_conclusion)``。
    """
    texts: list[str] = []
    for msg in messages:
        role = msg.role if isinstance(msg, Message) else getattr(msg, "role", "")
        if role == "assistant":
            texts.append(_text_of_message(msg))
    if (conclusion or "").strip():
        texts.append(conclusion)

    raw_contents = _dedupe_contents(
        [c for t in texts for c in _parse_marker_text(t)]
    )

    spec = getattr(working, "speculation", None) or []
    for item in spec:
        s = str(item or "").strip()
        if len(s) >= _MIN_CONTENT_LEN:
            raw_contents.append(s)
    raw_contents = _dedupe_contents(raw_contents)

    sid = (main_session_id or "").strip()
    aid = (agent_id or "").strip()
    payloads: list[dict[str, Any]] = []
    for content in raw_contents:
        payloads.append(
            {
                "content": content,
                "source": {
                    "kind": "agent",
                    "session_id": sid,
                    "agent_id": aid,
                },
                "evidence": ["subagent_marker"],
            }
        )

    cleaned = strip_memory_markers(conclusion or "")
    return payloads, cleaned


def harvest_as_candidates(
    messages: Iterable[Message],
    working: Any,
    *,
    main_session_id: str,
    agent_id: str,
    conclusion: str = "",
) -> tuple[list[MemoryCandidate], str]:
    """同 ``harvest_subagent_memories``，返回 ``MemoryCandidate`` 对象。"""
    from memory.agent_scope import normalize_memory_candidates

    payloads, cleaned = harvest_subagent_memories(
        messages,
        working,
        main_session_id=main_session_id,
        agent_id=agent_id,
        conclusion=conclusion,
    )
    return (
        normalize_memory_candidates(
            payloads,
            main_session_id=main_session_id,
            agent_id=agent_id,
        ),
        cleaned,
    )


def _remember_phrases(text: str) -> list[str]:
    """从用户/助手文本抽取「请记住 …」类陈述。"""
    found: list[str] = []
    for m in _REMEMBER_RE.finditer(text or ""):
        body = (m.group(1) or "").strip().strip("\"'`")
        if len(body) >= _MIN_CONTENT_LEN:
            found.append(body[:400])
    return found


def harvest_main_session_memories(
    messages: Iterable[Any],
    working: Any,
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """主会话收割：MEMORY_CANDIDATE 标记 + 「请记住」自然语言 + speculation。

    不写 memdir；调用方 ``append_candidates``。evidence=main_harvest。
    """
    texts: list[str] = []
    for msg in messages:
        role = msg.role if isinstance(msg, Message) else getattr(msg, "role", "")
        if role in {"assistant", "user"}:
            texts.append(_text_of_message(msg))
    raw = _dedupe_contents(
        [c for t in texts for c in _parse_marker_text(t)]
        + [c for t in texts for c in _remember_phrases(t)]
    )
    spec = getattr(working, "speculation", None) or []
    for item in spec:
        s = str(item or "").strip()
        if len(s) >= _MIN_CONTENT_LEN:
            raw.append(s)
    raw = _dedupe_contents(raw)
    try:
        from memory.write_policy import refuse_reason
    except ImportError:
        refuse_reason = None  # type: ignore[assignment]
    if refuse_reason is not None:
        raw = [c for c in raw if refuse_reason(content=c) is None]
    sid = (session_id or "").strip()
    return [
        {
            "content": content,
            "source": {"kind": "agent", "session_id": sid, "agent_id": "main"},
            "evidence": ["main_harvest"],
        }
        for content in raw
    ]


def enqueue_main_session_candidates(
    workspace_cwd: str,
    messages: Iterable[Any],
    working: Any,
    *,
    session_id: str,
) -> int:
    """主会话收割 → candidates.jsonl；返回新追加条数。"""
    payloads = harvest_main_session_memories(
        messages, working, session_id=session_id
    )
    if not payloads:
        return 0
    try:
        from memory.agent_scope import normalize_memory_candidates
        from memory.memdir import workspace_id
        from memory.nightshift import append_candidates
    except ImportError:
        return 0
    batch = normalize_memory_candidates(
        payloads, main_session_id=session_id, agent_id="main"
    )
    if not batch:
        return 0
    try:
        return append_candidates(workspace_id(workspace_cwd), batch)
    except OSError:
        return 0


__all__ = [
    "SUBAGENT_MEMORY_INSTRUCTION",
    "collect_files_touched",
    "enqueue_main_session_candidates",
    "harvest_as_candidates",
    "harvest_main_session_memories",
    "harvest_subagent_memories",
    "strip_memory_markers",
]
