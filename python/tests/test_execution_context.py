from __future__ import annotations

from engine.execution_context import ExecutionContext
from engine.workspace_context import (
	WorkspaceContext,
	bind_workspace_context,
	get_execution_context,
	get_workspace_context,
	set_workspace_context,
	update_execution_context,
)
from tools.container_routing import current_container, set_container_override
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


def test_workspace_context_is_execution_context_compatibility_alias() -> None:
	ctx = WorkspaceContext(
		session_id="s",
		cwd="/workspace",
		runtime="docker",
		container_id="c1",
		workspace_id="w1",
		trace_id="t1",
	)
	assert isinstance(ctx, ExecutionContext)
	set_workspace_context(ctx)
	try:
		assert get_workspace_context() is ctx
		assert get_execution_context() is ctx
		assert current_container() == "c1"
	finally:
		set_workspace_context(None)


def test_local_execution_context_masks_stale_process_container(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_DOCKER_CONTAINER", "stale-container")
	set_container_override("")
	set_workspace_context(
		ExecutionContext(session_id="s", cwd="/workspace", runtime="local")
	)
	try:
		assert current_container() == ""
	finally:
		set_workspace_context(None)
		set_container_override("")


def test_downstream_container_surfaces_keep_local_mask(monkeypatch) -> None:
	"""下游路由层不能在 current_container 之后恢复 stale env。"""
	monkeypatch.setenv("XEYO_DOCKER_CONTAINER", "stale-container")
	set_container_override("")
	set_workspace_context(
		ExecutionContext(session_id="s", cwd="/workspace", runtime="local")
	)
	try:
		from tools import container_fs, exec_channel

		assert container_fs.active_container() == ""
		assert exec_channel.active_container() == ""
	finally:
		set_workspace_context(None)
		set_container_override("")


def test_downstream_surfaces_keep_legacy_env_fallback_without_context(monkeypatch) -> None:
	"""无 ExecutionContext 的旧 CLI/单 trial 路径仍可用 env 回退。"""
	from tools import container_fs, exec_channel

	monkeypatch.setenv("XEYO_DOCKER_CONTAINER", "legacy-container")
	set_container_override("")
	set_workspace_context(None)
	assert container_fs.active_container() == "legacy-container"
	assert exec_channel.active_container() == "legacy-container"


def test_bind_workspace_context_restores_parent() -> None:
	set_workspace_context(ExecutionContext(session_id="outer", cwd="/outer"))
	try:
		inner = ExecutionContext(session_id="inner", cwd="/inner")
		with bind_workspace_context(inner):
			assert get_execution_context() is inner
		assert get_execution_context() is not None
		assert get_execution_context().session_id == "outer"
	finally:
		set_workspace_context(None)


def test_trace_fields_update_on_the_bound_execution_context() -> None:
	ctx = ExecutionContext(session_id="trace", cwd="/workspace")
	set_workspace_context(ctx)
	try:
		assert update_execution_context(model_request_id="m1", projection_id="p1") is ctx
		assert ctx.snapshot()["model_request_id"] == "m1"
		assert ctx.snapshot()["projection_id"] == "p1"
	finally:
		set_workspace_context(None)


def test_query_engine_runtime_snapshot_has_one_reading_surface(tmp_path) -> None:  # type: ignore[no-untyped-def]
	from engine.query_engine import QueryEngine

	registry = ToolRegistry(cwd=str(tmp_path))
	registry.register(EchoTool())
	engine = QueryEngine(
		{
			"cwd": str(tmp_path),
			"tools": registry,
			"model_client": object(),  # type: ignore[typeddict-item]
			"session_id": "snapshot-session",
		}
	)

	snapshot = engine.runtime_snapshot()
	assert snapshot["session_id"] == "snapshot-session"
	assert snapshot["turn_active"] is False
	assert snapshot["context"]["cwd"] == str(tmp_path.resolve())
	assert snapshot["budget"]["lifecycle"]["phase"] == "running"
	assert snapshot["jobs"] == []


def test_default_engine_accepts_explicit_runtime_facts(tmp_path) -> None:  # type: ignore[no-untyped-def]
	from engine.query_engine import build_default_engine

	engine = build_default_engine(
		cwd=str(tmp_path),
		model_backend="fake",
		runtime="docker",
		container_id="container-1",
		workspace_id="workspace-1",
	)

	assert engine.config["runtime"] == "docker"
	assert engine.config["container_id"] == "container-1"
	assert engine.config["workspace_id"] == "workspace-1"
