"""A0 的边界：零模型调用、只报事实、重复保存要去抖合并。"""

from __future__ import annotations

from pathlib import Path

from diagnostics.experiments import a0


def test_run_makes_no_provider_call_and_never_claims_improvement() -> None:
	result = a0.run(groups={"meta"}, batteries=())
	assert result["mode"] == "a0"
	assert result["provider_calls"] == 0
	assert result["claims"]["model_behaviour_improvement"] is False
	assert result["claims"]["task_success"] is False
	assert result["trace"]["status"] == "skipped"
	# 结论边界必须写在产物里，而不是靠人记得
	assert "A0" in result["claims"]["allowed_conclusion"]
	assert result["coverage_gap"]


def test_surface_changes_carry_mechanical_constraint() -> None:
	rows = a0._changes_to_rows(
		[{"name": "tools/Read", "status": "modified", "group": "tools", "chars_before": 10, "chars_after": 12, "added": 2, "removed": 0}]
	)
	assert rows[0]["mechanical_constraint"].startswith("工具 schema")
	rows2 = a0._changes_to_rows(
		[{"name": "tnow/registry", "status": "added", "group": "tnow", "chars_after": 3}]
	)
	assert "块准入" in rows2[0]["mechanical_constraint"]


def test_markdown_states_it_did_not_run_a_model() -> None:
	text = a0.to_markdown(a0.run(groups={"meta"}, batteries=()))
	assert "provider 调用：**0**" in text


def _root(tmp_path: Path) -> Path:
	# 观察根命名为 prompt/，路径→受影响面的映射规则与真实仓库同一套
	root = tmp_path / "prompt"
	root.mkdir()
	(root / "system_prompt.py").write_text("A = 1\n", encoding="utf-8")
	(root / "pre_llm_inject.py").write_text("B = 2\n", encoding="utf-8")
	(root / "notes.md").write_text("hello\n", encoding="utf-8")
	(root / "keep.json").write_text("{}\n", encoding="utf-8")
	return root


def test_first_scan_pins_baseline_without_events(tmp_path: Path) -> None:
	root = _root(tmp_path)
	out = a0.prompt_file_changes(roots=[root], now=1000.0, debounce_sec=5.0)
	assert out["changed"] is False
	assert out["events"] == []
	assert out["pending"] == []
	assert out["watched_files"] == 3  # .json 不属于提示词文件面


def test_rapid_repeated_saves_merge_into_one_event(tmp_path: Path) -> None:
	root = _root(tmp_path)
	a0.prompt_file_changes(roots=[root], now=1000.0, debounce_sec=5.0)
	target = root / "system_prompt.py"

	target.write_text("A = 2\n", encoding="utf-8")
	first = a0.prompt_file_changes(roots=[root], now=1001.0, debounce_sec=5.0)
	assert first["events"] == []
	assert len(first["pending"]) == 1

	target.write_text("A = 3\n", encoding="utf-8")
	second = a0.prompt_file_changes(roots=[root], now=1002.0, debounce_sec=5.0)
	assert second["events"] == []

	third = a0.prompt_file_changes(roots=[root], now=1010.0, debounce_sec=5.0)
	events = third["events"]
	assert len(events) == 1
	assert events[0]["merged_saves"] == 2
	assert events[0]["path"].endswith("system_prompt.py")
	assert events[0]["affected_surfaces"] == ["system/*"]
	assert events[0]["before_sha"] != events[0]["after_sha"]

	# 结算之后不再重复报同一处变更
	after = a0.prompt_file_changes(roots=[root], now=1099.0, debounce_sec=5.0)
	assert after["events"] == []


def test_revert_to_original_content_produces_no_event(tmp_path: Path) -> None:
	root = _root(tmp_path)
	a0.prompt_file_changes(roots=[root], now=1000.0, debounce_sec=5.0)
	target = root / "pre_llm_inject.py"
	original = target.read_text(encoding="utf-8")
	target.write_text("B = 999\n", encoding="utf-8")
	a0.prompt_file_changes(roots=[root], now=1001.0, debounce_sec=5.0)
	target.write_text(original, encoding="utf-8")
	out = a0.prompt_file_changes(roots=[root], now=1099.0, debounce_sec=5.0)
	assert out["events"] == []
	assert out["pending"] == []


def test_deletion_is_also_debounced_and_reported(tmp_path: Path) -> None:
	root = _root(tmp_path)
	a0.prompt_file_changes(roots=[root], now=1000.0, debounce_sec=5.0)
	(root / "notes.md").unlink()
	pending = a0.prompt_file_changes(roots=[root], now=1001.0, debounce_sec=5.0)
	assert pending["events"] == []
	settled = a0.prompt_file_changes(roots=[root], now=1099.0, debounce_sec=5.0)
	assert [e["change"] for e in settled["events"]] == ["removed"]


def test_state_persists_between_calls(tmp_path: Path) -> None:
	root = _root(tmp_path)
	a0.prompt_file_changes(roots=[root], now=1000.0, debounce_sec=5.0)
	assert Path(a0.watch_path()).is_file()
	out = a0.prompt_file_changes(roots=[root], now=1001.0, debounce_sec=5.0, persist=False)
	assert out["persisted"] is False
