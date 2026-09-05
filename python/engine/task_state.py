"""会话级任务状态机（SessionTaskState）。

与 Todo 文本、JobStore、前端 chatStore 不同，这是会话的权威任务状态：
queued / running / waiting_permission / stopping / stopped / succeeded / failed。
TodoWrite 仅作为兼容写入器；其它入口只消费本状态的投影。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

TaskStatus = Literal[
	"queued",
	"running",
	"waiting_permission",
	"stopping",
	"stopped",
	"succeeded",
	"failed",
]


@dataclass
class SessionTaskState:
	"""会话任务状态的权威持有者。每个 QueryEngine 持有自己的实例。"""

	session_id: str
	turn_id: str = ""
	status: TaskStatus = "queued"
	current_tool: str | None = None
	interruptible: bool = True
	agent_mode: str = "agent"
	error: str | None = None
	revision: int = 0
	updated_at: float = field(default_factory=time.time)

	def set_status(
		self,
		status: TaskStatus,
		*,
		turn_id: str | None = None,
		current_tool: str | None = None,
		interruptible: bool | None = None,
		agent_mode: str | None = None,
		error: str | None = None,
	) -> bool:
		"""更新状态。返回是否发生"可观察"变化（供事件去重）。"""
		changed = bool(
			self.status != status
			or (turn_id is not None and self.turn_id != turn_id)
			or (current_tool is not None and self.current_tool != current_tool)
			or (interruptible is not None and self.interruptible != interruptible)
			or (agent_mode is not None and self.agent_mode != agent_mode)
			or (error is not None and self.error != error)
		)
		self.status = status
		if turn_id is not None:
			self.turn_id = turn_id
		if current_tool is not None:
			self.current_tool = current_tool
		if interruptible is not None:
			self.interruptible = interruptible
		if agent_mode is not None:
			self.agent_mode = agent_mode
		if error is not None:
			self.error = error
		self.revision += 1
		self.updated_at = time.time()
		return changed

	def snapshot(self) -> dict[str, object]:
		"""供 /health 或 API 使用的不变快照。"""
		return {
			"session_id": self.session_id,
			"turn_id": self.turn_id,
			"task_status": self.status,
			"current_tool": self.current_tool,
			"interruptible": self.interruptible,
			"agent_mode": self.agent_mode,
			"error": self.error,
			"revision": self.revision,
			"updated_at": self.updated_at,
		}
