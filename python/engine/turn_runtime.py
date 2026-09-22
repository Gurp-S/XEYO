"""一次 submit 的回合控制状态机。

模型流、投影和工具编排仍由各自组件负责；本模块只拥有回合边界上的
预算/收尾决策，避免 ``query_loop`` 同时保存一套隐式的终止状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from engine.abort import AbortController

TurnDecision = Literal["continue", "wrap_up", "stop_aborted", "stop_budget"]


@dataclass
class TurnRuntime:
	"""把 submit 内的回合闸门和收尾配额集中到一个可测试对象。"""

	budget: Any
	abort: AbortController
	wrap_quota_left: int
	forced_wrap_up: bool = False

	def __post_init__(self) -> None:
		self.wrap_quota_left = max(0, int(self.wrap_quota_left))
		if self.forced_wrap_up:
			try:
				self.budget.lifecycle.enter_finalizing(
					self.budget.hard_stop_reason or "budget"
				)
			except Exception:  # noqa: BLE001 — 兼容旧 budget 实现
				pass

	def prepare_next_turn(self) -> TurnDecision:
		"""返回下一步状态；不计数，真正计数仍由 ``begin_turn`` 完成。"""
		if self.abort.aborted:
			return "stop_aborted"
		if self.budget.prepare_next_turn():
			return "continue"
		if self.forced_wrap_up:
			return "stop_budget"
		self.forced_wrap_up = True
		# BudgetTracker 通常已进入 finalizing；这里是状态机的兜底，确保
		# 自定义 budget 实现也不会在收尾窗口继续扩张 Agent 生命周期。
		try:
			self.budget.lifecycle.enter_finalizing(
				self.budget.hard_stop_reason or "budget"
			)
		except Exception:  # noqa: BLE001 — 生命周期旁路不阻断预算闸
			pass
		return "wrap_up"

	def begin_turn(self) -> None:
		"""进入一次真实模型请求。"""
		self.budget.begin_turn()

	def permits_tool(self, tool_name: str) -> bool:
		try:
			return bool(self.budget.lifecycle.permits_tool(tool_name))
		except Exception:  # noqa: BLE001 — 兼容无 lifecycle 的旧 budget
			return True

	def consume_wrap_quota(self) -> bool:
		"""收尾窗内占用一个工具配额；未进入收尾或已耗尽均拒绝。"""
		if not self.forced_wrap_up or self.wrap_quota_left <= 0:
			return False
		self.wrap_quota_left -= 1
		return True


__all__ = ["TurnDecision", "TurnRuntime"]
