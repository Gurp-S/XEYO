"""统一权限门禁（兼容层）。

真实裁决已收敛到 ``permissions.policy.evaluate_policy``。
本模块保留 ``can_use_tool`` 二元 API（allow|deny）：ASK 降级为 DENY，
供旧测试与不走 ToolRegistry 挂起流程的调用方使用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from permissions.filesystem import (
	PermissionDecision,
	is_dangerous_path,
	path_in_allowed_working_path,
)
from permissions.policy import evaluate_policy


@dataclass(frozen=True)
class GateResult:
	decision: PermissionDecision  # 兼容 API：仅 allow | deny
	reason: str
	path: str | None = None

	@property
	def allowed(self) -> bool:
		return self.decision == PermissionDecision.ALLOW



def _deny_reason(path: str, *, cwd: str, fallback: str) -> str:
	"""把 policy 的 needs_confirmation 映射回可读的路径拒绝原因。"""
	if not path_in_allowed_working_path(
		path, cwd=cwd, allowed_working_paths=[cwd]
	):
		return "path_outside_working_directory"
	if is_dangerous_path(path, cwd=cwd):
		return "dangerous_path"
	return fallback


def can_use_tool(
	name: str,
	tool_input: dict | None,
	*,
	cwd: str,
) -> GateResult:
	"""
	二元权限裁决（ASK→DENY）。
	生产路径请走 ToolRegistry + evaluate_policy（保留 ASK 挂起）。
	"""
	root = os.path.abspath(os.path.expanduser(cwd or "."))
	pd = evaluate_policy(name, tool_input, cwd=root)
	if pd.decision == PermissionDecision.ALLOW:
		return GateResult(
			decision=PermissionDecision.ALLOW,
			reason=pd.reason,
			path=pd.path,
		)
	reason = pd.reason
	if pd.decision == PermissionDecision.ASK and pd.path:
		reason = _deny_reason(pd.path, cwd=root, fallback=pd.reason)
	elif pd.decision == PermissionDecision.ASK:
		reason = pd.reason or "needs_confirmation"
	return GateResult(
		decision=PermissionDecision.DENY,
		reason=reason,
		path=pd.path,
	)
