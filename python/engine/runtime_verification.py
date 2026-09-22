"""运行态完成前的一致性检查。

这里不判断代码答案是否正确，也不生成模型可见的建议；只检查 runtime 能
确定的执行事实。报告是旁路观测，调用方可以把它写入 trace/checkpoint，
而不是把自然语言塞回模型上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class VerificationReport:
	checked: bool
	ok: bool
	cwd_exists: bool
	active_jobs: int = 0
	unpaired_tool_calls: int = 0
	orphan_tool_results: int = 0
	unknown_actions: int = 0
	pending_actions: int = 0
	issues: tuple[str, ...] = field(default_factory=tuple)

	@property
	def blocking(self) -> bool:
		return not self.ok

	def to_dict(self) -> dict[str, Any]:
		return {
			"checked": self.checked,
			"ok": self.ok,
			"blocking": self.blocking,
			"cwd_exists": self.cwd_exists,
			"active_jobs": self.active_jobs,
			"unpaired_tool_calls": self.unpaired_tool_calls,
			"orphan_tool_results": self.orphan_tool_results,
			"unknown_actions": self.unknown_actions,
			"pending_actions": self.pending_actions,
			"issues": list(self.issues),
		}


def _tool_ids(messages: Iterable[Any]) -> tuple[set[str], set[str]]:
	calls: set[str] = set()
	results: set[str] = set()
	for message in messages:
		role = str(getattr(message, "role", "") or "")
		content = getattr(message, "content", None)
		blocks = content if isinstance(content, list) else []
		for block in blocks:
			if not isinstance(block, dict):
				continue
			type_name = str(block.get("type") or "")
			if role == "assistant" and type_name in {"tool_use", "tool_call"}:
				tool_id = str(block.get("id") or block.get("tool_use_id") or "")
				if tool_id:
					calls.add(tool_id)
			elif role == "tool" and type_name in {"tool_result", "tool_result_block"}:
				tool_id = str(block.get("tool_use_id") or block.get("tool_call_id") or "")
				if tool_id:
					results.add(tool_id)
		if role == "tool" and getattr(message, "tool_call_id", None):
			results.add(str(message.tool_call_id))
	return calls, results


def verify_runtime(
	*,
	store: Any,
	cwd: str,
	jobs: Iterable[dict[str, Any]] = (),
	action_summary: dict[str, Any] | None = None,
) -> VerificationReport:
	"""检查一轮结束时 runtime 的可判定一致性。"""
	messages = list(getattr(store, "items", ()) or ())
	calls, results = _tool_ids(messages)
	unpaired = len(calls - results)
	orphan = len(results - calls)
	job_rows = list(jobs or ())
	active = sum(
		1 for row in job_rows if str(row.get("status") or "") in {"running", "stopping"}
		if isinstance(row, dict)
	)
	action_rows = list((action_summary or {}).get("actions") or ())
	unknown = sum(1 for row in action_rows if row.get("status") == "unknown")
	pending = sum(1 for row in action_rows if row.get("status") == "executing")
	issues: list[str] = []
	if unpaired:
		issues.append(f"unpaired_tool_calls:{unpaired}")
	if orphan:
		issues.append(f"orphan_tool_results:{orphan}")
	if unknown:
		issues.append(f"unknown_actions:{unknown}")
	if pending:
		issues.append(f"pending_actions:{pending}")
	cwd_exists = bool(cwd) and Path(cwd).is_dir()
	if not cwd_exists:
		issues.append("cwd_missing")
	# active jobs 是事实观察，不自动否定完成：detached job 本来就允许跨 turn 存活。
	return VerificationReport(
		checked=True,
		ok=not issues,
		cwd_exists=cwd_exists,
		active_jobs=active,
		unpaired_tool_calls=unpaired,
		orphan_tool_results=orphan,
		unknown_actions=unknown,
		pending_actions=pending,
		issues=tuple(issues),
	)


__all__ = ["VerificationReport", "verify_runtime"]
