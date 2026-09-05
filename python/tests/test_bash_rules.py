"""T7 bash 前缀规则引擎：默认规则迁移、最严胜出、示例自校验、ask/deny 收紧集成。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.workspace_context import set_workspace_context
from permissions.bash_policy import (
	bash_readonly_allow,
	bash_rule_decision,
	clear_bash_rules_cache,
	load_bash_rules,
)
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from permissions.workspace_policy import POLICY_FILENAME, clear_policy_cache


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	clear_policy_cache()
	clear_bash_rules_cache()
	set_workspace_context(None)
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	monkeypatch.delenv("XEYO_BASH_UNSAFE_ALLOW", raising=False)
	yield
	clear_policy_cache()
	clear_bash_rules_cache()
	set_workspace_context(None)


def _write_rules(tmp_path: Path, rules: list[dict], fmt: str = "json") -> None:
	base = tmp_path / ".xeyo"
	base.mkdir(exist_ok=True)
	if fmt == "json":
		(base / "bash_rules.json").write_text(
			json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8"
		)
	else:
		lines: list[str] = []
		for r in rules:
			lines.append("[[rules]]")
			for k, v in r.items():
				if isinstance(v, list):
					lines.append(f"{k} = [{', '.join(json.dumps(x) for x in v)}]")
				else:
					lines.append(f"{k} = {json.dumps(v)}")
			lines.append("")
		(base / "bash_rules.toml").write_text("\n".join(lines), encoding="utf-8")
	clear_bash_rules_cache()


def _write_policy(tmp_path: Path, **fields: object) -> None:
	(tmp_path / POLICY_FILENAME).write_text(json.dumps(fields), encoding="utf-8")
	clear_policy_cache()


def test_default_rules_preserve_readonly_allow() -> None:
	"""内置默认规则 = 原只读白名单迁移：允许面不回归。"""
	for cmd in (
		"echo hi",
		"git status",
		"git log --oneline -5",
		"git -C sub status",
		"git -c core.quotepath=false diff",
		"npm ls",
		"pnpm list",
		"pip list",
		"python -V",
		"python3 --version",
		"node -v",
		"dir",
		"rg foo",
		"pytest -q",
	):
		assert bash_readonly_allow(cmd), cmd
	for cmd in (
		"python -c \"print(1)\"",
		"git commit -m x",
		"git push",
		"echo hi | cat",
		"echo hi > out.txt",
		"npm publish",
		"type .env",
		"unknown-tool x",
	):
		assert not bash_readonly_allow(cmd), cmd


def test_strictest_wins(tmp_path: Path) -> None:
	_write_rules(
		tmp_path,
		[
			{"name": "fetch-allow", "program": "git", "prefix": ["fetch"], "decision": "allow"},
			{"name": "fetch-ask", "program": "git", "prefix": ["fetch"], "decision": "ask"},
			{"name": "fetch-deny", "program": "git", "prefix": ["fetch"], "decision": "deny"},
		],
	)
	assert bash_rule_decision("git fetch origin", cwd=str(tmp_path)) == "deny"
	_write_rules(
		tmp_path,
		[
			{"name": "fetch-allow", "program": "git", "prefix": ["fetch"], "decision": "allow"},
			{"name": "fetch-ask", "program": "git", "prefix": ["fetch"], "decision": "ask"},
		],
	)
	assert bash_rule_decision("git fetch origin", cwd=str(tmp_path)) == "ask"
	assert bash_rule_decision("git status", cwd=str(tmp_path)) == "allow"
	assert bash_rule_decision("git push", cwd=str(tmp_path)) is None


def test_workspace_rule_extends_allow(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="default")
	_write_rules(
		tmp_path,
		[
			{
				"name": "tf-plan",
				"program": "terraform",
				"prefix": ["plan"],
				"decision": "allow",
				"match_examples": ["terraform plan -out=x.tfplan"],
				"not_match_examples": ["terraform apply"],
			}
		],
	)
	cwd = str(tmp_path)
	ok = evaluate_policy("Bash", {"command": "terraform plan"}, cwd=cwd)
	assert ok.decision == PermissionDecision.ALLOW
	assert ok.matched_rule == "bash_readonly_allow"
	ask = evaluate_policy("Bash", {"command": "terraform apply"}, cwd=cwd)
	assert ask.decision == PermissionDecision.ASK


def test_rule_ask_tightens_default_mode(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="default")
	_write_rules(
		tmp_path,
		[
			{
				"name": "status-ask",
				"program": "git",
				"prefix": ["status"],
				"decision": "ask",
			}
		],
	)
	r = evaluate_policy("Bash", {"command": "git status"}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "bash_rule_ask"


def test_rule_ask_tightens_unsafe_allow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_BASH_UNSAFE_ALLOW", "1")
	_write_policy(tmp_path, bash="allow")
	_write_rules(
		tmp_path,
		[
			{
				"name": "fetch-ask",
				"program": "git",
				"prefix": ["fetch"],
				"decision": "ask",
			}
		],
	)
	r = evaluate_policy("Bash", {"command": "git fetch"}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.ASK
	assert r.matched_rule == "bash_rule_ask"


def test_rule_deny_even_in_ask_mode(tmp_path: Path) -> None:
	"""出厂默认 bash=ask：规则 deny 仍收紧为 DENY。"""
	_write_rules(
		tmp_path,
		[
			{
				"name": "no-publish",
				"program": "npm",
				"prefix": ["publish"],
				"decision": "deny",
			}
		],
	)
	r = evaluate_policy("Bash", {"command": "npm publish --access public"}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.DENY
	assert r.matched_rule == "bash_rule_deny"


def test_worker_rule_ask_denies_and_allow_extends(tmp_path: Path) -> None:
	from permissions.write_scope import write_scope

	_write_rules(
		tmp_path,
		[
			{
				"name": "status-ask",
				"program": "git",
				"prefix": ["status"],
				"decision": "ask",
			},
			{
				"name": "tf-plan",
				"program": "terraform",
				"prefix": ["plan"],
				"decision": "allow",
			},
		],
	)
	cwd = str(tmp_path)
	with write_scope(["src"]):
		ask = evaluate_policy("Bash", {"command": "git status"}, cwd=cwd)
		ext = evaluate_policy("Bash", {"command": "terraform plan"}, cwd=cwd)
		deny = evaluate_policy("Bash", {"command": "python app.py"}, cwd=cwd)
	assert ask.decision == PermissionDecision.DENY
	assert ask.matched_rule == "worker_bash_deny"
	assert ext.decision == PermissionDecision.ALLOW
	assert ext.matched_rule == "worker_bash_readonly"
	assert deny.decision == PermissionDecision.DENY
	assert deny.matched_rule == "worker_bash_deny"


def test_contradictory_match_example_rejects_rule(tmp_path: Path) -> None:
	_write_rules(
		tmp_path,
		[
			{
				"name": "broken",
				"program": "git",
				"prefix": ["status"],
				"decision": "allow",
				"match_examples": ["git push origin"],
			},
			{"name": "ok", "program": "terraform", "prefix": ["plan"], "decision": "allow"},
		],
	)
	rs = load_bash_rules(str(tmp_path))
	assert any("broken" in e for e in rs.errors)
	assert all(r.name != "broken" for r in rs.rules)
	assert any(r.name == "ok" for r in rs.rules)
	# 矛盾规则被拒载后，git status 只由内置默认规则放行；terraform 规则不受影响
	assert bash_rule_decision("terraform plan", cwd=str(tmp_path)) == "allow"
	assert bash_rule_decision("git status", cwd=str(tmp_path)) == "allow"


def test_not_match_example_contradiction_rejects_rule(tmp_path: Path) -> None:
	_write_rules(
		tmp_path,
		[
			{
				"name": "broken",
				"program": "git",
				"prefix": ["status"],
				"decision": "allow",
				"not_match_examples": ["git status --short"],
			}
		],
	)
	rs = load_bash_rules(str(tmp_path))
	assert all(r.name != "broken" for r in rs.rules)
	assert any("not_match_example" in e for e in rs.errors)
	# 默认规则不受坏规则影响（合并而非替换）
	assert bash_readonly_allow("git status", cwd=str(tmp_path)) is True


def test_bad_rules_file_falls_back_to_builtin(tmp_path: Path) -> None:
	(tmp_path / ".xeyo").mkdir()
	(tmp_path / ".xeyo" / "bash_rules.json").write_text("{not json", encoding="utf-8")
	clear_bash_rules_cache()
	rs = load_bash_rules(str(tmp_path))
	assert any("parse error" in e for e in rs.errors)
	assert bash_readonly_allow("git status", cwd=str(tmp_path)) is True


def test_toml_rules_load(tmp_path: Path) -> None:
	_write_rules(
		tmp_path,
		[{"name": "tf", "program": "terraform", "prefix": ["plan"], "decision": "allow"}],
		fmt="toml",
	)
	assert bash_readonly_allow("terraform plan", cwd=str(tmp_path)) is True
	assert not bash_readonly_allow("terraform apply", cwd=str(tmp_path))


def test_token_alternatives(tmp_path: Path) -> None:
	_write_rules(
		tmp_path,
		[
			{
				"name": "k8s-read",
				"program": "kubectl",
				"prefix": ["get|describe"],
				"decision": "allow",
			}
		],
	)
	assert bash_readonly_allow("kubectl get pods", cwd=str(tmp_path))
	assert bash_readonly_allow("kubectl describe pod x", cwd=str(tmp_path))
	assert not bash_readonly_allow("kubectl delete pod x", cwd=str(tmp_path))


def test_absolute_path_matched_by_basename() -> None:
	assert bash_readonly_allow(r"C:\Windows\System32\where.exe python")
	assert bash_readonly_allow(r"C:\Windows\System32\git.exe status")
	assert bash_readonly_allow(r'"C:\tools\git.exe" status')
	assert not bash_readonly_allow(r"D:\tools\custom.exe run")


def test_shipping_default_readonly_autopass(tmp_path: Path) -> None:
	"""出厂缺省 bash=default：只读白名单自动放行（不再逐条确认）。"""
	r = evaluate_policy("Bash", {"command": "echo hi"}, cwd=str(tmp_path))
	assert r.decision == PermissionDecision.ALLOW
	assert r.matched_rule == "bash_readonly_allow"


def test_multiline_never_readonly_autopass() -> None:
	"""G74: 换行拼接的多行命令不得被只读白名单自动放行（首行 ls/echo 蹭 allow 跑第二行任意脚本）。"""
	assert not bash_readonly_allow("ls -la\necho hi")
	assert not bash_readonly_allow("ls -la\npython -c \"import os\"")
	assert not bash_readonly_allow("echo hello\npython -c \"import os\"")
	assert not bash_readonly_allow("ls\r\ncat /etc/passwd")
	# 单行只读仍照常自动放行
	assert bash_readonly_allow("ls -la")
	assert bash_readonly_allow("echo hi")


def test_multiline_rule_decision_takes_strictest_line(tmp_path: Path) -> None:
	"""多行命令逐行判定取最严:次行命中 deny 不会被首行 allow 盖过。"""
	_write_rules(
		tmp_path,
		[
			{
				"name": "deny-py-c",
				"program": "python",
				"prefix": ["-c"],
				"decision": "deny",
			}
		],
	)
	cwd = str(tmp_path)
	assert bash_rule_decision("ls -la", cwd=cwd) == "allow"  # 单行 allow 不受影响
	assert bash_rule_decision("ls -la\npython -c \"import os\"", cwd=cwd) == "deny"
	assert bash_readonly_allow("ls -la\npython -c \"import os\"", cwd=cwd) is False
