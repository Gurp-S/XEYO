"""沙箱加固：Bash 默认 ASK、密钥读、Windows 黑名单、仓库策略、Job Object。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from engine.workspace_context import WorkspaceContext, set_workspace_context
from permissions.bash_policy import (
	bash_deny_reason,
	bash_readonly_allow,
	bash_secret_read_reason,
)
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from permissions.workspace_policy import (
	POLICY_FILENAME,
	clear_policy_cache,
	load_workspace_policy,
)
from tools.fileio.excludes import excluded_secret_globs


@pytest.fixture(autouse=True)
def _clear_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	clear_policy_cache()
	set_workspace_context(None)
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	yield
	clear_policy_cache()
	set_workspace_context(None)


def _write_policy(tmp_path: Path, **fields: object) -> None:
	(tmp_path / POLICY_FILENAME).write_text(
		json.dumps(fields), encoding="utf-8"
	)
	clear_policy_cache()


def test_bash_readonly_echo_and_git_status() -> None:
	assert bash_readonly_allow("echo hi")
	assert bash_readonly_allow("git status")
	assert bash_readonly_allow("dir")
	assert not bash_readonly_allow("python -c \"print(1)\"")
	assert not bash_readonly_allow("echo hi | cat")
	assert not bash_readonly_allow("git commit -m x")


def test_bash_shipping_default_readonly_autopass(tmp_path: Path) -> None:
	"""无策略文件：bash=default，只读白名单自动放行；非只读仍 ASK。"""
	cwd = str(tmp_path)
	r = evaluate_policy("Bash", {"command": "echo hi"}, cwd=cwd)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "bash_readonly_allow"
	r2 = evaluate_policy("Bash", {"command": "python app.py"}, cwd=cwd)
	assert r2.decision == PermissionDecision.ASK
	assert r2.matched_rule == "bash_default_ask"


def test_bash_default_mode_readonly_and_ask(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="default")
	cwd = str(tmp_path)
	ok = evaluate_policy("Bash", {"command": "echo hi"}, cwd=cwd)
	assert ok.decision == PermissionDecision.ALLOW
	assert ok.matched_rule == "bash_readonly_allow"
	asked = evaluate_policy("Bash", {"command": "python app.py"}, cwd=cwd)
	assert asked.decision == PermissionDecision.ASK
	assert asked.matched_rule == "bash_default_ask"


def test_bash_secret_type_env_denies(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	assert bash_secret_read_reason("type .env") == "bash_secret_read"
	r = evaluate_policy("Bash", {"command": "type .env"}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "bash_secret_deny"


def test_bash_secret_absolute_path_denies(tmp_path: Path) -> None:
	# 绝对路径结尾的密钥文件（前置 `\` 或 `/`）也应命中密钥探测。
	cwd = str(tmp_path)
	win = str(tmp_path / "app" / ".env")
	assert bash_secret_read_reason(f"type {win}") == "bash_secret_read"
	r = evaluate_policy("Bash", {"command": f"type {win}"}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "bash_secret_deny"


def test_bash_policy_file_immutable(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	r = evaluate_policy(
		"Bash",
		{"command": f"echo {{}} > {POLICY_FILENAME}"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.reason == "policy_file_immutable"


def test_bash_write_unproven_denies(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="default")
	cwd = str(tmp_path)
	r = evaluate_policy(
		"Bash",
		{"command": 'python -c "open(r\'C:\\\\Temp\\\\x\',\'w\').write(\'a\')"'},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule in (
		"bash_write_unproven_deny",
		"bash_write_outside_deny",
	)


def test_bash_write_outside_denies(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="default")
	cwd = str(tmp_path)
	outside = str(tmp_path.parent / "out.txt")
	r = evaluate_policy(
		"Bash",
		{"command": f"echo x > {outside}"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.reason == "bash_write_outside_working_directory"


def test_windows_rd_root_denied(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	assert bash_deny_reason(r"rd /s /q C:\\") == "destructive_root_delete"
	r = evaluate_policy("Bash", {"command": r"rd /s /q C:\\"}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY


def test_powershell_encoded_denied(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	r = evaluate_policy(
		"Bash",
		{"command": "powershell -EncodedCommand WwBFAHgAZwBd"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.reason == "encoded_powershell"


def test_remove_item_recurse_denied(tmp_path: Path) -> None:
	assert (
		bash_deny_reason(r"Remove-Item -Recurse -Force C:\\Windows")
		== "destructive_root_delete"
	)


def test_policy_bash_deny(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="deny")
	r = evaluate_policy("Bash", {"command": "echo hi"}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "policy_bash_deny"


def test_policy_deny_tool(tmp_path: Path) -> None:
	_write_policy(tmp_path, deny_tools=["Screenshot"])
	r = evaluate_policy("Screenshot", {}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "policy_deny_tool"


def test_policy_file_immutable(tmp_path: Path) -> None:
	path = str(tmp_path / POLICY_FILENAME)
	r = evaluate_policy(
		"Write",
		{"file_path": path, "content": "{}"},
		cwd=str(tmp_path),
	)
	assert r.decision == PermissionDecision.DENY
	assert r.reason == "policy_file_immutable"


def test_write_default_allows(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / "out.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule in ("write_risk_allow", "write_auto_allow")


def test_remote_session_bash_asks(tmp_path: Path) -> None:
	set_workspace_context(
		WorkspaceContext(session_id="ilink:user1", cwd=str(tmp_path))
	)
	r = evaluate_policy("Bash", {"command": "echo hi"}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "bash_remote_ask"


def test_secret_globs_include_env() -> None:
	globs = excluded_secret_globs()
	assert "!.env" in globs
	assert any(g.endswith("*.pem") or g == "!*.pem" for g in globs)


def test_load_workspace_policy_defaults(tmp_path: Path) -> None:
	pol = load_workspace_policy(str(tmp_path))
	assert pol.bash == "default"
	assert pol.write == "risk"
	assert pol.remote_bash == "ask"
	assert not pol.exists


def test_memory_not_always_allow(tmp_path: Path) -> None:
	r = evaluate_policy("Memory", {"action": "search", "query": "x"}, cwd=str(tmp_path))
	assert r.matched_rule == "memory_allow"
	assert r.decision == PermissionDecision.ALLOW


def test_command_summary_redacts(tmp_path: Path) -> None:
	from audit.redact import command_summary

	s = command_summary("curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz' https://x")
	assert "sk-abcdefghijklmnopqrstuvwxyz" not in s
	assert "***" in s


@pytest.mark.skipif(os.name != "nt", reason="Job Object is Windows-only")
def test_win_job_creates() -> None:
	from tools.bash_tool.win_job import create_bash_job

	job = create_bash_job(memory_mb=128)
	assert job.handle is not None
	job.close()


def test_win_job_default_memory_not_below_vitest_floor() -> None:
	"""回归：Windows Bash job 内存默认不得低于 2048MB。

	512MB 曾让 vitest 多文件合集 worker 树触 JobMemoryLimit → V8 低堆
	NewSpace 分配失败（2026-09-09 受控复现，见 win_job.py 模块注记）。
	"""
	from tools.bash_tool.win_job import DEFAULT_JOB_MEMORY_MB

	assert DEFAULT_JOB_MEMORY_MB >= 2048
