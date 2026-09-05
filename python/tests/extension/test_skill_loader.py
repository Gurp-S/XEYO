"""skill 发现：三源合并、frontmatter、冲突、插件承载。"""

import json
from pathlib import Path

from extension.config import load_ext_config
from extension.skill_loader import discover_skills


def _write_skill(d: Path, name: str, body: str) -> None:
	(d / name).mkdir(parents=True, exist_ok=True)
	(d / name / "SKILL.md").write_text(body, encoding="utf-8")


def _enable(ws: Path, *, plugin: dict | None = None) -> None:
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	data = {"enabled_extensions": True, "plugins": plugin or {}, "skills": {}}
	p.write_text(json.dumps(data), encoding="utf-8")


def test_frontmatter_description(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_skill(
		ws / ".xeyo" / "skills",
		"alpha",
		"---\ndescription: 这是我的 skill\n---\n# Alpha\nbody here",
	)
	_enable(ws)
	cfg = load_ext_config(str(ws))
	skills = discover_skills(str(ws), config=cfg)
	alpha = [s for s in skills if s.name == "alpha"][0]
	assert alpha.description == "这是我的 skill"
	assert alpha.source == "workspace"


def test_fallback_to_heading(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_skill(ws / ".xeyo" / "skills", "beta", "# Beta Heading\n\nbody")
	_enable(ws)
	cfg = load_ext_config(str(ws))
	skills = discover_skills(str(ws), config=cfg)
	beta = [s for s in skills if s.name == "beta"][0]
	assert beta.description == "Beta Heading"


def test_plugin_skill_merged(monkeypatch, tmp_path):
	home = tmp_path / "home"
	# 插件 skill 独立于 XEYO_HOME 存放，直接模拟 workspace 插件。
	ws = tmp_path / "ws"
	ws.mkdir()
	plug = ws / ".xeyo" / "plugins" / "demo"
	(plug / "skills" / "greeter").mkdir(parents=True)
	(plug / "skills" / "greeter" / "SKILL.md").write_text(
		"---\ndescription: 欢迎语\n---\n# Greeter\n", encoding="utf-8"
	)
	(plug / "plugin.json").write_text(json.dumps({
		"name": "demo",
		"skills": ["skills/greeter"],
		"enabled": True,
	}), encoding="utf-8")
	_enable(ws, plugin={"demo": {"enabled": True}})
	cfg = load_ext_config(str(ws))
	skills = discover_skills(str(ws), config=cfg)
	greeter = [s for s in skills if s.name == "greeter"]
	assert greeter and greeter[0].plugin == "demo"
	assert greeter[0].description == "欢迎语"


def test_same_name_not_overridden_default(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	# workspace 同名 skill 先出现；plugin 同名不覆盖（默认禁止覆盖）。
	_write_skill(ws / ".xeyo" / "skills", "dup", "# Duplicat workspace")
	plug = ws / ".xeyo" / "plugins" / "p"
	(plug / "skills" / "dup").mkdir(parents=True)
	(plug / "skills" / "dup" / "SKILL.md").write_text(
		"# Duplicat plugin (should NOT override)", encoding="utf-8"
	)
	(plug / "plugin.json").write_text(json.dumps({
		"name": "p",
		"skills": ["skills/dup"],
		"enabled": True,
	}), encoding="utf-8")
	_enable(ws, plugin={"p": {"enabled": True}})
	cfg = load_ext_config(str(ws))
	skills = discover_skills(str(ws), config=cfg)
	dup = [s for s in skills if s.name == "dup"]
	assert len(dup) == 1
	assert dup[0].source == "workspace"
