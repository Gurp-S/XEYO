"""JournalQuery — read-only recent workspace changes (multi-agent visibility)."""

from __future__ import annotations

from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.journal_query_tool.prompt import DESCRIPTION, JOURNAL_QUERY_TOOL_NAME


class JournalQueryTool:
    name = JOURNAL_QUERY_TOOL_NAME
    max_result_size_chars = 12_000

    def __init__(self, *, cwd: str = ".") -> None:
        self._cwd = cwd

    @staticmethod
    def is_read_only() -> bool:
        return True

    @staticmethod
    def is_concurrency_safe() -> bool:
        return True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": DESCRIPTION,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path_prefix": {
                        "type": "string",
                        "description": "Only return changes whose path starts with this prefix.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows (1–50). Default 20.",
                    },
                    "since_ts": {
                        "type": "number",
                        "description": "Only return changes at or after this unix timestamp (seconds).",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Only return changes from this agent_id.",
                    },
                },
                "additionalProperties": False,
            },
        }

    async def execute(
        self, input: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        from memory import journal
        from memory.memdir import workspace_id

        prefix = str((input or {}).get("path_prefix") or "").strip() or None
        agent_id = str((input or {}).get("agent_id") or "").strip() or None
        try:
            limit = int((input or {}).get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(50, limit))
        since_ts = None
        raw_since = (input or {}).get("since_ts")
        if raw_since is not None and raw_since != "":
            try:
                since_ts = float(raw_since)
            except (TypeError, ValueError):
                since_ts = None
        try:
            wsid = workspace_id(self._cwd)
        except Exception:  # noqa: BLE001
            wsid = self._cwd
        import asyncio

        rows = await asyncio.to_thread(
            journal.recent_changes,
            wsid,
            path_prefix=prefix,
            since_ts=since_ts,
            agent_id=agent_id,
            limit=max(limit * 3, 50),
            workspace_root=self._cwd,
        )
        rows = _filter_rows_for_session(rows, limit=limit)
        text = journal.format_changes_for_agent(rows) or "(no recent workspace changes)"
        if len(text) > self.max_result_size_chars:
            text = text[: self.max_result_size_chars].rstrip() + "\n… [truncated]"
        return ToolResult(content=text)


def _filter_rows_for_session(rows: list, *, limit: int) -> list:
    """只保留当前会话及其子 agent 的 journal 行；无 session_id 的旧行仍可见。"""
    try:
        from engine.workspace_context import get_workspace_context

        ctx = get_workspace_context()
        sid = (ctx.session_id if ctx is not None else "") or ""
    except Exception:  # noqa: BLE001
        sid = ""
    if not sid:
        return rows[-limit:]
    out = []
    for rec in rows:
        meta = getattr(rec, "metadata", None) or {}
        rec_sid = str(meta.get("session_id") or "").strip()
        # 旧记录无 session_id：保留（同进程多 agent 历史兼容）
        if not rec_sid or rec_sid == sid:
            out.append(rec)
    return out[-limit:]
