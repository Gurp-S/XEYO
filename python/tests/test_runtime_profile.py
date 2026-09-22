"""运行档案的稳定身份和显式接线契约。"""

from __future__ import annotations

from engine.runtime_profile import RuntimeProfile, resolve_runtime_profile


def test_terminal_bench_profile_is_explicit_and_stable() -> None:
	profile = RuntimeProfile.from_name("tb2.1")
	assert profile.name == "terminal-bench-2.1"
	assert profile.execution_backend == "docker"
	assert profile.tool_surface == "minimal"
	assert profile.human_interaction is False
	assert profile.profile_id == RuntimeProfile.from_name("terminal-bench-2.1").profile_id
	assert profile.to_dict()["profile_id"] == profile.profile_id


def test_profile_override_is_not_derived_from_container_only() -> None:
	profile = resolve_runtime_profile("product-local", runtime="docker")
	assert profile.name == "product-local"
	assert profile.execution_backend == "local"
	assert resolve_runtime_profile(runtime="docker").name == "product-docker"


def test_runtime_profile_reaches_engine_snapshot(tmp_path) -> None:  # type: ignore[no-untyped-def]
	from engine.query_engine import QueryEngine
	from tools.echo import EchoTool
	from tools.tool_registry import ToolRegistry

	registry = ToolRegistry(cwd=str(tmp_path))
	registry.register(EchoTool())
	engine = QueryEngine(
		{
			"cwd": str(tmp_path),
			"tools": registry,
			"model_client": object(),  # type: ignore[typeddict-item]
			"session_id": "profile-session",
			"runtime": "docker",
			"runtime_profile": "terminal-bench-2.1",
		}
	)
	snapshot = engine.runtime_snapshot()
	assert snapshot["runtime_profile"]["name"] == "terminal-bench-2.1"
	assert snapshot["context"]["runtime_profile_id"] == snapshot["runtime_profile"]["profile_id"]
	assert snapshot["context"]["tool_surface_id"] == "custom@1"
