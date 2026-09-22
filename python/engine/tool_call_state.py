"""ToolCall 执行状态机。

状态机只约束执行层，不替模型规划，也不生成模型可见指令。它把工具调用
从一串自然语言事件变成可审计的有限状态迁移，便于 provider/恢复边界统一。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

ToolCallPhase = Literal[
	"new",
	"validated",
	"running",
	"pending",
	"completed",
	"failed",
	"cancelled",
	"unknown",
]


class InvalidToolCallTransition(ValueError):
	"""工具调用尝试了不允许的状态迁移。"""


@dataclass
class ToolCallState:
	tool_use_id: str
	phase: ToolCallPhase = "new"
	revision: int = 0
	reason: str = ""
	history: list[ToolCallPhase] = field(default_factory=lambda: ["new"])

	_ALLOWED: ClassVar[dict[ToolCallPhase, frozenset[ToolCallPhase]]] = {
		"new": frozenset({"validated", "cancelled", "failed"}),
		"validated": frozenset({"running", "pending", "cancelled", "failed"}),
		"running": frozenset({"pending", "completed", "failed", "cancelled", "unknown"}),
		"pending": frozenset({"running", "cancelled", "failed"}),
		"completed": frozenset(),
		"failed": frozenset(),
		"cancelled": frozenset(),
		"unknown": frozenset(),
	}

	@property
	def terminal(self) -> bool:
		return self.phase in {"completed", "failed", "cancelled", "unknown"}

	def transition(self, phase: ToolCallPhase, *, reason: str = "") -> None:
		phase = str(phase)  # type: ignore[assignment]
		allowed = self._ALLOWED.get(self.phase, frozenset())
		if phase not in allowed:
			raise InvalidToolCallTransition(
				f"tool call {self.tool_use_id} cannot transition "
				f"{self.phase} -> {phase}"
			)
		self.phase = phase  # type: ignore[assignment]
		self.revision += 1
		self.reason = str(reason or "")
		self.history.append(self.phase)

	def metadata(self) -> dict[str, object]:
		return {
			"tool_call_state": self.phase,
			"tool_call_state_revision": self.revision,
			"tool_call_state_history": list(self.history),
			"tool_call_state_reason": self.reason,
		}


__all__ = ["InvalidToolCallTransition", "ToolCallPhase", "ToolCallState"]
