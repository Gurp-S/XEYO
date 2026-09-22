"""执行上下文的兼容入口。

``WorkspaceContext`` 现在是 ``ExecutionContext`` 的兼容别名。旧调用方仍可
按原名字导入；新代码应把 session、runtime、container、cwd、权限和 deadline
视为同一个上下文，而不是重新读取环境变量。
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from collections.abc import Iterator

from engine.execution_context import ExecutionContext, WorkspaceContext


_current: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
	"xeyo_workspace", default=None
)


def set_workspace_context(ctx: ExecutionContext | None) -> None:
	"""在当前 async 上下文设置工作区。None 表示清除。"""
	_current.set(ctx)


def get_workspace_context() -> ExecutionContext | None:
	return _current.get()


def get_execution_context() -> ExecutionContext | None:
	"""新的单一事实源入口；与旧的 get_workspace_context 同一对象。"""
	return _current.get()


def update_execution_context(**updates: object) -> ExecutionContext | None:
	"""更新当前 turn 的机器事实，保持所有消费者看到同一上下文对象。"""
	ctx = _current.get()
	if ctx is None:
		return None
	for key, value in updates.items():
		if hasattr(ctx, key):
			setattr(ctx, key, value)
	return ctx


@contextmanager
def bind_workspace_context(ctx: ExecutionContext | None) -> Iterator[ExecutionContext | None]:
	"""临时绑定上下文并在退出时恢复父上下文。"""
	token = _current.set(ctx)
	try:
		yield ctx
	finally:
		_current.reset(token)


def get_cwd() -> str:
	"""优先返回当前会话上下文的工作目录；无则回退模块全局。"""
	ctx = _current.get()
	if ctx is not None and ctx.cwd:
		return ctx.cwd
	from session.cwd import get_cwd as _legacy

	return _legacy(_skip_context=True)


__all__ = [
	"ExecutionContext",
	"WorkspaceContext",
	"bind_workspace_context",
	"get_cwd",
	"get_execution_context",
	"update_execution_context",
	"get_workspace_context",
	"set_workspace_context",
]

