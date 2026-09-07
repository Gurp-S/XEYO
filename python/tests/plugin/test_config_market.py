"""配置扩展：plugin_market / hooks 开关 + 企业策略 plugin_deny / market 白名单。"""

from pathlib import Path


from extension.config import (
	load_ext_config,
	set_hooks_enabled,
	set_plugin_market_enabled,
)
from extension.mcp_scopes import (
	plugin_denied,
	plugin_market_allowed,
)


def _write(ws: Path, data: dict) -> None:
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	import json

	p.write_text(json.dumps(data), encoding="utf-8")


def test_defaults_off(tmp_path):
	cfg = load_ext_config(str(tmp_path))
	assert cfg.plugin_market_enabled() is False
	assert cfg.hooks_enabled() is False


def test_market_requires_master(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write(ws, {"plugin_market": True})
	cfg = load_ext_config(str(ws))
	assert cfg.plugin_market_enabled() is False  # 主开关仍关
	_write(ws, {"enabled_extensions": True, "plugin_market": True})
	assert load_ext_config(str(ws)).plugin_market_enabled() is True


def test_hooks_master_and_single(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write(
		ws,
		{
			"enabled_extensions": True,
			"hooks": {
				"__master__": {"enabled": True},
				"pre_tool_use_demo": {"enabled": True},
			},
		},
	)
	cfg = load_ext_config(str(ws))
	assert cfg.hooks_enabled() is True
	assert cfg.hook_enabled("pre_tool_use_demo") is True
	# 未显式 off 的钩子：主开关开 + 插件未禁用 → 默认启用（skill 同款语义）。
	assert cfg.hook_enabled("other") is True
	assert cfg.hook_enabled("other", parent_plugin_enabled=False) is False

	# hooks 总开关关 → 全关
	_write(ws, {"enabled_extensions": True, "hooks": {"__master__": {"enabled": False}}})
	assert load_ext_config(str(ws)).hooks_enabled() is False


def test_set_plugin_market_enabled(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	set_plugin_market_enabled(str(ws), True)
	assert load_ext_config(str(ws)).plugin_market is True


def test_set_hooks_enabled(tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	set_hooks_enabled(str(ws), True)
	cfg = load_ext_config(str(ws))
	# hooks 主开关已落盘；hooks_enabled() 仍依赖扩展层主开关 → 需主开关开。
	assert cfg.hooks.get("__master__") == {"enabled": True}
	_write(ws, {"enabled_extensions": True, "hooks": {"__master__": {"enabled": True}}})
	assert load_ext_config(str(ws)).hooks_enabled() is True


def test_enterprise_plugin_deny():
	assert plugin_denied("evil", policy={"plugin_deny": ["evil"], "plugin_market_allow": []}) is True
	assert plugin_denied("ok", policy={"plugin_deny": ["evil"], "plugin_market_allow": []}) is False


def test_market_whitelist():
	# 空白名单 → 全放行（默认）
	assert plugin_market_allowed("github:a/b", policy={"plugin_market_allow": [], "plugin_deny": []})
	# 非空白名单 → 仅列出的放行
	pol = {"plugin_market_allow": ["github:a/b"], "plugin_deny": []}
	assert plugin_market_allowed("github:a/b", policy=pol)
	assert plugin_market_allowed("github:other/x", policy=pol) is False
