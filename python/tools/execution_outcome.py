"""Execution identity survives cancellation of the coroutine awaiting a tool."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from engine.flag_definitions import enabled
from tools.base_tool import ToolResult


@dataclass
class ExecutionAttempt:
    started: bool = False
    side_effect: str = "none"
    action_id: str | None = None
    result: ToolResult | None = None

    def recover(self, fallback: ToolResult) -> ToolResult:
        if not enabled("XEYO_TOOL_OUTCOME_CONTRACT"):
            return fallback
        if self.result is not None:
            return self.result
        if self.started and self.side_effect != "none":
            return unknown_result(fallback.content, side_effect=self.side_effect, action_id=self.action_id)
        return fallback


current_attempt: ContextVar[ExecutionAttempt | None] = ContextVar("tool_execution_attempt", default=None)


def unknown_result(detail: str, *, side_effect: str = "external", action_id: str | None = None) -> ToolResult:
    return ToolResult(
        content=f"action outcome unknown: {detail}", is_error=True, status="unknown",
        error_kind="ACTION_OUTCOME_UNKNOWN", retryable=False,
        side_effect=side_effect, action_id=action_id,
        metadata={"execution_complete": False, "action_recovery_required": True},
    )


async def execute_attempt(tool: Any, tool_input: Any, abort: Any, *, side_effect: str, action_id: str | None) -> ToolResult:
    attempt = current_attempt.get()
    if attempt is not None:
        attempt.started = True
        attempt.side_effect = side_effect
        attempt.action_id = action_id
    result = await tool.execute(tool_input, abort)
    if enabled("XEYO_TOOL_OUTCOME_CONTRACT"):
        if result.side_effect == "none":
            result.side_effect = side_effect
        if result.action_id is None:
            result.action_id = action_id
    if attempt is not None:
        attempt.result = result
    return result


def operation_key(session_id: str, tool_name: str, tool_input: Any) -> str:
    # Only unresolved attempts block another call with the same arguments.
    # Successful identical commands remain repeatable; this is not a universal
    # business-level idempotency key for arbitrary external APIs.
    from engine.action_journal import action_identity
    from engine.agent_action_contract import operation_owner
    return action_identity(session_id=operation_owner(session_id), turn_id="", tool_use_id="",
                           tool_name=tool_name, tool_input=tool_input)[1]

