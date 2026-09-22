"""工具执行错误分类。

分类是执行层事实，不是给模型的指令。它让 query loop、审计和评测 verdict
区分“参数/路径错误”“不可重试的权限错误”和“可重试的临时基础设施错误”，
而不必从自然语言错误文本猜测。
"""

from __future__ import annotations

from typing import Any


UNKNOWN_TOOL = "UNKNOWN_TOOL"
RESERVED_CHANNEL = "RESERVED_CHANNEL"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
NOT_FOUND = "NOT_FOUND"
COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
PERMISSION_DENIED = "PERMISSION_DENIED"
USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"
TRANSIENT_INFRA = "TRANSIENT_INFRA"
TIMEOUT = "TIMEOUT"
ABORTED = "ABORTED"
ACTION_OUTCOME_UNKNOWN = "ACTION_OUTCOME_UNKNOWN"
INTERNAL = "INTERNAL"
FINALIZATION_RESTRICTED = "FINALIZATION_RESTRICTED"


def classify_exception(exc: BaseException) -> tuple[str, bool]:
	"""把执行异常映射为 (error_kind, retryable)。"""
	name = type(exc).__name__.lower()
	text = str(exc).lower()
	if "timeout" in name or "timed out" in text or "timeout" in text:
		return TIMEOUT, True
	if "permission" in name or "permission denied" in text:
		return PERMISSION_DENIED, False
	if "notfound" in name or "not found" in text:
		return NOT_FOUND, False
	if "connection" in name or "temporar" in text or "docker" in text:
		return TRANSIENT_INFRA, True
	if "abort" in name or "cancel" in name:
		return ABORTED, False
	return INTERNAL, False


def metadata(
	kind: str,
	*,
	retryable: bool = False,
	side_effect: str = "none",
	action_id: str | None = None,
	**extra: Any,
) -> dict[str, Any]:
	"""生成兼容旧 metadata 的结构化字段。"""
	value = {
		"error_kind": kind,
		"retryable": bool(retryable),
		"side_effect": side_effect,
	}
	if action_id:
		value["action_id"] = action_id
	value.update(extra)
	return value


__all__ = [
	"ABORTED",
	"ACTION_OUTCOME_UNKNOWN",
	"COMMAND_NOT_FOUND",
	"INTERNAL",
	"FINALIZATION_RESTRICTED",
	"INVALID_ARGUMENT",
	"NOT_FOUND",
	"PERMISSION_DENIED",
	"RESERVED_CHANNEL",
	"TIMEOUT",
	"TRANSIENT_INFRA",
	"UNKNOWN_TOOL",
	"USER_INPUT_REQUIRED",
	"classify_exception",
	"metadata",
]
