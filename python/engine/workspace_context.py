"""会话级工作区上下文（WorkspaceContext）。

用 contextvars 把 session 与工作目录强绑定，避免多并发会话读取
`session/cwd.py` 的模块级全局变量而串目录。工具/权限应优先读取
`get_workspace_context()` 中的 cwd，而不是模块全局。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field


@dataclass
class WorkspaceContext:
	"""一次会话/一件任务的权威工作区上下文。"""

	session_id: str
	cwd: str
	allowed_paths: list[str] = field(default_factory=list)
	permission_profile: str = "workspace_write"


_current: contextvars.ContextVar[WorkspaceContext | None] = contextvars.ContextVar(
	"xeyo_workspace", default=None
)


def set_workspace_context(ctx: WorkspaceContext | None) -> None:
	"""在当前 async 上下文设置工作区。None 表示清除。"""
	_current.set(ctx)


def get_workspace_context() -> WorkspaceContext | None:
	return _current.get()


def get_cwd() -> str:
	"""优先返回当前会话上下文的工作目录；无则回退模块全局。"""
	ctx = _current.get()
	if ctx is not None and ctx.cwd:
		return ctx.cwd
	from session.cwd import get_cwd as _legacy

	return _legacy(_skip_context=True)

