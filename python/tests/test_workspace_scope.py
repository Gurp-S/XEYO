"""WorkspaceContext 上下文隔离测试。"""

from __future__ import annotations

import contextvars
import os

from engine.workspace_context import (
	WorkspaceContext,
	get_cwd,
	get_workspace_context,
	set_workspace_context,
)


def test_default_is_none() -> None:
	set_workspace_context(None)
	assert get_workspace_context() is None


def test_set_fresh_context() -> None:
	ctx = WorkspaceContext(session_id="s", cwd="C:/workspace")
	set_workspace_context(ctx)
	got = get_workspace_context()
	assert got is not None
	assert got.session_id == "s"
	assert got.cwd == "C:/workspace"
	set_workspace_context(None)


def test_inner_set_does_not_leak() -> None:
	set_workspace_context(None)

	def _inner() -> str:
		set_workspace_context(WorkspaceContext(session_id="b", cwd="C:/b"))
		got = get_workspace_context()
		assert got is not None
		return got.session_id

	assert contextvars.copy_context().run(_inner) == "b"
	# 外层未受影响
	assert get_workspace_context() is None


def test_get_cwd_prefers_context() -> None:
	set_workspace_context(WorkspaceContext(session_id="s", cwd="C:/ctx"))
	assert get_cwd() == "C:/ctx"
	set_workspace_context(None)
	assert isinstance(get_cwd(), str)


def test_get_cwd_without_context_ignores_unrelated_tmp(tmp_path) -> None:
	from session.cwd import reset_cwd_for_tests

	set_workspace_context(None)
	reset_cwd_for_tests()
	got = get_cwd()
	assert isinstance(got, str)
	# 无 context 时不得「碰巧」等于某个未绑定的临时仓。
	assert os.path.realpath(got) != os.path.realpath(tmp_path)


def test_default_permission_context_prefers_workspace() -> None:
	from permissions.filesystem import default_permission_context

	set_workspace_context(
		WorkspaceContext(
			session_id="s",
			cwd="C:/workspace",
			allowed_paths=["C:/workspace", "C:/ext"],
		)
	)
	ctx = default_permission_context()
	assert ctx.cwd == os.path.abspath(os.path.expanduser("C:/workspace"))
	assert any(
		p == os.path.abspath(os.path.expanduser("C:/ext"))
		for p in ctx.allowed_working_paths
	)
	set_workspace_context(None)
