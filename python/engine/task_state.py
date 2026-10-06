"""会话级任务状态机（SessionTaskState）。

与 Todo 文本、JobStore、前端 chatStore 不同，这是会话的权威任务状态：
queued / running / waiting_permission / stopping / stopped / succeeded / failed。
TodoWrite 仅作为兼容写入器；其它入口只消费本状态的投影。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

TaskStatus = Literal[
	"queued",
	"running",
	"waiting_permission",
	"stopping",
	"stopped",
	"succeeded",
	"failed",
]

#: 区分「参数没给」与「显式传 None（清空）」。
#: 用 None 当缺省会把两者合并：调用方永远清不掉 current_tool / error。
_KEEP = object()


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
		turn_id: Any = _KEEP,
		current_tool: Any = _KEEP,
		interruptible: Any = _KEEP,
		agent_mode: Any = _KEEP,
		error: Any = _KEEP,
	) -> bool:
		"""更新状态。返回是否发生"可观察"变化（供事件去重）。

		缺省 = 保持原值；显式 `None` = 清空该字段。
		"""
		changed = bool(
			self.status != status
			or (turn_id is not _KEEP and self.turn_id != turn_id)
			or (current_tool is not _KEEP and self.current_tool != current_tool)
			or (interruptible is not _KEEP and self.interruptible != interruptible)
			or (agent_mode is not _KEEP and self.agent_mode != agent_mode)
			or (error is not _KEEP and self.error != error)
		)
		self.status = status
		if turn_id is not _KEEP:
			self.turn_id = str(turn_id or "")
		if current_tool is not _KEEP:
			self.current_tool = None if current_tool is None else str(current_tool)
		if interruptible is not _KEEP:
			self.interruptible = bool(interruptible)
		if agent_mode is not _KEEP and agent_mode is not None:
			# 非 Optional 字段：显式 None 没有合法的清空目标，按保持处理，
			# 免得把字面 "None" 写进模式字段（生产调用点恒给合法模式名）。
			self.agent_mode = str(agent_mode)
		if error is not _KEEP:
			self.error = None if error is None else str(error)
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
