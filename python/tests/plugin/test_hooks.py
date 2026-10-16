"""hooks：三分结果 / abort 短路 / 上下文块注入 / 开关 fail-closed / 归类。"""

import json
import os
from pathlib import Path

from extension.hooks import _outcome_for, run_event_hooks
from extension.reconcile import consume_reconcile_blocks, reset_reconcile_state


def _setup(tmp, name="demo", *, hooks=None, master=True) -> Path:
	ws = tmp / "ws"
	ws.mkdir()
	plug = ws / ".xeyo" / "plugins" / name
	plug.mkdir(parents=True)
	manifest = {"name": name, "version": "0.1.0", "skills": ["skills/a"]}
	if hooks:
		manifest["hooks"] = hooks
	(plug / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
	(plug / "skills" / "a").mkdir(parents=True)
	(plug / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	settings = {
		"enabled_extensions": True,
		"plugins": {name: {"enabled": True}},
		"hooks": {"__master__": {"enabled": master}},
	}
	sp = ws / ".xeyo" / "settings.json"
	sp.parent.mkdir(parents=True, exist_ok=True)
	sp.write_text(json.dumps(settings), encoding="utf-8")
	return ws


def _cmds(plug: Path, body: str, name="hook.cmd") -> Path:
	p = plug / name
	if os.name == "nt":
		p.write_text(body, encoding="utf-8")
	else:
		lines = [line.strip() for line in body.splitlines()]
		message = next(line[5:] for line in lines if line.lower().startswith("echo "))
		exit_line = next(line for line in lines if line.lower().startswith("exit /b "))
		exit_code = exit_line.rsplit(" ", 1)[1]
		p.write_text(f"#!/bin/sh\necho {message}\nexit {exit_code}\n", encoding="utf-8")
		p.chmod(0o755)
	return p


def reset():
	reset_reconcile_state()


def test_hooks_disabled_skips(tmp_path):
	ws = _setup(tmp_path, master=False)
	reset()
	out = run_event_hooks("PreToolUse", str(ws), {})
	assert out.status == "skipped"
	assert consume_reconcile_blocks() == []


def test_success_hook_injects_block(tmp_path):
	ws = _setup(tmp_path, hooks=[{"event": "PreToolUse", "command": "hook.cmd"}])
	_cmds(ws / ".xeyo" / "plugins" / "demo", "@echo off\r\necho hello-from-hook\r\nexit /b 0")
	reset()
	out = run_event_hooks("PreToolUse", str(ws), {"tool_name": "Bash"})
	assert out.status == "success"
	assert any("hello-from-hook" in b for b in out.blocks)
	blocks = consume_reconcile_blocks()
	assert any("插件钩子" in b and "hello-from-hook" in b for b in blocks)


def test_abort_hook_short_circuits(tmp_path):
	ws = _setup(
		tmp_path,
		hooks=[{"event": "PreToolUse", "command": "fail.cmd", "fail_policy": "abort"}],
	)
	_cmds(ws / ".xeyo" / "plugins" / "demo", "@echo off\r\necho boom\r\nexit /b 7", "fail.cmd")
	reset()
	out = run_event_hooks("PreToolUse", str(ws), {})
	assert out.should_abort is True
	assert out.status == "abort"


def test_factor_classification():
	# Success（成功）
	assert _outcome_for({"status": "ok", "returncode": 0}, _hook(fail="continue")) == "success"
	# FailedContinue（非零 + continue）
	assert _outcome_for({"status": "ok", "returncode": 3}, _hook(fail="continue")) == "continue"
	# FailedAbort（非零 + abort）
	assert _outcome_for({"status": "ok", "returncode": 3}, _hook(fail="abort")) == "abort"
	# 超时 → fail-closed abort
	assert _outcome_for({"status": "timeout"}, _hook(fail="continue")) == "abort"



def test_permission_request_failure_ignores_continue_policy():
	from extension.hooks import PluginHook

	hook = PluginHook(
		plugin_name="p",
		event="PermissionRequest",
		command=Path("x"),
		fail_policy="continue",
	)
	assert _outcome_for({"status": "ok", "returncode": 9}, hook) == "abort"
	assert _outcome_for({"status": "error", "returncode": -1}, hook) == "abort"


def test_permission_request_hook_failure_is_monotonic(tmp_path, monkeypatch):
	from extension import hooks
	from extension.config import load_ext_config
	from extension.hooks import PluginHook

	ws = _setup(tmp_path, hooks=[{"event": "PermissionRequest", "command": "hook.cmd"}])
	cfg = load_ext_config(str(ws))
	first = PluginHook("p1", "PermissionRequest", Path("first"), fail_policy="continue")
	second = PluginHook("p2", "PermissionRequest", Path("second"), fail_policy="continue")
	calls = []
	monkeypatch.setattr(hooks, "_plugin_hooks", lambda _cfg, _cwd: [first, second])
	def run_one(hook, _context):
		calls.append(hook.plugin_name)
		if hook is first:
			return {"status": "ok", "returncode": 4, "stdout": "", "stderr": ""}
		return {"status": "ok", "returncode": 0, "stdout": "", "stderr": ""}
	monkeypatch.setattr(hooks, "_run_one_sync", run_one)
	out = run_event_hooks("PermissionRequest", str(ws), {}, config=cfg)
	assert out.status == "abort"
	assert calls == ["p1"]


def test_permission_request_hook_execution_exception_aborts(tmp_path, monkeypatch):
	from extension import hooks
	from extension.config import load_ext_config
	from extension.hooks import PluginHook

	ws = _setup(tmp_path, hooks=[{"event": "PermissionRequest", "command": "hook.cmd"}])
	cfg = load_ext_config(str(ws))
	hook = PluginHook("p", "PermissionRequest", Path("missing"), fail_policy="continue")
	monkeypatch.setattr(hooks, "_plugin_hooks", lambda _cfg, _cwd: [hook])
	def raise_error(_hook, _context):
		raise OSError("synthetic hook failure")
	monkeypatch.setattr(hooks, "_run_one_sync", raise_error)
	out = run_event_hooks("PermissionRequest", str(ws), {}, config=cfg)
	assert out.status == "abort"
	assert out.errors

def _hook(*, fail: str, event="PreToolUse"):
	from extension.hooks import PluginHook

	return PluginHook(plugin_name="p", event=event, command=Path("x"), fail_policy=fail)


def test_missing_permission_request_hook_aborts(tmp_path):
	ws = _setup(
		tmp_path,
		hooks=[{"event": "PermissionRequest", "command": "missing.cmd", "fail_policy": "continue"}],
	)
	out = run_event_hooks("PermissionRequest", str(ws), {})
	assert out.status == "abort"
