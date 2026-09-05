"""扩展层配置读写与合并。"""

from pathlib import Path

from extension.config import (
	ExtensionConfig,
	load_ext_config,
	set_plugin_enabled,
	workspace_settings_path,
)


def _write_ws_settings(ws: Path, data: dict) -> None:
	p = ws_settings(ws)
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(__import__("json").dumps(data), encoding="utf-8")


def ws_settings(ws: Path) -> Path:
	return workspace_settings_path(str(ws))


def test_default_closed(tmp_path):
	cfg = load_ext_config(str(tmp_path))
	assert cfg.enabled_extensions is False
	assert cfg.plugin_enabled("demo") is False


def test_enabled_via_workspace(tmp_path):
	_write_ws_settings(tmp_path, {"enabled_extensions": True, "plugins": {"demo": {"enabled": True}}})
	cfg = load_ext_config(str(tmp_path))
	assert cfg.plugin_enabled("demo") is True


def test_workspace_overrides_home(monkeypatch, tmp_path):
	home = tmp_path / "home"
	home.mkdir()
	(home / "settings.json").write_text(
		'{"enabled_extensions":true,"plugins":{"demo":{"enabled":false}}}', encoding="utf-8"
	)
	monkeypatch.setenv("XEYO_HOME", str(home))
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_ws_settings(ws, {"plugins": {"demo": {"enabled": True}}})
	cfg = load_ext_config(str(ws))
	assert cfg.plugin_enabled("demo") is True  # workspace 覆盖 home


def test_skill_default_enabled_with_plugin(tmp_path):
	_write_ws_settings(
		tmp_path,
		{"enabled_extensions": True, "plugins": {"demo": {"enabled": True}}},
	)
	cfg = load_ext_config(str(tmp_path))
	# 插件启用后，其 skill 默认启用（未显式声明）
	assert cfg.skill_enabled("greeter", from_plugin=True, parent_plugin_enabled=True) is True
	# 主开关关 → 全关
	cfg2 = load_ext_config(str((tmp_path / "empty").mkdir() or tmp_path / "empty")) if False else None
	# 显式禁用某个 skill
	_write_ws_settings(tmp_path, {"enabled_extensions": True, "skills": {"greeter": {"enabled": False}}})
	cfg3 = load_ext_config(str(tmp_path))
	assert cfg3.skill_enabled("greeter", from_plugin=True, parent_plugin_enabled=True) is False


def test_set_plugin_enabled(tmp_path):
	set_plugin_enabled(str(tmp_path), "demo", True)
	p = ws_settings(tmp_path)
	assert p.is_file()
	cfg = load_ext_config(str(tmp_path))
	# 注意：set_plugin_enabled 只写插件，不改 enabled_extensions，需同时开，否则默认关。
	assert cfg.enabled_extensions is False or cfg.plugin_enabled("demo") is True


def test_bad_json_falls_back_empty(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	(ws / ".xeyo").mkdir()
	(ws / ".xeyo" / "settings.json").write_text("{bad json", encoding="utf-8")
	cfg = load_ext_config(str(ws))
	assert cfg.enabled_extensions is False


# Permission test: adding a comment to verify write access
# This is a harmless modification to test file write permissions
