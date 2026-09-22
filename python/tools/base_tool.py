from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from engine.abort import AbortController


ToolStatus = Literal["ok", "error", "pending", "running", "cancelled"]


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
	"""引擎可判定的执行状态；为空时由 is_error 推导，兼容旧构造方式。"""
	status: ToolStatus | str | None = None
	"""稳定错误分类；模型文本仍由 content 承载，调度逻辑读取此字段。"""
	error_kind: str | None = None
	"""是否适合由执行层重试；默认 False，避免错误地重复副作用。"""
	retryable: bool = False
	"""副作用类别：none / write / process / external / unknown。"""
	side_effect: str = "none"
	"""与 ActionJournal 关联的稳定动作 id。"""
	action_id: str | None = None

	def __post_init__(self) -> None:
		if self.status is None:
			self.status = "error" if self.is_error else "ok"
		if self.status == "error":
			self.is_error = True
		if self.is_error and not self.error_kind:
			# 旧工具仍可能只返回 is_error + 文本；至少给执行层一个稳定的
			# “未细分内部错误”类别，避免下游再次解析自然语言或得到 None。
			self.error_kind = "INTERNAL"

	def execution_metadata(self) -> dict[str, Any]:
		"""供事件/审计使用的机器字段；不包含原始参数或秘密。"""
		return {
			"status": self.status or ("error" if self.is_error else "ok"),
			"error_kind": self.error_kind,
			"retryable": bool(self.retryable),
			"side_effect": self.side_effect,
			"action_id": self.action_id,
		}


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
