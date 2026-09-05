"""T25/T26 治理 fail-closed 测试：坏配置收紧可见 + 权限单向性。

- T26：仓库策略（.xeyo-policy.json）只能收紧用户审批，不能放宽（审计排名#2）。
- T25：坏 policy → 收紧默认 + 审计可见 + exists=False；坏 settings.json → keep-last-good。
"""

from __future__ import annotations

import json
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


def _write_policy(tmp_path: Path, data: object) -> None:
	p = tmp_path / ".xeyo-policy.json"
	p.write_text(
		json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data,
		encoding="utf-8",
	)
	from permissions.workspace_policy import clear_policy_cache

	clear_policy_cache()


def _set_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
	from audit.log import reset_default_audit_log

	log_path = tmp_path / "audit.jsonl"
	monkeypatch.setenv("XEYO_AUDIT_LOG", str(log_path))
	reset_default_audit_log()
	return log_path


# ---------- T26 权限单向性矩阵 ----------


def test_policy_never_cannot_widen_user_always(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	# 核心回归：仓库策略 write:never 不得把用户 always（每写必问）放宽为自动放行。
	_write_policy(tmp_path, {"write": "never"})
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "always")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "write_confirm_ask"


def test_policy_never_keeps_user_never(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	# 用户本就自动放行：策略 never 无变化（no-op），行为与无策略一致。
	_write_policy(tmp_path, {"write": "never"})
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "write_auto_allow"


def test_policy_ask_does_not_tighten_auto_write_mode(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	# 最高档（never/allow）豁免：repo 策略 write:"ask" 的收紧不反向 override 最高权限
	# （见 permissions/policy.py:1380-1386，防止 smoke-test #1：最高权限仍每写必弹确认）。
	# 故 never 模式下安全写自动放行。
	_write_policy(tmp_path, {"write": "ask"})
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "write_auto_allow"


def test_policy_never_with_default_mode_no_widening(tmp_path: Path) -> None:
	# 默认（risk）模式下，策略 never 不再改变结果来源：决策仍由用户模式给出。
	_write_policy(tmp_path, {"write": "never"})
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	# risk 模式对安全写自动放行（用户侧默认），但 matched_rule 必须是用户路径
	# write_risk_allow，而不是被仓库策略放宽出来的 write_auto_allow。
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "write_risk_allow"


# ---------- T25 坏配置 fail-closed ----------


def test_broken_policy_falls_back_tight_and_audits(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	log_path = _set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, '{"write": "never", "bash": "allow",')  # 截断 JSON
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.parse_error and "unreadable" in pol.parse_error
	assert not pol.exists  # 坏文件不算生效策略
	# 回退收紧默认
	assert pol.write == "ask"
	assert pol.bash == "ask"
	assert pol.remote_bash == "ask"
	# 关键：坏策略回退为收紧默认（write=ask）。但最高档（never）豁免 write:ask 收紧
	# （policy.py:1380-1386，防止最高权限仍每写必弹确认），故 never 下安全写仍自动
	# 放行——fail-closed 体现在策略文档默认值与审计，而非把用户最高权限反向收紧。
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	cwd = str(_work(tmp_path))
	r = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "write_auto_allow"
	# bash:allow 意图丢失 → 回退默认 ask：非白名单命令必须 ASK，而非放行。
	b = evaluate_policy("Bash", {"command": "python app.py"}, cwd=cwd)
	assert b.decision == PermissionDecision.ASK
	# 审计可见
	from audit.log import default_audit_log

	events = default_audit_log().query(kind="policy.invalid")
	assert events, "坏 policy 必须产生 policy.invalid 审计事件"
	assert events[0].get("kind") == "policy.invalid"
	assert "ask" in str(events[0].get("action", ""))
	_ = log_path


def test_nonobject_policy_invalid(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	_set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, [1, 2, 3])
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.parse_error == "not a JSON object"
	assert not pol.exists


def test_missing_policy_clean(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	_set_audit(monkeypatch, tmp_path)
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.parse_error is None
	assert not pol.exists
	assert pol.write == "risk"
	assert pol.bash == "default"
	from audit.log import default_audit_log

	assert not default_audit_log().query(kind="policy.invalid")


def test_settings_keep_last_good(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	log_path = _set_audit(monkeypatch, tmp_path)
	from extension import config as ext_config

	monkeypatch.setattr(ext_config, "_home_root", lambda: tmp_path / "home")
	home = tmp_path / "home" / "settings.json"
	home.parent.mkdir(parents=True, exist_ok=True)
	good = {"enabled_extensions": True, "plugins": {"p1": {"enabled": True}}}
	home.write_text(json.dumps(good), encoding="utf-8")
	cfg = ext_config.load_ext_config(None)
	assert cfg.enabled_extensions
	assert cfg.plugin_enabled("p1")

	# 坏化（截断 JSON）→ keep-last-good
	home.write_text('{"enabled_extensions":', encoding="utf-8")
	cfg2 = ext_config.load_ext_config(None)
	assert cfg2.enabled_extensions
	assert cfg2.plugin_enabled("p1")

	from audit.log import default_audit_log

	events = default_audit_log().query(kind="config.invalid")
	assert events
	assert events[0].get("action") == "keep_last_good"

	# 删除 → 回退默认（主开关关，方向安全）
	home.unlink()
	cfg3 = ext_config.load_ext_config(None)
	assert not cfg3.enabled_extensions
