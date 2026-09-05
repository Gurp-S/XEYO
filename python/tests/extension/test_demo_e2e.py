"""端到端基础 demo：启用 demo 插件 → 发现 → SkillTool 可加载其 skill。

本测试仿真 conftest 的 XEYO_HOME 隔离，写入临时 workspace 的
``.xeyo/plugins/demo`` 与 ``.xeyo/settings.json``，跑通：
插件发现 → manifest 解析 → skill 三源合并 → SkillTool 加载。
"""

import asyncio
import json

from tools.skill_tool.skill_tool import SkillTool, list_skill_names, load_skill_body


def _bootstrap_workspace(ws) -> None:
	# demo 插件目录 + manifest + skill
	plug = ws / ".xeyo" / "plugins" / "demo"
	(plug / "skills" / "greeter").mkdir(parents=True)
	(plug / "skills" / "greeter" / "SKILL.md").write_text(
		"---\ndescription: 演示欢迎语\n---\n# Greeter content\n", encoding="utf-8"
	)
	(plug / "plugin.json").write_text(json.dumps({
		"name": "demo",
		"version": "0.1.0",
		"description": "demo plugin",
		"skills": ["skills/greeter"],
		"prompts": ["prompt.md"],
		"enabled": True,
	}), encoding="utf-8")
	(plug / "prompt.md").write_text("# demo prompt\n", encoding="utf-8")
	# 用户级 skill（workspace .xeyo/skills）
	(ws / ".xeyo" / "skills" / "map").mkdir(parents=True)
	(ws / ".xeyo" / "skills" / "map" / "SKILL.md").write_text(
		"# Map — 画图\n", encoding="utf-8"
	)
	# settings：开主开关 + demo 插件
	(ws / ".xeyo" / "settings.json").write_text(json.dumps({
		"enabled_extensions": True,
		"plugins": {"demo": {"enabled": True}},
	}), encoding="utf-8")


def test_demo_plugin_end_to_end(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_bootstrap_workspace(ws)
	cwd = str(ws)

	names = list_skill_names(cwd)
	assert "greeter" in names
	assert "map" in names

	body = load_skill_body(cwd, "greeter")
	assert body is not None and "Greeter content" in body

	tool = SkillTool(cwd=cwd)
	schema = tool.schema()
	desc = schema["description"]
	assert "greeter" in desc
	assert "演示欢迎语" in desc or "demo" in desc

	# 未知 skill 报错
	from engine.abort import AbortController

	result = asyncio.run(tool.execute({"name": "nope"}, AbortController()))
	assert result.is_error is True
