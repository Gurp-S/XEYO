"""执行上下文：一次 agent turn 的工作面单一事实源。

以前各层分别从 ``cwd``、``XEYO_DOCKER_CONTAINER``、ContextVar 和 tool 实例
推导运行环境。这样即使每个局部实现都“看起来正确”，也可能出现 host/container
错位。本模块只保存事实，不执行 Docker 或文件操作；后端实现由工具层消费。

``WorkspaceContext`` 在 ``engine.workspace_context`` 中是本类型的兼容别名。保留
旧名字是为了让已有工具和插件不需要一次性迁移。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

RuntimeKind = Literal["local", "docker", "ssh", "unknown"]


@dataclass
class ExecutionContext:
	"""一次 session/turn 的不可猜测执行事实。

	字段保持轻量、可 JSON 化，避免把具体 Docker client 或 asyncio 对象塞进
	ContextVar。``runtime`` 与 ``container_id`` 是路由事实；当 runtime 为
	``local`` 时，工具不得再回退读取一个遗留的进程级 Docker 环境变量。
	"""

	session_id: str
	cwd: str
	allowed_paths: list[str] = field(default_factory=list)
	permission_profile: str = "workspace_write"
	runtime: RuntimeKind = "local"
	container_id: str = ""
	workspace_id: str = ""
	trace_id: str = ""
	runtime_profile_id: str = ""
	tool_surface_id: str = ""
	model_request_id: str = ""
	projection_id: str = ""
	permission_snapshot_id: str = ""
	workspace_revision: str = ""
	deadline_ts: float | None = None
	tool_schema_hash: str = ""
	capability_id: str = ""
	capabilities: dict[str, Any] = field(default_factory=dict)

	@property
	def is_container(self) -> bool:
		return self.runtime == "docker" and bool(self.container_id)

	@property
	def permission_scope(self) -> str:
		"""兼容说明中的名称；权限实现仍使用 permission_profile。"""
		return self.permission_profile

	def snapshot(self) -> dict[str, Any]:
		"""返回不含可变对象的观测快照。"""
		return {
			"session_id": self.session_id,
			"cwd": self.cwd,
			"allowed_paths": list(self.allowed_paths),
			"permission_profile": self.permission_profile,
			"runtime": self.runtime,
			"container_id": self.container_id,
			"workspace_id": self.workspace_id,
			"trace_id": self.trace_id,
			"runtime_profile_id": self.runtime_profile_id,
			"tool_surface_id": self.tool_surface_id,
			"model_request_id": self.model_request_id,
			"projection_id": self.projection_id,
			"permission_snapshot_id": self.permission_snapshot_id,
			"workspace_revision": self.workspace_revision,
			"deadline_ts": self.deadline_ts,
			"tool_schema_hash": self.tool_schema_hash,
			"capability_id": self.capability_id,
			"capabilities": dict(self.capabilities),
		}

	def evolve(self, **updates: Any) -> "ExecutionContext":
		"""以显式更新生成新上下文，避免工具自行拼接路由字段。"""
		return replace(self, **updates)


# 源码和外部扩展有时直接从本模块导入旧名称；保留同一类型身份。
WorkspaceContext = ExecutionContext


__all__ = ["ExecutionContext", "WorkspaceContext", "RuntimeKind"]
