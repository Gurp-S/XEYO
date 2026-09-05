"""统一权限规则评估（policy）测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy


def _work(tmp_path: Path) -> Path:
	(tmp_path / "safe.txt").write_text("hello", encoding="utf-8")
	git = tmp_path / ".git"
	git.mkdir()
	(git / "config").write_text("secret", encoding="utf-8")
	return tmp_path


def test_always_allow_tools(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	assert evaluate_policy("echo", {"text": "hi"}, cwd=cwd).allowed
	assert evaluate_policy("TodoWrite", {"todos": []}, cwd=cwd).allowed
	shot = evaluate_policy("Screenshot", {}, cwd=cwd)
	assert shot.decision == PermissionDecision.ASK
	assert shot.matched_rule == "outbound_ask"


def test_send_to_wechat_asks_inside(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	inside = str(tmp_path / "out.png")
	r = evaluate_policy("SendToWeChat", {"path": inside}, cwd=cwd)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "outbound_ask"


def test_send_to_wechat_outside_deny(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	outside = str(tmp_path.parent / "secret.bin")
	r = evaluate_policy("SendToWeChat", {"path": outside}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "outbound_outside_deny"

def test_bash_allow_and_deny(tmp_path: Path) -> None:
	import json

	from permissions.workspace_policy import POLICY_FILENAME, clear_policy_cache

	(tmp_path / POLICY_FILENAME).write_text(
		json.dumps({"bash": "default"}), encoding="utf-8"
	)
	clear_policy_cache()
	cwd = str(_work(tmp_path))
	assert evaluate_policy("Bash", {"command": "echo hi"}, cwd=cwd).allowed
	denied = evaluate_policy("Bash", {"command": "rm -rf /"}, cwd=cwd)
	assert denied.decision == PermissionDecision.DENY
	assert denied.reason == "destructive_root_delete"
	asked = evaluate_policy("Bash", {"command": "python app.py"}, cwd=cwd)
	assert asked.decision == PermissionDecision.ASK
	assert asked.matched_rule == "bash_default_ask"


def test_bash_shipping_default_readonly_autopass(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	# 出厂缺省 bash=default：只读白名单自动放行（不再逐条确认）。
	r = evaluate_policy("Bash", {"command": "echo hi"}, cwd=cwd)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "bash_readonly_allow"


def test_read_allow_inside(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Read", {"file_path": str(tmp_path / "safe.txt")}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW


def test_read_dangerous_path_asks(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Read", {"file_path": str(tmp_path / ".git" / "config")}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ASK
	assert r.prompt is not None
	assert r.matched_rule == "read_ask"


def test_write_inside_default_allows(tmp_path: Path) -> None:
	# 出厂缺省 write=risk + approval=risk：工作区内安全文件自动放行。
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / "out.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule in ("write_risk_allow", "write_auto_allow")


def test_write_risk_policy_allows_safe(tmp_path: Path) -> None:
	import json

	from permissions.workspace_policy import POLICY_FILENAME, clear_policy_cache

	(tmp_path / POLICY_FILENAME).write_text(
		json.dumps({"write": "risk"}), encoding="utf-8"
	)
	clear_policy_cache()
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / "out.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule in ("write_risk_allow", "write_auto_allow")


def test_write_risky_path_asks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	# T12 起 workspace 内 .git/.ssh/.pem 等全部硬 DENY（见
	# test_write_protected_metadata_denies / secret/protected 检查）；
	# ASK 语义由「mode=always 每写必问」分支承载。
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "always")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / "out.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule in ("write_risk_ask", "write_confirm_ask")
	assert r.prompt is not None


def test_write_protected_metadata_denies(tmp_path: Path) -> None:
	# T12：.git/.xeyo/.agents 写从 ASK 收紧为 DENY（带 reason）。
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / ".git" / "x.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "protected_metadata_deny"


def test_write_mode_always_asks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	import json

	from permissions.workspace_policy import POLICY_FILENAME, clear_policy_cache

	(tmp_path / POLICY_FILENAME).write_text(
		json.dumps({"write": "risk"}), encoding="utf-8"
	)
	clear_policy_cache()
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "always")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / "out.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "write_confirm_ask"


def test_write_mode_never_allows_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	import json

	from permissions.workspace_policy import POLICY_FILENAME, clear_policy_cache

	(tmp_path / POLICY_FILENAME).write_text(
		json.dumps({"write": "never"}), encoding="utf-8"
	)
	clear_policy_cache()
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write",
		{"file_path": str(tmp_path / "out.txt"), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "write_auto_allow"


def test_write_secret_path_denies(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	env = tmp_path / ".env"
	env.write_text("SECRET=1", encoding="utf-8")
	r = evaluate_policy(
		"Write",
		{"file_path": str(env), "content": "x"},
		cwd=cwd,
	)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "secret_path_deny"


def test_read_secret_path_denies(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	env = tmp_path / ".env"
	env.write_text("SECRET=1", encoding="utf-8")
	r = evaluate_policy("Read", {"file_path": str(env)}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "secret_path_deny"

def test_permission_mode_contextvar_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
	from permissions.policy import permission_mode, set_permission_mode

	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	set_permission_mode("always")
	try:
		assert permission_mode() == "always"
	finally:
		set_permission_mode(None)
	assert permission_mode() == "risk"


def test_write_outside_deny(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	outside = str(tmp_path.parent / "outside.txt")
	r = evaluate_policy(
		"Write", {"file_path": outside, "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.DENY


def test_unknown_tool_asks(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	r = evaluate_policy("MysteryTool", {}, cwd=cwd)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "unknown_tool_ask"


def test_agent_tool_allows_spawn(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	r = evaluate_policy("Agent", {"desc": "do work"}, cwd=cwd)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "agent_allow"


# ── max 档（never/allow=免确认）对「工作区外」的权限级放宽 ──────────────
# 硬边界（密钥/策略文件/受保护元数据/危险路径）仍由上/下方分支硬拦。


def test_read_outside_max_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	outside = str(tmp_path.parent / "log.txt")
	r = evaluate_policy("Read", {"file_path": outside}, cwd=cwd)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "read_allow"


def test_read_outside_nonmax_denies(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	outside = str(tmp_path.parent / "log.txt")
	r = evaluate_policy("Read", {"file_path": outside}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "read_deny"


def test_write_outside_max_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	outside = str(tmp_path.parent / "out.txt")
	r = evaluate_policy(
		"Write", {"file_path": outside, "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "write_auto_allow"


def test_write_secret_outside_max_denies(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	# max 档也不读取密钥（区外相同，仍被硬拦）。
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	env = tmp_path / ".env"
	env.write_text("SECRET=1", encoding="utf-8")
	r = evaluate_policy("Read", {"file_path": str(env)}, cwd=cwd)
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "secret_path_deny"


def test_bash_write_outside_max_allows(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Bash", {"command": "echo hi > ../outside.log"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "bash_write_allow"


def test_outbound_max_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	r = evaluate_policy("WebSearch", {"query": "x"}, cwd=cwd)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "outbound_max_allow"
	r2 = evaluate_policy("WebFetch", {"url": "https://example.com"}, cwd=cwd)
	assert r2.decision == PermissionDecision.ALLOW
	assert r2.matched_rule == "outbound_max_allow"


def test_outbound_nonmax_asks(tmp_path: Path) -> None:
	cwd = str(_work(tmp_path))
	r = evaluate_policy("WebSearch", {"query": "x"}, cwd=cwd)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "outbound_ask"


def test_bash_exec_fallthrough_max_allows(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	# max 档：既非只读、又非已识别写文件的命令（git push / install / 跑脚本）自动放行。
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	for cmd in ("git push", "npm install", "python app.py", "pip install requests"):
		r = evaluate_policy("Bash", {"command": cmd}, cwd=cwd)
		assert r.decision == PermissionDecision.ALLOW, cmd
		assert r.matched_rule == "bash_max_allow", cmd


def test_bash_exec_fallthrough_nonmax_asks(tmp_path: Path) -> None:
	# 非 max 档（默认 risk）：同样的命令仍要确认。
	cwd = str(_work(tmp_path))
	for cmd in ("git push", "npm install", "python app.py"):
		r = evaluate_policy("Bash", {"command": cmd}, cwd=cwd)
		assert r.decision == PermissionDecision.ASK, cmd
		assert r.matched_rule == "bash_default_ask", cmd


def test_bash_max_still_denies_hard_boundaries(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	# max 档不放松硬边界：根删除 / 关机 / 密钥提及仍 DENY。
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	for cmd in ("rm -rf /", "shutdown /s /t 0"):
		r = evaluate_policy("Bash", {"command": cmd}, cwd=cwd)
		assert r.decision == PermissionDecision.DENY, cmd
	secret = evaluate_policy("Bash", {"command": "type .env"}, cwd=cwd)
	assert secret.decision == PermissionDecision.DENY
