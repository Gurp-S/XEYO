"""Preserve completed tool facts and join owned tasks before terminal exits."""
import asyncio

from msgtypes.events import ToolResultEvent
from msgtypes.message import tool_result_message
from tools.base_tool import ToolResult


async def settle_tool_exit(store, tool_uses, early, results, *, reason, tasks=(), result_q=None):
    completed = dict(results)
    for tool_id, task in early.items():
        if task.done() and not task.cancelled():
            try:
                completed[tool_id] = task.result()
            except (Exception, asyncio.CancelledError):
                pass
    owned = set(early.values()) | {task for task in tasks if task is not None}
    for task in owned:
        if not task.done():
            task.cancel()
    if owned:
        await asyncio.gather(*owned, return_exceptions=True)
    for tool_id, task in early.items():
        if task.done() and not task.cancelled():
            try:
                completed[tool_id] = task.result()
            except (Exception, asyncio.CancelledError):
                pass
    # Cancellation may finish a tool that was already executing. Drain after
    # joining, without creating new approval waiters or dispatching more work.
    if result_q is not None:
        while not result_q.empty():
            use, result = result_q.get_nowait()
            completed.setdefault(use.id, result)
    persisted = set()
    for message in reversed(store.items):
        if message.role == "assistant":
            break
        if message.role == "tool":
            persisted.add(message.tool_call_id)
    events = []
    for use in tool_uses:
        if use.id in persisted:
            continue
        result = completed.get(use.id)
        if result is not None and any((result.metadata or {}).get(key) for key in ("ask_pending", "permission_pending")):
            result = None
        if result is None:
            result = ToolResult(
                content=f"tool not completed: {reason}", is_error=True,
                status="cancelled" if reason == "aborted" else "error",
            )
        metadata = result.metadata or {}
        store.append(tool_result_message(
            use.id, use.name, result.content, is_error=result.is_error, images=result.images,
            status=result.status,
        ))
        events.append(ToolResultEvent(
            name=use.name, output=result.content, is_error=result.is_error,
            tool_use_id=use.id, todos=result.todos, ui=result.ui,
            operation_id=metadata.get("operation_id"), status=result.status,
            error_kind=result.error_kind, retryable=result.retryable,
            side_effect=result.side_effect, action_id=result.action_id,
        ))
    return events
