"""Agent submit 生命周期的执行层状态机。

这不是模型可见的提示，也不替代 ``SessionTaskState``。后者描述整个会话
任务在 API 层的状态；本模块描述一次 submit 内部是否仍在探索、已进入预算
压力或正在收尾，供预算和工具准入使用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

LifecyclePhase = Literal[
	"running",
	"budget_pressure",
	"verifying",
	"finalizing",
	"succeeded",
	"failed",
	"stopped",
]

TERMINAL_PHASES = frozenset({"succeeded", "failed", "stopped"})


@dataclass(frozen=True)
class LifecycleSnapshot:
	phase: LifecyclePhase
	reason: str
	revision: int
	updated_at: float

	def to_dict(self) -> dict[str, object]:
		return {
			"phase": self.phase,
			"reason": self.reason,
			"revision": self.revision,
			"updated_at": self.updated_at,
		}


@dataclass
class AgentLifecycle:
	"""一次 submit 的小型、可审计生命周期状态机。"""

	finalization_reserve_s: float = 30.0
	phase: LifecyclePhase = "running"
	reason: str = ""
	revision: int = 0
	updated_at: float = field(default_factory=time.time)

	def _set(self, phase: LifecyclePhase, reason: str = "") -> bool:
		if self.phase in TERMINAL_PHASES:
			return False
		if self.phase == phase and self.reason == reason:
			return False
		self.phase = phase
		self.reason = str(reason or "")
		self.revision += 1
		self.updated_at = time.time()
		return True

	def reset(self) -> None:
		self.phase = "running"
		self.reason = ""
		self.revision = 0
		self.updated_at = time.time()

	def observe_wall(self, remaining_s: float | None, *, armed: bool) -> None:
		"""记录墙钟压力；未武装时只记录观测状态，不触发停止。"""
		if not armed or remaining_s is None or self.phase != "running":
			return
		if remaining_s <= max(0.0, float(self.finalization_reserve_s)):
			self._set("budget_pressure", "wall_reserve")

	def enter_finalizing(self, reason: str) -> None:
		if self.phase in TERMINAL_PHASES:
			return
		self._set("finalizing", reason)

	def begin_verifying(self, reason: str = "turn_complete") -> None:
		"""进入 runtime 一致性检查阶段；不向模型发送文本。"""
		if self.phase in TERMINAL_PHASES:
			return
		self._set("verifying", reason)

	def finish(self, outcome: Literal["succeeded", "failed", "stopped"], reason: str = "") -> None:
		self._set(outcome, reason)

	def permits_tool(self, tool_name: str) -> bool:
		"""收尾期间禁止创建新的长生命周期子 Agent。

		读、写、编辑和已存在进程的收尾仍由原有工具闸决定；这里仅封住会
		再次扩张生命周期的 Agent 创建，避免收尾窗口被新任务占满。
		"""
		if self.phase != "finalizing":
			return True
		return str(tool_name or "") != "Agent"

	def snapshot(self) -> LifecycleSnapshot:
		return LifecycleSnapshot(
			phase=self.phase,
			reason=self.reason,
			revision=self.revision,
			updated_at=self.updated_at,
		)


__all__ = [
	"AgentLifecycle",
	"LifecyclePhase",
	"LifecycleSnapshot",
	"TERMINAL_PHASES",
]
