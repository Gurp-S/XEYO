"""扩展层配置持久化：``<root>/.xeyo/settings.json``（无 GUI，纯后端）。

存储按范围合并：
- 用户/home 级：``~/.xeyo/settings.json``（``XEYO_HOME`` 可覆盖）
- 工作区级：``<workspace root>/.xeyo/settings.json``（更具体者优先）

结构：
.. code-block:: jsonc

	{
	  "enabled_extensions": true,           // 总开关（默认关）
	  "plugins": {"<name>": {"enabled": true}},
	  "skills":  {"<name>": {"enabled": true}},
	  "mcp_servers": {"<id>": {"enabled": true, "auto_start": true}}
	}

读侧经 contextvar 快照注入（照抄 set_searxng_url 范式）：请求入口 set、finally 复位。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extension.errors import ConfigError

_DEFAULT: dict[str, Any] = {
	"enabled_extensions": False,
	"plugin_market": False,
	"plugins": {},
	"skills": {},
	"mcp_servers": {},
	"hooks": {},
}


def _home_root() -> Path:
	from memory.instruction import xeyo_home

	return xeyo_home()


def workspace_settings_path(cwd: str) -> Path:
	return (Path(cwd).expanduser().resolve() / ".xeyo" / "settings.json")


def home_settings_path() -> Path:
	return _home_root() / "settings.json"


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
	"""两层浅合并：插件/技能/MCP 的 enabled 用 extra（workspace）覆盖 base（home）。"""
	out = dict(base)
	for key in ("plugins", "skills", "mcp_servers", "hooks"):
		b = dict(base.get(key) or {})
		e = dict(extra.get(key) or {})
		merged = dict(b)
		for k, v in e.items():
			if isinstance(v, dict) and isinstance(merged.get(k), dict):
				merged[k] = {**merged[k], **v}
			else:
				merged[k] = v
		out[key] = merged
	for key in ("enabled_extensions", "plugin_market"):
		if key in extra:
			out[key] = extra[key]
	return out


_LAST_GOOD: dict[str, dict[str, Any]] = {}


def _read_json(path: Path) -> dict[str, Any]:
	"""读取一个 settings 文件（T25 fail-closed 语义）。

	- 缺文件 → 空 dict（该层回退默认，主开关关——方向安全）。
	- 坏 JSON / 非对象 → **keep-last-good**：返回该路径最近一次成功解析的内容
	  （编辑器原子写间隙、意外截断不应把已启用配置静默打回默认）；无 last-good
	  则回退空 dict。两种情况都记 warning + 审计事件（config.invalid）。
	"""
	import logging

	_log = logging.getLogger(__name__)
	key = str(path)
	if not path.is_file():
		_LAST_GOOD.pop(key, None)
		return {}
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
		if isinstance(raw, dict):
			_LAST_GOOD[key] = raw
			return raw
		kept = _LAST_GOOD.get(key)
		_log.warning(
			"settings.json at %s is not an object; %s",
			path,
			"keeping last good" if kept is not None else "no last good, using defaults",
		)
		_record_invalid(key, "not a JSON object", kept is not None)
		return dict(kept) if kept is not None else {}
	except (OSError, json.JSONDecodeError) as e:
		kept = _LAST_GOOD.get(key)
		_log.warning(
			"bad settings.json at %s: %s (%s)",
			path,
			e,
			"kept last good" if kept is not None else "no last good, using defaults",
		)
		_record_invalid(key, str(e), kept is not None)
		return dict(kept) if kept is not None else {}


def _record_invalid(path_key: str, error: str, kept_good: bool) -> None:
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"config.invalid",
			path=path_key,
			error=error,
			action="keep_last_good" if kept_good else "defaults_applied",
		)
	except Exception:  # 审计故障不影响配置回退
		pass


@dataclass
class ExtensionConfig:
	"""合并后的扩展配置视图。"""

	enabled_extensions: bool = _DEFAULT["enabled_extensions"]
	plugin_market: bool = _DEFAULT["plugin_market"]
	plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
	skills: dict[str, dict[str, Any]] = field(default_factory=dict)
	mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
	hooks: dict[str, dict[str, Any]] = field(default_factory=dict)

	def plugin_enabled(self, name: str) -> bool:
		"""插件启用：总开关 + 自身开关；缺省视为关（企业级默认关闭）。"""
		if not self.enabled_extensions:
			return False
		entry = self.plugins.get(name) or {}
		return bool(entry.get("enabled", False))

	def skill_enabled(
		self,
		name: str,
		*,
		from_plugin: bool = False,
		parent_plugin_enabled: bool = True,
	) -> bool:
		"""skill 启用。

		- 主开关 ``enabled_extensions`` 关 → 全关（企业级默认关闭）。
		- 来自插件（``from_plugin``）且插件被禁用 → 关。
		- 未在 ``skills`` 显式声明 → 默认启用（插件的自带 skill 随插件启用）；
		  显式 ``enabled: false`` 可单独禁用某个 skill。
		"""
		if not self.enabled_extensions:
			return False
		if from_plugin and not parent_plugin_enabled:
			return False
		entry = self.skills.get(name) or {}
		return bool(entry.get("enabled", True))

	def mcp_enabled(self, mcp_id: str) -> bool:
		if not self.enabled_extensions:
			return False
		entry = self.mcp_servers.get(mcp_id) or {}
		return bool(entry.get("enabled", False))

	def mcp_auto_start(self, mcp_id: str) -> bool:
		entry = self.mcp_servers.get(mcp_id) or {}
		return bool(entry.get("auto_start", True))

	def plugin_market_enabled(self) -> bool:
		"""插件市场：需扩展层主开关开 + 市场开关开（默认关）。"""
		return bool(self.enabled_extensions and self.plugin_market)

	def hooks_enabled(self) -> bool:
		"""生命周期钩子开关：需扩展层主开关开 + hooks 总开关开（默认关）。"""
		return bool(self.enabled_extensions and self._hooks_master())

	def hook_enabled(self, name: str, *, parent_plugin_enabled: bool = True) -> bool:
		"""单个 hook 启用：主开关 + hooks 总开关 + 插件未禁用 + 未显式 off。"""
		if not self.hooks_enabled():
			return False
		if not parent_plugin_enabled:
			return False
		entry = self.hooks.get(name) or {}
		return bool(entry.get("enabled", True))

	def _hooks_master(self) -> bool:
		entry = self.hooks.get("__master__") or {}
		return bool(entry.get("enabled", False))


def load_ext_config(cwd: str | None = None) -> ExtensionConfig:
	"""合并 home + workspace 两处配置；任何一处坏读都回退该处为空。"""
	home = _read_json(home_settings_path())
	ws = _read_json(workspace_settings_path(cwd)) if cwd else {}
	merged = _merge(home, ws)
	# 保证所有预期键存在（即便 home/ws 为空文件）。
	merged = _merge(_DEFAULT, merged)
	return ExtensionConfig(
		enabled_extensions=bool(merged.get("enabled_extensions", False)),
		plugin_market=bool(merged.get("plugin_market", False)),
		plugins=dict(merged.get("plugins") or {}),
		skills=dict(merged.get("skills") or {}),
		mcp_servers=dict(merged.get("mcp_servers") or {}),
		hooks=dict(merged.get("hooks") or {}),
	)


def write_settings(path: Path, data: dict[str, Any]) -> None:
	"""写一份设置（全量覆盖单文件；temp+``os.replace`` 原子落盘）。

	原子性（P0b F2.5）：push reconcile 写入后立即 apply，读侧（mtime 缓存/
	其他进程）不应看到半截 JSON；keep-last-good 是最后防线，不是常规路径。
	"""
	tmp: Path | None = None
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
		tmp.write_text(
			json.dumps(data, ensure_ascii=False, indent=2) + "\n",
			encoding="utf-8",
		)
		os.replace(tmp, path)
	except OSError as e:
		if tmp is not None:
			try:
				tmp.unlink(missing_ok=True)
			except OSError:
				pass
		raise ConfigError(f"cannot write settings {path}: {e}") from e


def set_plugin_enabled(cwd: str | None, name: str, enabled: bool) -> None:
	"""写工作区级 settings.json 的 plugin 开关（demo 用；后续 GUI 接管）。"""
	target = workspace_settings_path(cwd) if cwd else home_settings_path()
	data = _read_json(target)
	plugins = dict(data.get("plugins") or {})
	plugins[name] = {"enabled": bool(enabled)}
	data["plugins"] = plugins
	write_settings(target, data)


def set_mcp_enabled(cwd: str | None, mcp_id: str, enabled: bool) -> None:
	"""写工作区级 settings.json 的 MCP server 开关（P0b F2.5 push reconcile）。

	原子写 + 变化才发布 T_now 活页块（``# 工具面变更``，digest 幂等）。
	"""
	target = workspace_settings_path(cwd) if cwd else home_settings_path()
	data = _read_json(target)
	servers = dict(data.get("mcp_servers") or {})
	entry = dict(servers.get(mcp_id) or {})
	changed = bool(entry.get("enabled", False)) != bool(enabled)
	entry["enabled"] = bool(enabled)
	servers[mcp_id] = entry
	data["mcp_servers"] = servers
	write_settings(target, data)
	if changed:
		from extension.reconcile import build_mcp_block, publish_if_changed

		publish_if_changed(
			f"mcp:{mcp_id}",
			{"id": mcp_id, "enabled": bool(enabled)},
			lambda: build_mcp_block(bool(enabled), f"MCP 服务 `{mcp_id}`"),
		)


def set_skill_enabled(cwd: str | None, name: str, enabled: bool) -> None:
	"""写工作区级 settings.json 的 skill 开关（P0b F2.5 push reconcile）。

	原子写 + 变化才发布 T_now 活页块（``# 技能目录变更``，digest 幂等）。
	"""
	target = workspace_settings_path(cwd) if cwd else home_settings_path()
	data = _read_json(target)
	skills = dict(data.get("skills") or {})
	entry = dict(skills.get(name) or {})
	changed = bool(entry.get("enabled", True)) != bool(enabled)
	entry["enabled"] = bool(enabled)
	skills[name] = entry
	data["skills"] = skills
	write_settings(target, data)
	if changed:
		from extension.reconcile import build_skill_block, publish_if_changed

		publish_if_changed(
			f"skill:{name}",
			{"name": name, "enabled": bool(enabled)},
			lambda: build_skill_block(bool(enabled), name),
		)


def set_extensions_enabled(cwd: str | None, enabled: bool) -> None:
	"""写扩展层主开关（P0b 控制路径；变化才发布工具面活页块）。"""
	target = workspace_settings_path(cwd) if cwd else home_settings_path()
	data = _read_json(target)
	changed = bool(data.get("enabled_extensions", False)) != bool(enabled)
	data["enabled_extensions"] = bool(enabled)
	write_settings(target, data)
	if changed:
		from extension.reconcile import publish_if_changed

		kind = "启用" if enabled else "停用"

		def _build() -> str:
			return (
				"# 工具面变更（background only — 非用户新提问）\n"
				f"- 用户{kind}了扩展层主开关：全部 MCP 工具/技能调用侧即时"
				+ ("生效。" if enabled else "失效（调用被拒绝）；下个会话重塑目录。")
			)

		publish_if_changed("extensions_master", {"enabled": bool(enabled)}, _build)


def set_plugin_market_enabled(cwd: str | None, enabled: bool) -> None:
	"""写插件市场开关（默认关）。"""
	target = workspace_settings_path(cwd) if cwd else home_settings_path()
	data = _read_json(target)
	data["plugin_market"] = bool(enabled)
	write_settings(target, data)


def set_hooks_enabled(cwd: str | None, enabled: bool) -> None:
	"""写生命周期钩子总开关（默认关）。"""
	target = workspace_settings_path(cwd) if cwd else home_settings_path()
	data = _read_json(target)
	hooks = dict(data.get("hooks") or {})
	master = dict(hooks.get("__master__") or {})
	master["enabled"] = bool(enabled)
	hooks["__master__"] = master
	data["hooks"] = hooks
	write_settings(target, data)
