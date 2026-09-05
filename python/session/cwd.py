"""
会话工作目录 shim。

权威 cwd 是 WorkspaceContext / SessionState / ToolRegistry，不是模块全局。
``set_cwd`` 仅解析路径；测试可用 ``reset_cwd_for_tests`` 写入回退值。
"""

from __future__ import annotations

import os
from pathlib import Path

from session.workspace_path import resolve_physical_cwd

# 测试回退；生产路径不应依赖。
_cwd: str | None = None
_original_cwd: str | None = None


def get_original_cwd() -> str:
	if _original_cwd:
		return _original_cwd
	return get_cwd(_skip_context=True)


def get_cwd(*, _skip_context: bool = False) -> str:
	if not _skip_context:
		try:
			from engine.workspace_context import get_workspace_context

			ctx = get_workspace_context()
			if ctx is not None and ctx.cwd:
				return ctx.cwd
		except Exception:
			pass
	if _cwd:
		return _cwd
	try:
		return os.getcwd()
	except OSError:
		return str(Path.cwd())


def set_cwd(
	path: str,
	relative_to: str | None = None,
	*,
	sync_os: bool = False,
	set_as_original: bool = False,
) -> str:
	"""解析并校验路径。默认不写入模块全局（并发会话互不覆盖）。

	``set_as_original=True`` 时写入测试回退 ``_cwd`` / ``_original_cwd``。
	"""
	global _cwd, _original_cwd
	base = relative_to if relative_to is not None else get_cwd()
	physical = resolve_physical_cwd(path, relative_to=base)
	_cwd = physical
	if set_as_original or _original_cwd is None:
		_original_cwd = physical
	if sync_os:
		os.chdir(physical)
	return physical


def reset_cwd_for_tests(path: str | None = None) -> None:
	global _cwd, _original_cwd
	if path is None:
		_cwd = None
		_original_cwd = None
		return
	set_cwd(path, set_as_original=True)
