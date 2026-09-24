"""A2 隔离任务配对的验收：不合格就停在 A0/A1，合格则两臂起点必须逐字节一致。

对应设计文档 §11 阶段四的验收条：两臂起始清单一致、互不污染、原工作区未改、
外部副作用受限、verifier 版本一致、无效运行也记账。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from diagnostics.experiments import a2


def _workspace(tmp_path: Path) -> Path:
	root = tmp_path / "ws"
	(root / "pkg").mkdir(parents=True)
	(root / "a.py").write_text("x = 1\n", encoding="utf-8")
	(root / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
	return root


def _spec(root: Path, **over) -> dict:
	spec = {
		"task_id": "fix-bug",
		"tools": ["Read", "Write"],
		"isolation": {
			"files": "throwaway_copy",
			"processes": "subprocess_isolated",
			"external": "none",
		},
		"workspace": {"root": str(root), "arm_root": str(root.parent / "arms")},
		"verifier": {"name": "pytest", "command": "pytest -q", "allowed_commands": ["pytest -q"]},
		"runtime_profile": {"name": "ci", "human_interaction": False},
	}
	spec.update(over)
	return spec


# ---------- 准入闸门 ----------


def test_eligible_spec_passes_gate(tmp_path) -> None:
	root = _workspace(tmp_path)
	verdict = a2.eligibility(_spec(root))
	assert verdict["ok"] is True, verdict["missing"]
	assert verdict["missing"] == []
	assert verdict["mode"] == a2.MODE


def test_bare_boolean_is_not_proof_of_isolation(tmp_path) -> None:
	"""隔离档位必须是可核对的机制名，裸 True 不算证明。"""
	root = _workspace(tmp_path)
	spec = _spec(root, isolation={"files": "true", "processes": "true", "external": "true"})
	missing = a2.eligibility(spec)["missing"]
	assert any(m.startswith("file_isolation_not_proven") for m in missing)
	assert any(m.startswith("external_side_effects_not_proven") for m in missing)


def test_worktree_only_or_temp_cwd_is_not_enough(tmp_path) -> None:
	root = _workspace(tmp_path)
	spec = _spec(
		root,
		isolation={"files": "temp_cwd", "processes": "subprocess_isolated", "external": "none"},
	)
	assert any(m.startswith("file_isolation_not_proven:temp_cwd") for m in a2.eligibility(spec)["missing"])


def test_external_write_tool_excluded_by_default(tmp_path) -> None:
	root = _workspace(tmp_path)
	spec = _spec(root, tools=["Read", "WebFetch"])
	missing = a2.eligibility(spec)["missing"]
	assert "external_effect_tool_excluded:WebFetch" in missing


def test_process_tool_needs_process_isolation(tmp_path) -> None:
	root = _workspace(tmp_path)
	spec = _spec(root, tools=["Bash"], isolation={"files": "throwaway_copy", "processes": "in_process", "external": "none"})
	missing = a2.eligibility(spec)["missing"]
	assert "process_effect_tool_needs_isolation:Bash" in missing


def test_ignored_dependency_not_supplied_is_refused(tmp_path) -> None:
	root = _workspace(tmp_path)
	spec = _spec(root, depends_on_ignored=["fixtures/huge.bin"])
	assert "ignored_dependency_not_supplied:fixtures/huge.bin" in a2.eligibility(spec)["missing"]
	supplied = _spec(root, depends_on_ignored=["fixtures/huge.bin"], supplied_ignored=["fixtures/huge.bin"])
	assert not any(m.startswith("ignored_dependency_not_supplied") for m in a2.eligibility(supplied)["missing"])


def test_original_workspace_cannot_be_an_arm(tmp_path) -> None:
	root = _workspace(tmp_path)
	spec = _spec(root)
	spec["workspace"]["arm_root"] = str(root)
	assert "original_workspace_used_as_arm" in a2.eligibility(spec)["missing"]


def test_verifier_must_be_declared_and_allowed(tmp_path) -> None:
	root = _workspace(tmp_path)
	no_verifier = _spec(root)
	no_verifier["verifier"] = {}
	assert "verifier_missing" in a2.eligibility(no_verifier)["missing"]

	name_only = _spec(root)
	name_only["verifier"] = {"name": "pytest"}
	assert "verifier_command_missing" in a2.eligibility(name_only)["missing"]

	not_allowed = _spec(root)
	not_allowed["verifier"] = {"name": "pytest", "command": "rm -rf /", "allowed_commands": ["pytest -q"]}
	assert "verifier_command_not_allowed" in a2.eligibility(not_allowed)["missing"]


def test_interactive_runtime_profile_is_refused(tmp_path) -> None:
	root = _workspace(tmp_path)
	spec = _spec(root, runtime_profile={"name": "product-local", "human_interaction": True})
	assert "runtime_profile_interactive" in a2.eligibility(spec)["missing"]


# ---------- 两臂等价与原工作区不被污染 ----------


def test_two_copies_start_identical_and_source_untouched(tmp_path) -> None:
	root = _workspace(tmp_path)
	before = a2.file_inventory(root)
	out = a2.export_copies(root, dest_parent=tmp_path / "arms")
	assert out["identical"] is True
	assert out["source_matches_copies"] is True
	assert out["digests"]["A"] == out["digests"]["B"]
	assert Path(out["copies"]["A"]["path"]).is_dir() and Path(out["copies"]["B"]["path"]).is_dir()
	assert out["copies"]["A"]["inventory"]["count"] == out["copies"]["B"]["inventory"]["count"] == 2
	# 源工作区逐条目不变
	assert a2.inventory_digest(a2.file_inventory(root)) == a2.inventory_digest(before)
	# 两臂各自确实拿到同一份文件内容
	for arm in ("A", "B"):
		arm_root = Path(out["copies"][arm]["path"])
		assert (arm_root / "a.py").read_text(encoding="utf-8") == "x = 1\n"
		assert (arm_root / "pkg" / "b.py").read_text(encoding="utf-8") == "y = 2\n"


def test_editing_one_arm_does_not_touch_the_other(tmp_path) -> None:
	root = _workspace(tmp_path)
	out = a2.export_copies(root, dest_parent=tmp_path / "arms")
	arm_a = Path(out["copies"]["A"]["path"])
	arm_b = Path(out["copies"]["B"]["path"])
	(arm_a / "a.py").write_text("x = 999\n", encoding="utf-8")
	assert a2.inventory_digest(a2.file_inventory(arm_a)) != a2.inventory_digest(a2.file_inventory(arm_b))
	assert (arm_b / "a.py").read_text(encoding="utf-8") == "x = 1\n"
	assert (root / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_inventory_is_bounded_and_reports_truncation(tmp_path) -> None:
	root = _workspace(tmp_path)
	inv = a2.file_inventory(root, cap=1)
	assert inv["count"] <= 1
	assert inv["truncated"] is True


# ---------- 每臂环境隔离 ----------


def test_arm_env_isolates_all_state_dirs(tmp_path) -> None:
	env = a2.arm_env(experiment_home=tmp_path / "home", arm="A")
	assert Path(env["XEYO_HOME"]) == tmp_path / "home" / "A"
	for key in ("XEYO_DATA_DIR", "XEYO_SESSIONS_DIR", "XEYO_USAGE_DIR", "XEYO_AUDIT_LOG", "XEYO_DIAGNOSTICS_DIR"):
		assert env[key].startswith(str(tmp_path / "home" / "A")), key
	# 两臂路径必须互不相同
	env_b = a2.arm_env(experiment_home=tmp_path / "home", arm="B")
	assert env["XEYO_SESSIONS_DIR"] != env_b["XEYO_SESSIONS_DIR"]


def test_worker_is_a_separate_process_entrypoint() -> None:
	argv = a2.arm_argv("spec.json")
	assert argv[-3:] == ["-m", "diagnostics.experiments.worker", "--spec"] or "--spec" in argv
	assert "diagnostics.experiments.worker" in argv


# ---------- verifier 与配对结果 ----------


def _exit_script(root: Path, code: int) -> str:
	"""写一个只退出指定码的脚本；用相对路径调用。

	``verifier_argv`` 在 Windows 上会包成 ``cmd /c <整串>``，带引号的绝对路径会被
	嵌套引号切坏（表现为 python 打不开文件、退出码 2），相对路径 + cwd 才可信。
	"""
	script = root / f"_v{code}.py"
	script.write_text("\n".join(("import sys", f"sys.exit({code})", "")), encoding="utf-8")
	return f"python _v{code}.py"


def test_run_verifier_records_exit_and_version(tmp_path) -> None:
	root = _workspace(tmp_path)
	res = a2.run_verifier({"name": "pytest", "command": _exit_script(root, 0), "version": "v1"}, cwd=str(root))
	assert res["ran"] is True
	assert res["passed"] is True
	assert res["exit_code"] == 0
	assert res["verifier_version"] == "v1"


def test_run_verifier_not_executed_is_not_a_pass() -> None:
	res = a2.run_verifier({"name": "pytest", "command": ""}, cwd=".")
	assert res["ran"] is False
	assert res["exit_code"] is None
	# 未运行绝不给出"通过"，也不把退出码补成 0
	assert res.get("passed") is not True


def test_failed_verifier_is_recorded_as_failed(tmp_path) -> None:
	root = _workspace(tmp_path)
	res = a2.run_verifier({"name": "pytest", "command": _exit_script(root, 4)}, cwd=str(root))
	assert res["ran"] is True and res["passed"] is False and res["exit_code"] == 4


def test_compare_arms_keeps_invalid_runs_and_reports_pairing(tmp_path) -> None:
	root = _workspace(tmp_path)
	cmp = a2.compare_arms({"A": {"passed": True, "cost_cny": 0.01}, "B": {"passed": False, "cost_cny": 0.02}})
	pairing = cmp["pairing"]
	assert pairing["a_only_pass"] == 1 and pairing["pairs"] == 1
	# 不合成掩盖退步的总分
	assert cmp["blended_score"] is None

	invalid = a2.compare_arms({"A": {"invalid": True, "cost_cny": 0.03}, "B": {"passed": False, "cost_cny": 0.04}})
	assert invalid["pairing"]["invalid"] == 1
	assert invalid["pairing"]["both_fail"] == 0, "无效运行不得被算成任务失败"
