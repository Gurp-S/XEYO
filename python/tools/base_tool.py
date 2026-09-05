from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from engine.abort import AbortController


@dataclass
class ToolResult:
	content: str
	is_error: bool = False
	"""TodoWrite 可选的结构化清单 → SSE → 前端 dock。"""
	todos: list[dict[str, str]] | None = None
	"""data:image/...;base64,... 供视觉模型查看。"""
	images: list[str] | None = None
	"""结构化工具元数据（例如 rewind operation_id）。"""
	metadata: dict[str, Any] | None = None
	"""桌面 UI 旁路载荷（XeyoUI → SSE xy.ui → 前端分发）。"""
	ui: dict[str, Any] | None = None


@runtime_checkable
class Tool(Protocol):
	"""工具契约。编排 / ask·plan 闸读 is_read_only / is_concurrency_safe。"""

	name: str

	def schema(self) -> dict[str, Any]: ...

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult: ...

	@staticmethod
	def is_read_only() -> bool:
		"""无磁盘/外发/spawn 副作用时为 True；ask/plan 模式只放行只读工具。"""
		...

	@staticmethod
	def is_concurrency_safe() -> bool:
		"""可与其它只读工具同批并发；写 / 外发 / shell 必须 False。"""
		...


@runtime_checkable
class ReadStateAware(Protocol):
	"""需要共享 ReadFileState 的工具（Read / Write / Edit）。"""

	def set_read_file_state(self, state: Any) -> None: ...


@runtime_checkable
class WriteStoreAware(Protocol):
	"""需要 WriteStore 的写路径工具（Write / Edit / Agent）。"""

	def set_write_store(self, store: Any) -> None: ...


@runtime_checkable
class AgentIdAware(Protocol):
	"""需要 agent_id 的会话隔离工具。"""

	def set_agent_id(self, agent_id: str | None) -> None: ...


@runtime_checkable
class RuntimeProviderAware(Protocol):
	"""需要子 agent 运行时注入的工具（Agent）。"""

	def set_runtime_provider(self, provider: Any) -> None: ...


def tool_flag(tool: Any, name: str, *, default: bool = False) -> bool:
	"""安全读取工具上的静态标记（方法或属性）；缺失或异常时回退 default。"""
	fn = getattr(tool, name, None)
	if fn is None:
		return default
	try:
		return bool(fn() if callable(fn) else fn)
	except Exception:
		return default
