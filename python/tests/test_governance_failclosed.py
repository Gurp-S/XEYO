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


# ---------- T25 延伸：键认得、值读不出 = 与坏文件同向（收紧 + 出声）----------


@pytest.mark.parametrize(
	"bad",
	["ask_me", "desny", 123, True, {"on": True}],
	ids=["typo_ask", "transposed_deny", "int", "bool", "dict"],
)
def test_unreadable_bash_value_never_reaches_loose_default(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad: object
) -> None:
	"""核心回归：收紧意图打错，过去静默落到 bash=default（只读命令自动放行）。

	对照臂是坏文件本身：整个文件解析失败 → ask（T25），单个键读不出却 → 宽档。
	"""
	_set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"bash": bad})
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.bash == "ask"
	assert pol.exists and pol.parse_error is None  # 文件仍生效，只该键被收紧
	cwd = str(_work(tmp_path))
	r = evaluate_policy("Bash", {"command": "ls -la"}, cwd=cwd)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "bash_policy_ask"


def test_readable_bash_values_keep_documented_semantics(tmp_path: Path) -> None:
	"""方向控制：修复不许把合法值 / 缺省（键缺失、空值）一起收紧。"""
	from permissions.workspace_policy import load_workspace_policy

	for payload, want in (
		({"bash": "default"}, "default"),
		({"bash": "ask"}, "ask"),
		({"bash": "allow"}, "allow"),
		({"bash": "deny"}, "deny"),
		({"bash": "  ASK  "}, "ask"),
		({"bash": ""}, "default"),
		({"bash": None}, "default"),
		({}, "default"),
	):
		_write_policy(tmp_path, payload)
		assert load_workspace_policy(str(tmp_path)).bash == want, payload


def test_deny_lists_written_as_bare_string_still_deny(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	"""漏方括号（"deny_tools": "Read"）过去整条丢弃 ⇒ deny 静默失效。"""
	_set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"deny_tools": "Read", "deny_commands": "ls"})
	cwd = str(_work(tmp_path))
	t = evaluate_policy("Read", {"file_path": str(tmp_path / "safe.txt")}, cwd=cwd)
	assert t.decision == PermissionDecision.DENY
	assert t.matched_rule == "policy_deny_tool"
	b = evaluate_policy("Bash", {"command": "ls -la"}, cwd=cwd)
	assert b.decision == PermissionDecision.DENY
	assert b.matched_rule == "bash_deny"


def test_allowed_roots_written_as_bare_string_is_honored(tmp_path: Path) -> None:
	import os

	from permissions.workspace_policy import resolve_allowed_roots

	_write_policy(tmp_path, {"allowed_roots": "../extra"})
	roots = resolve_allowed_roots(str(tmp_path))
	assert os.path.abspath(os.path.join(str(tmp_path), "../extra")) in roots


def test_unreadable_write_value_tightens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	_set_audit(monkeypatch, tmp_path)
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	cwd = str(_work(tmp_path))
	# 对照：合法 risk 不收紧（用户模式说话）。
	_write_policy(tmp_path, {"write": "risk"})
	base = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	assert base.matched_rule == "write_risk_allow"
	# 打错的 always → 收紧档 ask，而不是回落到 risk（不收紧）。
	_write_policy(tmp_path, {"write": "alway"})
	r = evaluate_policy(
		"Write", {"file_path": str(tmp_path / "out.txt"), "content": "x"}, cwd=cwd
	)
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "write_confirm_ask"


def test_unreadable_field_is_audited_and_keeps_readable_deny(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	"""坏键必须出声，且不得顺手丢掉同文件里读得出的 deny。"""
	log_path = _set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"bash": "desny", "deny_commands": ["ls"]})
	cwd = str(_work(tmp_path))
	b = evaluate_policy("Bash", {"command": "ls -la"}, cwd=cwd)
	assert b.decision == PermissionDecision.DENY
	assert b.matched_rule == "bash_deny"
	from audit.log import default_audit_log

	events = default_audit_log().query(kind="policy.field_invalid")
	assert events, "值读不出必须产生 policy.field_invalid 审计事件"
	assert events[0].get("field") == "bash"
	assert "ask" in str(events[0].get("action", ""))
	assert log_path.is_file()
	assert "policy.field_invalid" in log_path.read_text(encoding="utf-8")


