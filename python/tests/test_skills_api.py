"""``GET /v1/skills`` — 结构化技能清单端点的契约与门禁测试。

覆盖：
- loopback 放行 / LAN 拒绝（T33 同源门禁）。
- 扩展层关闭 → ``enabled_extensions:false`` + 空列表。
- 扩展层开启 → 合并 workspace / plugin 技能并返回描述与 source。

与 ``tests/extension/test_demo_e2e.py`` 共用 workspace 引导方式（临时 .xeyo 目录）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app

_LAN = ("203.0.113.7", 55555)


def _bootstrap_workspace(ws: Path) -> None:
	plug = ws / ".xeyo" / "plugins" / "demo"
	(plug / "skills" / "greeter").mkdir(parents=True)
	(plug / "skills" / "greeter" / "SKILL.md").write_text(
		"---\ndescription: 演示欢迎语\n---\n# Greeter content\n", encoding="utf-8"
	)
	(plug / "plugin.json").write_text(
		json.dumps({
			"name": "demo",
			"version": "0.1.0",
			"description": "demo plugin",
			"skills": ["skills/greeter"],
			"prompts": ["prompt.md"],
			"enabled": True,
		}),
		encoding="utf-8",
	)
	(plug / "prompt.md").write_text("# demo prompt\n", encoding="utf-8")
	(ws / ".xeyo" / "skills" / "map").mkdir(parents=True)
	(ws / ".xeyo" / "skills" / "map" / "SKILL.md").write_text(
		"---\ndescription: 画图技能\n---\n# Map — 画图\n", encoding="utf-8"
	)
	(ws / ".xeyo" / "settings.json").write_text(
		json.dumps({
			"enabled_extensions": True,
			"plugins": {"demo": {"enabled": True}},
		}),
		encoding="utf-8",
	)


def _get(client: TestClient, workspace: str) -> dict:
	r = client.get(f"/v1/skills?workspace={workspace}")
	assert r.status_code == 200, r.text
	return r.json()


def test_skills_rejected_from_lan() -> None:
	with TestClient(app, client=_LAN) as c:
		assert c.get("/v1/skills").status_code == 403


def test_skills_disabled_by_default(tmp_path: Path) -> None:
	# 无 settings.json → 扩展层默认关闭，返回空列表而非报错。
	body = _get(TestClient(app), str(tmp_path))
	assert body.get("ok") is True
	assert body.get("enabled_extensions") is False
	assert body.get("skills") == []


def test_skills_merges_workspace_and_plugin(tmp_path: Path) -> None:
	_bootstrap_workspace(tmp_path)
	with TestClient(app) as c:
		body = _get(c, str(tmp_path))
	assert body.get("ok") is True
	assert body.get("enabled_extensions") is True
	names = {s["name"] for s in body["skills"]}
	assert "map" in names
	assert "greeter" in names
	by_name = {s["name"]: s for s in body["skills"]}
	assert by_name["map"]["source"] == "workspace"
	assert by_name["map"]["description"] == "画图技能"
	assert by_name["greeter"]["source"] == "plugin"
	assert by_name["greeter"]["description"] == "演示欢迎语"


def test_skills_menu_filters_user_invocable_false(tmp_path: Path) -> None:
	# F4（§2 决策 3）：user_invocable:false → /v1/skills 不展示；
	# model_invocable:false 只挡模型侧，仍对用户菜单可见。
	_bootstrap_workspace(tmp_path)
	hidden = tmp_path / ".xeyo" / "skills" / "internal-only"
	hidden.mkdir(parents=True)
	(hidden / "SKILL.md").write_text(
		"---\ndescription: 内部流程\nuser_invocable: false\n---\n# internal\n",
		encoding="utf-8",
	)
	model_only = tmp_path / ".xeyo" / "skills" / "auto-flow"
	model_only.mkdir(parents=True)
	(model_only / "SKILL.md").write_text(
		"---\ndescription: 仅模型流程\nmodel_invocable: false\n---\n# auto\n",
		encoding="utf-8",
	)
	with TestClient(app) as c:
		body = _get(c, str(tmp_path))
	names = {s["name"] for s in body["skills"]}
	assert "map" in names
	assert "internal-only" not in names
	assert "auto-flow" in names
