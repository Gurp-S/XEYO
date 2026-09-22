"""Query loop 与工具执行层之间的窄边界。

这里不做规划、不改变并发/权限策略；只把工具执行入口集中起来，后续可以在
不继续膨胀 ``query_loop.py`` 的情况下替换 provider、trace 或恢复实现。
"""

from __future__ import annotations

from typing import Any

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.orchestration import _run_one_tool, run_tools_partitioned
from tools.tool_registry import ToolRegistry


_BOUND_COORDINATOR = object()


class ToolCoordinator:
	"""工具执行的统一门面；状态与权限事实仍由下层组件持有。"""

	def __init__(self, registry: ToolRegistry, permission_coordinator: Any = None) -> None:
		self.registry = registry
		self.permission_coordinator = permission_coordinator

	async def run_one(
		self,
		tu: ToolUse,
		abort: AbortController,
		*,
		progress_q: Any = None,
		result_q: Any = None,
		coordinator: Any = _BOUND_COORDINATOR,
	) -> ToolResult:
		permission_coordinator = (
			self.permission_coordinator
			if coordinator is _BOUND_COORDINATOR
			else coordinator
		)
		return await _run_one_tool(
			self.registry,
			tu,
			abort,
			coordinator=permission_coordinator,
			progress_q=progress_q,
			result_q=result_q,
		)

	async def run_batch(
		self,
		tool_uses: list[ToolUse],
		abort: AbortController,
		*,
		progress_q: Any = None,
		result_q: Any = None,
	) -> list[ToolResult]:
		return await run_tools_partitioned(
			self.registry,
			tool_uses,
			abort,
			coordinator=self.permission_coordinator,
			progress_q=progress_q,
			result_q=result_q,
		)

	async def run_authorized(
		self, tu: ToolUse, abort: AbortController
	) -> ToolResult:
		"""执行已通过权限面板的调用。"""
		return await self.registry.run(
			tu,
			abort,
			coordinator=self.permission_coordinator,
			skip_ask=True,
		)


__all__ = ["ToolCoordinator"]