def test_unreadable_field_absent_when_values_are_clean(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	"""反向自证：合法文件零出声，否则该审计事件会淹掉账本。"""
	log_path = _set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"bash": "ask", "write": "always", "deny_tools": ["Skill"]})
	assert evaluate_policy(
		"Bash", {"command": "ls -la"}, cwd=str(_work(tmp_path))
	).decision == PermissionDecision.ASK
	from audit.log import default_audit_log

	assert not default_audit_log().query(kind="policy.field_invalid")
	assert not log_path.exists() or "policy.field_invalid" not in log_path.read_text(
		encoding="utf-8"
	)


def test_unreadable_numeric_fields_are_audited(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	"""数值键读不出：值留在保守侧（不限额 / 关），但必须出声。"""
	_set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"bash_job_memory_mb": "512MB", "bash_escalate": "three"})
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.bash_job_memory_mb is None
	assert pol.bash_escalate == 0
	from audit.log import default_audit_log

	fields = {
		str(e.get("field"))
		for e in default_audit_log().query(kind="policy.field_invalid")
	}
	assert {"bash_job_memory_mb", "bash_escalate"} <= fields
	# 新事件名的诊断边界必须与 policy.invalid 一致，否则诊断面按未知种类处理。
	from diagnostics.collect import boundary_of

	assert boundary_of("policy.field_invalid") == boundary_of("policy.invalid")


def test_unusable_deny_shape_fails_closed_instead_of_being_dropped(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	"""deny 清单既不是字符串也不是列表 ⇒ 按坏文件处理（收紧 + 审计），不是丢掉 deny 后放行。

	条目本身读不出来（无法凭空补 deny），但本文件的 T25 纪律是"宁可多问"：
	其余档位必须落到 ask，且 `exists` 为假，让这条策略不被误当成"已生效"。
	"""
	log_path = _set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"deny_tools": {"Read": True}})
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.parse_error and "deny_tools" in pol.parse_error
	assert not pol.exists
	assert pol.bash == "ask" and pol.write == "ask"
	cwd = str(_work(tmp_path))
	b = evaluate_policy("Bash", {"command": "ls -la"}, cwd=cwd)
	assert b.decision == PermissionDecision.ASK
	from audit.log import default_audit_log

	events = default_audit_log().query(kind="policy.invalid")
	assert events, "读不出的 deny 形状必须走 policy.invalid 留痕"
	assert log_path.is_file()


def test_readable_deny_list_is_not_invalidated(tmp_path: Path) -> None:
	"""反向自证：合法 deny 列表不得被新分支判成坏文件。"""
	_write_policy(tmp_path, {"deny_tools": ["Read"], "bash": "default"})
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.parse_error is None and pol.exists
	assert pol.deny_tools == ("Read",)
	assert pol.bash == "default"
	cwd = str(_work(tmp_path))
	t = evaluate_policy("Read", {"file_path": str(tmp_path / "safe.txt")}, cwd=cwd)
	assert t.decision == PermissionDecision.DENY


def test_unusable_allowed_roots_only_drops_that_field(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
	"""allowed_roots 形状错丢掉的是**额外可写根**（收紧侧），不该牵动整份文件。"""
	_set_audit(monkeypatch, tmp_path)
	_write_policy(tmp_path, {"allowed_roots": {"a": 1}, "bash": "default"})
	from permissions.workspace_policy import load_workspace_policy

	pol = load_workspace_policy(str(tmp_path))
	assert pol.parse_error is None and pol.exists
	assert pol.allowed_roots == ()
	assert pol.bash == "default"
	from audit.log import default_audit_log

	events = default_audit_log().query(kind="policy.field_invalid")
	assert {str(e.get("field")) for e in events} == {"allowed_roots"}
