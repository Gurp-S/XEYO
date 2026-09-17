"""隔离 WSC active 适配器的 correctness 契约。

这些测试不访问网络，也不接入 query_loop；它们只验证实验适配器不会把坏的
WSC 结果、坏的 Read 视图或切坏的 tool pair 发送出去。
"""

from __future__ import annotations

from pathlib import Path

from memory.wsc_active import enabled, project_messages
from memory.working import WorkingSnapshot


def _history(pairs: int = 10, size: int = 2_000) -> list[dict]:
	rows: list[dict] = [{"role": "user", "content": "Keep the test target unchanged."}]
	for i in range(pairs):
		uid = f"u{i}"
		rows.append(
			{
				"role": "assistant",
				"content": [
					{
						"type": "tool_use",
						"id": uid,
						"name": "Grep",
						"input": {"query": f"needle-{i}"},
					}
				],
			}
		)
		rows.append(
			{
				"role": "user",
				"content": [
					{
						"type": "tool_result",
						"tool_use_id": uid,
						"content": f"result-{i} " + ("x" * size),
						"is_error": False,
					}
				],
			}
		)
	return rows


def test_active_flag_is_default_off(monkeypatch):
	monkeypatch.delenv("XEYO_WSC_ACTIVE", raising=False)
	assert not enabled()
	monkeypatch.setenv("XEYO_WSC_ACTIVE", "1")
	assert enabled()


def test_active_projection_uses_read_and_does_not_mutate_input(tmp_path: Path):
	rows = _history()
	before = repr(rows)
	result = project_messages(rows, session="active-a", cwd=tmp_path)

	assert result.used_wsc
	assert not result.fallback_reason
	assert repr(rows) == before
	assert result.view_path.startswith(str(tmp_path / ".xeyo_offload"))
	assert result.view_ref == ".xeyo_offload/wsc-active/active-a.txt"
	assert result.messages[0]["name"] == "wsc_snapshot"
	assert "Read(file_path='" in result.messages[0]["content"]
	assert "expand(" not in result.messages[0]["content"]


def test_cross_turn_state_and_cold_are_committed_only_after_success(tmp_path: Path):
	rows = _history()
	first = project_messages(rows, session="active-b", cwd=tmp_path)
	assert first.used_wsc
	assert first.state is not None and first.cold is not None

	rows.extend(
		[
			{"role": "assistant", "content": "The observed facts remain unchanged."},
			{"role": "user", "content": "Continue from the recorded state."},
		]
	)
	second = project_messages(
		rows,
		session="active-b",
		cwd=tmp_path,
		state=first.state,
		cold=first.cold,
	)
	assert second.used_wsc
	assert second.state is not None and second.cold is not None
	assert Path(second.view_path).read_text(encoding="utf-8").count("#node") >= 1
	# 旧视图句柄仍指向同一文件，不能因第二轮重写而换路径。
	assert second.view_path == first.view_path


def test_restart_restores_state_and_cold_sidecar(tmp_path: Path):
	rows = _history()
	first = project_messages(rows, session="active-restart", cwd=tmp_path)
	assert first.used_wsc
	assert (tmp_path / ".xeyo_offload" / "wsc-active" / "active-restart.txt.state.json").is_file()

	rows.extend(
		[
			{"role": "assistant", "content": "A new observed fact was recorded."},
			{"role": "user", "content": "Continue after restart."},
		]
	)
	second = project_messages(
		rows,
		session="active-restart",
		cwd=tmp_path,
		state=None,
		cold=None,
	)
	assert second.used_wsc
	assert second.state is not None and second.cold is not None
	assert len(second.cold.view_blocks) >= len(first.cold.view_blocks)


def test_short_history_falls_back_without_state(tmp_path: Path):
	rows = [{"role": "user", "content": "short"}]
	baseline = [{"role": "system", "content": "current production baseline"}]
	result = project_messages(rows, session="short", cwd=tmp_path, baseline=baseline)
	assert not result.used_wsc
	assert result.fallback_reason == "no_compressible_region"
	assert result.messages == baseline
	assert result.state is None and result.cold is None


def test_wsc_exception_cannot_pollute_prior_cold(monkeypatch, tmp_path: Path):
	import importlib

	first = project_messages(_history(), session="active-c", cwd=tmp_path)
	assert first.used_wsc
	before = first.cold.to_json()

	def fail(*args, **kwargs):
		raise RuntimeError("synthetic WSC failure")

	project_module = importlib.import_module("synaptic.project")
	monkeypatch.setattr(project_module, "project", fail)
	second = project_messages(
		_history(11),
		session="active-c",
		cwd=tmp_path,
		state=first.state,
		cold=first.cold,
	)
	assert not second.used_wsc
	assert second.fallback_reason.startswith("RuntimeError:")
	assert first.cold.to_json() == before


def test_rejected_partial_tool_batch_cannot_rewrite_published_view(tmp_path: Path):
	rows = _history()
	first = project_messages(rows, session="active-d", cwd=tmp_path)
	assert first.used_wsc
	view = Path(first.view_path)
	published = view.read_bytes()

	rows.extend(
		[
			{
				"role": "assistant",
				"content": [
					{"type": "tool_use", "id": "partial-a", "name": "Read", "input": {}},
					{"type": "tool_use", "id": "partial-b", "name": "Read", "input": {}},
				],
			},
			{
				"role": "user",
				"content": [
					{"type": "tool_result", "tool_use_id": "partial-a", "content": "ok"}
				],
			},
		]
	)
	second = project_messages(
		rows,
		session="active-d",
		cwd=tmp_path,
		baseline=[{"role": "system", "content": "the already published C2 baseline"}],
		state=first.state,
		cold=first.cold,
	)

	assert not second.used_wsc
	assert second.fallback_reason == "broken_tool_pair"
	assert second.messages == [{"role": "system", "content": "the already published C2 baseline"}]
	assert view.read_bytes() == published
	assert not Path(str(view) + ".trial").exists()
