"""XEYO 权限（Windows-only 精简版）。"""

from permissions.filesystem import (
	PermissionDecision,
	ToolPermissionContext,
	check_read_permission_for_path,
	check_read_permission_for_tool,
	check_write_permission_for_path,
	check_write_permission_for_tool,
	default_permission_context,
	path_in_allowed_working_path,
)
from permissions.gate import GateResult, can_use_tool

__all__ = [
	"PermissionDecision",
	"ToolPermissionContext",
	"GateResult",
	"can_use_tool",
	"check_read_permission_for_path",
	"check_read_permission_for_tool",
	"check_write_permission_for_path",
	"check_write_permission_for_tool",
	"default_permission_context",
	"path_in_allowed_working_path",
]
