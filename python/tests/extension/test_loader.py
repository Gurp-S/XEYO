"""插件发现 / 合并 / 去重 / 坏清单跳过。"""

from pathlib import Path

from extension.config import load_ext_config
from extension.loader import discover_plugins, loaded_plugins_with_errors


def _mk_plugin(root: Path, name: str, *, body: dict | None = None, enabled: bool = True) -> Path:
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "plugin.json").write_text(
		__import__("json").dumps({
			"name": name,
			"version": "0.1.0",
			"description": f"{name} desc",
			"skills": ["skills/a"],
			"enabled": enabled,
		}),
		encoding="utf-8",
	)
	(d / "skills" / "a").mkdir(parents=True)
	(d / "skills" / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
	return d


def _enable(ws: Path, name: str, enabled: bool = True) -> None:
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	import json

	data = json.loads(p.read_text()) if p.exists() else {}
	data["enabled_extensions"] = True
	data.setdefault("plugins", {})[name] = {"enabled": enabled}
	p.write_text(json.dumps(data), encoding="utf-8")


def test_discover_workspace_plugin(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(ws / ".xeyo" / "plugins", "demo")
	_enable(ws, "demo")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	names = [(p.name, p.enabled, p.source_scope) for p in plugs]
	assert ("demo", True, "workspace") in names


def test_disabled_plugin_not_enabled(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(ws / ".xeyo" / "plugins", "off")
	_enable(ws, "off", enabled=False)
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	got = {p.name: p.enabled for p in plugs}
	assert got.get("off") is False


def test_workspace_overrides_home_same_name(monkeypatch, tmp_path):
	home = tmp_path / "home"
	_mk_plugin(home / ".xeyo" / "plugins", "dup", body={"name": "dup"})
	monkeypatch.setenv("XEYO_HOME", str(home))
	ws = tmp_path / "ws"
	ws.mkdir()
	_mk_plugin(ws / ".xeyo" / "plugins", "dup")
	_enable(ws, "dup")
	cfg = load_ext_config(str(ws))
	plugs = discover_plugins(str(ws), config=cfg)
	dup = [p for p in plugs if p.name == "dup"][0]
	assert dup.source_scope == "workspace"  # 同名以 workspace 为准


def test_bad_manifest_skipped(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	bad = ws / ".xeyo" / "plugins" / "bad"
	bad.mkdir(parents=True)
	(bad / "plugin.json").write_text("{bad", encoding="utf-8")
	plugs, errs = loaded_plugins_with_errors(str(ws))
	assert plugs == []
	assert any("bad" in e for e in errs)
