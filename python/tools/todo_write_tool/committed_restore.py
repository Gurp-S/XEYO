"""Restore the same observed TodoWrite state consumed by WSC projection."""
from dataclasses import asdict, is_dataclass


def rows_from(messages):
    return [dict(message) if isinstance(message, dict) else asdict(message)
            if is_dataclass(message) else {key: getattr(message, key, None)
                for key in ("role", "name", "content", "tool_call_id")}
            for message in messages]


def reconcile(snapshot, messages):
    from synaptic.task_checkpoint import enabled
    if not enabled():
        return False
    from synaptic.todo_snapshot import latest_todo_snapshot
    current = latest_todo_snapshot(rows_from(messages))
    if not current.observed:
        return False
    snapshot.todos = list(current.records) if current.active_count else []
    return True


def restore(messages):
    from synaptic.todo_snapshot import latest_todo_snapshot, _payload
    from synaptic.textutil import tool_use_blocks
    from tools.todo_write_tool.types import todo_item_from_raw
    rows = rows_from(messages)
    snapshot = latest_todo_snapshot(rows)
    if snapshot.observed:
        return [item for raw in snapshot.records if (item := todo_item_from_raw(raw)) is not None]
    # Legacy standalone named receipts have no call provenance. They remain
    # compatible only when the transcript contains no TodoWrite declarations.
    has_calls = any(use.get("name") == "TodoWrite" for row in rows for use in tool_use_blocks(row))
    if not has_calls:
        for row in reversed(rows):
            if row.get("role") == "tool" and row.get("name") == "TodoWrite" and isinstance(row.get("content"), str):
                execution = row.get("execution") or {}
                if (not isinstance(execution, dict) or row.get("is_error") is True
                        or execution.get("status") in {"error", "cancelled"}
                        or execution.get("complete") is False):
                    continue
                payload = _payload(row["content"])
                if payload is not None:
                    return [item for raw in payload if (item := todo_item_from_raw(raw)) is not None]
    # An uncommitted or failed input is not a state update during restore.
    return []
