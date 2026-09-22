"""运行态 checkpoint 的只读漂移核验。

恢复不能只把聊天记录塞回模型：容器、能力、工具面和后台进程都可能已经
变化。本模块只比较事实并返回报告，绝不自动重放副作用或把旧 job 假装成
running；真正的恢复动作必须由明确的上层流程决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeRecoveryReport:
	checked: bool
	state: str
	differences: tuple[str, ...] = field(default_factory=tuple)
	checkpoint_jobs: tuple[str, ...] = field(default_factory=tuple)
	current_jobs: tuple[str, ...] = field(default_factory=tuple)
	requires_manual_action: bool = False

	def to_dict(self) -> dict[str, Any]:
		return {
			"checked": self.checked,
			"state": self.state,
			"differences": list(self.differences),
			"checkpoint_jobs": list(self.checkpoint_jobs),
			"current_jobs": list(self.current_jobs),
			"requires_manual_action": self.requires_manual_action,
		}


def compare_runtime_checkpoint(
	checkpoint: dict[str, Any] | None,
	current: dict[str, Any],
) -> RuntimeRecoveryReport:
	if not checkpoint:
		return RuntimeRecoveryReport(checked=True, state="fresh")
	old_context = checkpoint.get("context") or {}
	new_context = current.get("context") or {}
	differences: list[str] = []
	for key in (
		"session_id",
		"runtime",
		"container_id",
		"workspace_id",
		"runtime_profile_id",
		"capability_id",
		"tool_schema_hash",
	):
		old = old_context.get(key)
		new = new_context.get(key)
		if old and new and old != new:
			differences.append(key)
	old_jobs = {
		str(row.get("job_id"))
		for row in (checkpoint.get("jobs") or [])
		if isinstance(row, dict)
		and str(row.get("status") or "") in {"running", "stopping"}
		and row.get("job_id")
	}
	new_jobs = {
		str(row.get("job_id"))
		for row in (current.get("jobs") or [])
		if isinstance(row, dict)
		and str(row.get("status") or "") in {"running", "stopping"}
		and row.get("job_id")
	}
	missing_jobs = old_jobs - new_jobs
	if missing_jobs:
		differences.append("active_jobs_not_present")
	state = "compatible" if not differences else "drifted"
	return RuntimeRecoveryReport(
		checked=True,
		state=state,
		differences=tuple(differences),
		checkpoint_jobs=tuple(sorted(old_jobs)),
		current_jobs=tuple(sorted(new_jobs)),
		requires_manual_action=bool(missing_jobs),
	)


__all__ = ["RuntimeRecoveryReport", "compare_runtime_checkpoint"]
