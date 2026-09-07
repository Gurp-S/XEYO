"""Memory — 记忆写路径三合一（write / update / forget）。

检索不在本工具：一切"读"统一走 Grep 直读
- 记忆库:  ~/.xeyo/memory/{workspace_id}/（MEMORY.md 为索引导航，详情在 topics/*.md）
- 会话历史: ~/.xeyo/sessions/*.jsonl（含 .old1/.old2 归档）
以上两个目录已加入读白名单（permissions.filesystem.readable_extra_roots）。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from engine.abort import AbortController
from memory.governance import (
    MemorySchemaError,
    may_resurrect,
    new_note_id,
    parse_and_validate,
    resolve_conflict,
    today_iso,
)
from memory.memdir import (
    append_tombstone,
    find_note,
    load_notes,
    load_tombstones,
    rewrite_index,
    workspace_id,
    write_note,
)
from tools.base_tool import ToolResult
from tools.memory_tool.prompt import build_description

_ACTIONS = ("write", "update", "forget", "search", "peers", "retrieve")

_PEER_TOPIC_LIMIT = 72


def _peer_topic(session_id: str, limit: int = _PEER_TOPIC_LIMIT) -> str:
	"""读同工作区 peer 会话的 session.md，取 Goal/Current 一行作话题。

	原属 T_now 推送逻辑（engine/session_presence._peer_topic）；peer 话题
	工具化后迁到工具层——只在模型主动 ``Memory(action=peers)`` 时读取。
	"""
	sid = (session_id or "").strip()
	if not sid or "__agent__" in sid:
		return ""
	try:
		from memory.session_md import load as _load_session_md

		text = _load_session_md(sid) or ""
	except Exception:  # noqa: BLE001
		return ""
	for header in ("## Goal", "## Current state"):
		idx = text.find(header)
		if idx < 0:
			continue
		for line in text[idx + len(header) :].splitlines():
			line = line.strip()
			if not line:
				continue
			if line.startswith("#"):
				break
			if line in ("(unspecified)", "(none)", "(continue)", "(none yet)"):
				break
			return line[:limit]
	return ""


def _proposals_notice_line(cwd: str) -> str:
	"""待审 XEYO.md 写入提案计数行（一行，可空）。

	批次1 补偿：Proposals digest 已从 T_now 下线推送——模型对候选晋升
	无可执行动作（NightShift / 人工确认）。search 结果附带待审计数作
	低噪音召回通道，全量列表走 /proposals slash 命令。
	失败不挡检索结果。
	"""
	root = (cwd or "").strip()
	if not root:
		return ""
	try:
		from memory.instruction_maintain import list_pending_proposals

		rows = list_pending_proposals(workspace_id(root))
		if rows:
			return (
				f"另有 {len(rows)} 条 XEYO.md 写入提案待审（/proposals 查看）。"
			)
	except Exception:  # noqa: BLE001
		return ""
	return ""


def _format_peer_row(entry: Any) -> str:
	"""一条 peer 的结构化在场行（label / busy / tool / git / files / 话题）。"""
	label = (getattr(entry, "title", "") or "").strip() or str(
		getattr(entry, "session_id", "")
	)
	bits: list[str] = []
	if getattr(entry, "busy", False):
		bits.append("忙碌中")
	tool = (getattr(entry, "current_tool", "") or "").strip()
	if tool:
		bits.append(f"工具: {tool}")
	git_op = (getattr(entry, "git_op", "") or "").strip()
	if git_op:
		bits.append(f"git {git_op}")
	owned = sorted((getattr(entry, "owned_files", {}) or {}).keys())
	if owned:
		show = ", ".join(owned[:8])
		if len(owned) > 8:
			show += f" …(+{len(owned) - 8})"
		bits.append(f"改过: {show}")
	topic = _peer_topic(str(getattr(entry, "session_id", "")))
	if topic:
		bits.append(f"正在聊: {topic}")
	body = "；".join(bits) if bits else "空闲"
	return f"- 会话「{label}」: {body}"


def _build_note_from_input(raw: dict[str, Any], *, note_id: str | None = None) -> Any:
    note_type = str(raw.get("type") or "").strip()
    content = str(raw.get("content") or "").strip()
    source_kind = str(raw.get("source_kind") or "user").strip() or "user"
    fm = {
        "id": note_id or str(raw.get("id") or new_note_id()),
        "type": note_type,
        "title": str(raw.get("title") or ""),
        "source": {
            "kind": source_kind,
            "session_id": str(raw.get("session_id") or ""),
            "message_id": str(raw.get("message_id") or ""),
        },
        "confidence": raw.get("confidence", 1.0),
        "status": str(raw.get("status") or "active"),
        "scope": str(raw.get("scope") or "workspace"),
        "applies_to": raw.get("applies_to") if isinstance(raw.get("applies_to"), list) else [],
        "created_at": str(raw.get("created_at") or today_iso()),
        "updated_at": today_iso(),
        "last_confirmed_at": str(raw.get("last_confirmed_at") or today_iso()),
        "expires_at": raw.get("expires_at"),
        "supersedes": raw.get("supersedes"),
    }
    return parse_and_validate(fm, content)


class MemoryTool:
    name = "Memory"

    def __init__(self, *, cwd: str = ".") -> None:
        self._cwd = cwd
        self._agent_id: str = "main"
        self._session_id: str = ""

    def set_agent_id(self, agent_id: str | None) -> None:
        from memory.agent_scope import MAIN_AGENT_ID

        self._agent_id = (agent_id or "").strip() or MAIN_AGENT_ID

    def set_session_id(self, session_id: str | None) -> None:
        """当前会话 id（跨会话检索时用于排除自身会话树）。"""
        self._session_id = (session_id or "").strip()

    @staticmethod
    def is_read_only() -> bool:
        return False

    @staticmethod
    def is_concurrency_safe() -> bool:
        return False

    def _paths_hint(self) -> str:
        mem = "~/.xeyo/memory/<workspace>"
        sess = "(当前会话转录,会话激活后可 Grep)"
        try:
            from memory.memdir import memdir_root, workspace_id

            mem = str(memdir_root(workspace_id(self._cwd)))
        except Exception:
            pass
        try:
            from engine.workspace_context import get_workspace_context
            from session.persistence import transcript_path

            ctx = get_workspace_context()
            sid = (ctx.session_id if ctx is not None else "") or ""
            if sid.strip():
                tp = transcript_path(sid)
                if tp.is_file():
                    sess = str(tp)
        except Exception:
            pass
        return f"{mem}|{sess}"

    def schema(self) -> dict[str, Any]:
        mem, sess = self._paths_hint().split("|", 1)
        return {
            "name": self.name,
            "description": build_description(mem, sess),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(_ACTIONS)},
                    "id": {
                        "type": "string",
                        "description": "Note id (update/forget) or fragment anchor notes:msg:<i> (retrieve)",
                    },
                    "query": {"type": "string", "description": "search query"},
                    "type": {
                        "type": "string",
                        "enum": ["user", "feedback", "project", "reference"],
                        "description": "write or search filter",
                    },
                    "content": {"type": "string", "description": "Fact to remember (write/update)"},
                    "title": {"type": "string"},
                    "scope": {
                        "type": "string",
                        "description": "write scope, or search filter (workspace/user/…)",
                    },
                    "supersedes": {"type": "string"},
                    "reason": {"type": "string", "description": "forget only"},
                    "top_k": {"type": "integer", "description": "search top_k (default 5)"},
                },
                "required": ["action"],
            },
        }

    async def execute(
        self, input: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        raw = input if isinstance(input, dict) else {}
        action = str(raw.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                content=f"unknown action: {action or '(empty)'}; expected {_ACTIONS}",
                is_error=True,
            )
        if action == "search":
            return await self._execute_search(raw, abort)
        if action == "peers":
            return await self._execute_peers(abort)
        if action == "retrieve":
            # 只读还原：子代理同样可用（与 search/peers 同级，不进写门禁）
            return self._execute_retrieve(raw)
        from memory.agent_scope import may_write_memdir

        if not may_write_memdir(self._agent_id):
            return ToolResult(
                content=(
                    "Memory mutations are not allowed for sub-agents. "
                    "Return MemoryCandidate in the sub-agent handoff; "
                    "the main session or NightShift promotes them after validation."
                ),
                is_error=True,
            )
        note_id = str(raw.get("id") or "").strip()
        if action in ("update", "forget") and not note_id:
            return ToolResult(content=f"action={action} requires id", is_error=True)
        if action == "forget":
            return await self._execute_forget(note_id, raw, abort)
        if action == "update":
            return await self._execute_update(note_id, raw, abort)
        return await self._execute_write(raw, abort)

    async def _execute_search(
        self, raw: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        query = str(raw.get("query") or raw.get("content") or "").strip()
        if not query:
            return ToolResult(content="action=search requires query", is_error=True)
        scope = str(raw.get("scope") or "").strip()
        note_type = str(raw.get("type") or "").strip()
        try:
            top_k = int(raw.get("top_k") or 5)
        except (TypeError, ValueError):
            top_k = 5
        from memory.search import search

        # 扫描 + touch 是同步文件 I/O——挪线程防冻结事件循环。
        hits = await asyncio.to_thread(
            search,
            query,
            scope=scope,
            note_type=note_type,
            top_k=top_k,
            cwd=self._cwd,
            touch=True,
        )
        # 跨会话共享记忆：同工作区其他对话的 session.md 一并检索，
        # 命中即带会话归属返回 —— 让对话能看到别的对话聊过什么。
        from memory.search import search_session_notes

        try:
            session_hits = await asyncio.to_thread(
                search_session_notes,
                query,
                cwd=self._cwd,
                self_session_id=self._session_id,
                top_k=max(1, int(top_k)),
            )
        except Exception:  # noqa: BLE001 — 跨会话检索失败不挡本会话记忆
            session_hits = []
        # P2-2 任务级 rollout 归档：历史任务语义笔记（会话结束写一次，只读检索）
        from memory.search import search_rollout_summaries

        try:
            rollout_hits = await asyncio.to_thread(
                search_rollout_summaries,
                query,
                cwd=self._cwd,
                top_k=max(1, int(top_k)),
            )
        except Exception:  # noqa: BLE001 — 归档检索失败不挡本会话记忆
            rollout_hits = []
        if not hits and not session_hits and not rollout_hits:
            # 空结果也带提案计数——召回通道不依赖命中。
            return ToolResult(
                content=_proposals_notice_line(self._cwd) or "(no memory hits)"
            )
        lines = []
        for n in hits:
            from memory.search import note_citation_text

            cite = note_citation_text(n, workspace_id(self._cwd))
            lines.append(
                f"- [{n.type}/{n.scope} conf={n.confidence}] {n.id}: "
                f"{(n.title or '')[:80]}\n  {n.content[:400]}"
            )
            if cite:
                lines.append(f"  引用: {cite.replace(chr(10), ' / ')[:180]}")
        if session_hits:
            lines.append("跨会话记忆（同工作区其他对话的 session notes）:")
            for h in session_hits:
                sid = h.session_id if len(h.session_id) <= 12 else h.session_id[-12:]
                lines.append(f"- 会话「{h.title[:60]}」({sid}): {h.excerpt[:72]}")
                if h.citation:
                    lines.append(f"  引用: {h.citation.replace(chr(10), ' / ')[:120]}")
        if rollout_hits:
            lines.append("历史任务归档（rollout summaries）:")
            for h in rollout_hits:
                sid = h.session_id if len(h.session_id) <= 12 else h.session_id[-12:]
                lines.append(f"- 任务「{h.title[:60]}」({sid}): {h.excerpt[:72]}")
                if h.citation:
                    lines.append(f"  引用: {h.citation.replace(chr(10), ' / ')[:120]}")
        tail = _proposals_notice_line(self._cwd)
        if tail:
            lines.append(tail)
        return ToolResult(content="\n".join(lines))

    async def _execute_peers(self, abort: AbortController) -> ToolResult:
        """列出同工作区其他活跃会话（结构化在场信息，纯读）。

        peer 话题的拉取面：T_now 只留一行 beacon，明细由模型按需调用。
        只读 + 并发安全（presence 表是进程内快照，session.md 只读扫描）；
        子代理上下文返回空（T14 净化清单：子代理不见 peer presence）。
        """
        abort.raise_if_aborted()
        from memory.agent_scope import is_main_agent

        if not is_main_agent(self._agent_id):
            return ToolResult(content="(no peers)")
        from engine.session_presence import default_session_presence

        def _collect() -> list[str]:
            entries = default_session_presence().peers(self._cwd, self._session_id)
            if not entries:
                return []
            lines = [f"同工作区其他会话（{len(entries)}）:"]
            lines.extend(_format_peer_row(ent) for ent in entries)
            return lines

        # session.md 读取是文件 I/O——挪线程防冻结事件循环。
        rows = await asyncio.to_thread(_collect)
        if not rows:
            return ToolResult(content="(no peers)")
        return ToolResult(content="\n".join(rows))

    def _execute_retrieve(self, raw: dict[str, Any]) -> ToolResult:
        """A2 retrieve 还原：按 ``notes:msg:<i>``（可选 ``:<kind>``）取回压缩碎片。

        C2 压缩时抓拍的结构化原子（报错栈/取值行/路径…）字节级找回；
        无记录返回可解释的空结果（还原未开启 / 该消息未含结构化原子）。
        """
        fid = str(raw.get("id") or "").strip()
        if not fid:
            return ToolResult(content="action=retrieve requires id", is_error=True)
        import re as _re

        m = _re.match(r"^notes:msg:(\d+)(?::([A-Za-z_]+))?$", fid)
        if not m:
            return ToolResult(
                content=(
                    f"unknown fragment id: {fid}；"
                    "retrieve 的 id 形如 notes:msg:<index>（见 [C2] 摘要行/引用锚点）"
                ),
                is_error=True,
            )
        try:
            idx = int(m.group(1))
        except ValueError:  # pragma: no cover
            return ToolResult(content=f"bad fragment id: {fid}", is_error=True)
        kind = (m.group(2) or "").strip() or None
        from memory import memindex

        rows = memindex.get_fragments(self._session_id, idx, kind=kind)
        if not rows:
            return ToolResult(
                content=(
                    f"(no fragments recorded for notes:msg:{idx}"
                    + (f" kind={kind}" if kind else "")
                    + "；还原未开启或该消息未含结构化原子，可重跑对应工具获取原文)"
                )
            )
        lines = [f"notes:msg:{idx}" + (f" kind={kind}" if kind else "") + f" — {len(rows)} fragments:"]
        used = 0
        shown = 0
        for row in rows:
            text = str(row.get("text") or "")
            if used + len(text) > 8_000:
                lines.append(f"…（其余 {len(rows) - shown} 条省略，单次还原上限 8k 字符）")
                break
            lines.append(f"- [{row.get('kind')}] {text}")
            used += len(text)
            shown += 1
        return ToolResult(content="\n".join(lines))

    async def _execute_write(
        self, raw: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        from memory.write_policy import refuse_reason

        blocked = refuse_reason(
            title=str(raw.get("title") or ""),
            content=str(raw.get("content") or ""),
        )
        if blocked:
            return ToolResult(content=blocked, is_error=True)
        wsid = workspace_id(self._cwd)
        stones = load_tombstones(wsid)
        try:
            note = _build_note_from_input(raw)
        except MemorySchemaError as exc:
            return ToolResult(content=f"schema rejected: {exc}", is_error=True)
        if not may_resurrect(note.id, stones) and any(s.id == note.id for s in stones):
            return ToolResult(content=f"tombstone blocks {note.id}", is_error=True)
        existing = await asyncio.to_thread(load_notes, wsid)
        superseded_ids: list[str] = []
        for old in existing:
            if old.id == note.id:
                continue
            verdict = resolve_conflict(old, note)
            if verdict == "keep_old":
                return ToolResult(
                    content="inference must not override a user-confirmed note",
                    is_error=True,
                )
            if verdict == "supersede":
                superseded_ids.append(old.id)
        for old_id in superseded_ids:
            old = find_note(wsid, old_id)
            if old is not None:
                await asyncio.to_thread(
                    write_note,
                    replace(old, status="superseded", supersedes=note.id),
                    wsid=wsid,
                )
        if superseded_ids:
            note = replace(note, supersedes=note.supersedes or superseded_ids[0])
        await asyncio.to_thread(write_note, note, wsid=wsid)
        from memory.memdir import resolve_memdir_id

        target = resolve_memdir_id(wsid, scope=note.scope)
        await asyncio.to_thread(rewrite_index, await asyncio.to_thread(load_notes, target), wsid=target)
        return ToolResult(content=f"wrote {note.id} ({note.type}/{note.scope}) {note.title}")

    async def _execute_update(
        self, note_id: str, raw: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        wsid = workspace_id(self._cwd)
        old = find_note(wsid, note_id)
        if old is None:
            return ToolResult(content=f"unknown note {note_id}", is_error=True)
        from memory.write_policy import refuse_reason

        next_title = str(raw.get("title") or old.title or "")
        next_content = str(raw.get("content") or old.content or "")
        blocked = refuse_reason(title=next_title, content=next_content)
        if blocked:
            return ToolResult(content=blocked, is_error=True)
        merged = {
            "id": old.id,
            "type": raw.get("type") or old.type,
            "title": raw.get("title") or old.title,
            "content": raw.get("content") or old.content,
            "source_kind": old.source.get("kind") or "user",
            "session_id": old.source.get("session_id") or "",
            "message_id": old.source.get("message_id") or "",
            "confidence": raw.get("confidence", old.confidence),
            "status": raw.get("status") or old.status,
            "scope": old.scope,
            "applies_to": old.applies_to,
            "created_at": old.created_at,
            "supersedes": raw.get("supersedes", old.supersedes),
            "last_confirmed_at": old.last_confirmed_at,
        }
        try:
            note = _build_note_from_input(merged, note_id=old.id)
        except MemorySchemaError as exc:
            return ToolResult(content=f"schema rejected: {exc}", is_error=True)
        await asyncio.to_thread(write_note, note, wsid=wsid)
        from memory.memdir import resolve_memdir_id

        target = resolve_memdir_id(wsid, scope=note.scope)
        rewrite_index(load_notes(target), wsid=target)
        return ToolResult(content=f"updated {note.id}")

    async def _execute_forget(
        self, note_id: str, raw: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        reason = str(raw.get("reason") or "user_request")
        wsid = workspace_id(self._cwd)
        note = find_note(wsid, note_id)
        if note is None:
            return ToolResult(content=f"unknown note {note_id}", is_error=True)
        from memory.governance import forget as make_tombstone

        stone = make_tombstone(note_id, reason=reason)
        write_note(replace(note, status="deleted"), wsid=wsid)
        append_tombstone(stone, wsid=wsid)
        from memory.memdir import resolve_memdir_id

        target = resolve_memdir_id(wsid, scope=note.scope)
        rewrite_index(load_notes(target), wsid=target)
        try:
            from memory.nightshift import load_state, save_state

            state = load_state(wsid)
            state.pending_forget_or_conflict = True
            save_state(wsid, state)
        except Exception:
            pass
        return ToolResult(content=f"forgot {note_id}")
