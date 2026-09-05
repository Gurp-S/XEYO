"""工具门禁钩子接线：PreToolUse abort → 短路工具（返回阻断结果）。"""

import asyncio
import json
from pathlib import Path

from tools.tool_registry import ToolRegistry


def _setup(tmp_path, *, fail_policy="abort", master=True) -> Path:
	ws = tmp_path / "ws"
	ws.mkdir()
	plug = ws / ".xeyo" / "plugins" / "demo"
	plug.mkdir(parents=True)
	manifest = {
		"name": "demo",
		"version": "0.1.0",
		"skills": ["skills/a"],
		"hooks": [
			{"event": "PreToolUse", "command": "fail.cmd", "fail_policy": fail_policy}
		],
	}
	(plug / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
	(plug / "skills" / "a").mkdir(parents=True)
	(plug / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	(plug / "fail.cmd").write_text("@echo off\r\necho boom\r\nexit /b 7", encoding="utf-8")
	sp = ws / ".xeyo" / "settings.json"
	sp.parent.mkdir(parents=True, exist_ok=True)
	sp.write_text(
		json.dumps(
			{
				"enabled_extensions": True,
				"plugins": {"demo": {"enabled": True}},
				"hooks": {"__master__": {"enabled": master}},
			}
		),
		encoding="utf-8",
	)
	return ws


def test_pre_tool_abort_short_circuits(tmp_path):
	ws = _setup(tmp_path)
	reg = ToolRegistry(cwd=str(ws))
	res = asyncio.run(reg._hook_blocker("PreToolUse", str(ws), "Bash", {"command": "ls"}, abort_label="Bash"))
	assert res is not None
	assert res.is_error
	assert "aborted by plugin hook" in res.content


def test_pre_tool_skips_when_hooks_off(tmp_path):
	ws = _setup(tmp_path, master=False)
	reg = ToolRegistry(cwd=str(ws))
	res = asyncio.run(reg._hook_blocker("PreToolUse", str(ws), "Bash", {"command": "ls"}, abort_label="Bash"))
	assert res is None
