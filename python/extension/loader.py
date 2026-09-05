"""插件全局发现与合并。

发现源（优先级 workspace > home）：
1. ``<workspace root>/.xeyo/plugins/*``
2. ``~/.xeyo/plugins/*``（``XEYO_HOME`` 可覆盖）

命名冲突：同名（casefold）以 workspace 为准，同名家目录条目丢弃。
坏 manifest：捕获 :class:`ManifestError`，跳过并记录，不让单个坏插件搞挂启动。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from extension.config import ExtensionConfig, load_ext_config
from extension.errors import ManifestError
from extension.manifest import Plugin, load_manifest

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedPlugin:
	"""发现到的插件（已解析 manifest + 启用态）。"""

	plugin: Plugin
	enabled: bool
	source_scope: str  # "workspace" | "home"

	@property
	def name(self) -> str:
		return self.plugin.name


def _scan_root(root: Path) -> list[Plugin]:
	if not root.is_dir():
		return []
	out: list[Plugin] = []
	try:
		for child in sorted(root.iterdir()):
			if not child.is_dir():
				continue
			try:
				out.append(load_manifest(child))
			except ManifestError as e:
				_log.warning("skip bad plugin: %s", e)
				continue
	except OSError as e:
		_log.warning("cannot scan plugin root %s: %s", root, e)
	return out


def discover_plugins(
	cwd: str | None = None,
	*,
	config: ExtensionConfig | None = None,
) -> list[LoadedPlugin]:
	"""发现全部插件，返回带启用态的列表；按 workspace > home 去重（同名覆盖）。"""
	cfg = config if config is not None else load_ext_config(cwd)
	home_plugins = _scan_root((Path("~/.xeyo").expanduser() / "plugins"))
	ws_plugins: list[Plugin] = []
	if cwd:
		ws_plugins = _scan_root((Path(cwd).expanduser().resolve() / ".xeyo" / "plugins"))

	by_name: dict[str, LoadedPlugin] = {}
	# home 先入（低优先级），workspace 后入覆盖同名。
	for p in home_plugins:
		by_name[p.name.casefold()] = LoadedPlugin(
			plugin=p,
			enabled=_plugin_active(cfg, cwd, p),
			source_scope="home",
		)
	for p in ws_plugins:
		by_name[p.name.casefold()] = LoadedPlugin(
			plugin=p,
			enabled=_plugin_active(cfg, cwd, p),
			source_scope="workspace",
		)
	return [by_name[k] for k in sorted(by_name)]


def _plugin_active(cfg: ExtensionConfig, cwd: str | None, p: Plugin) -> bool:
	"""插件是否激活：配置文件启用 && (本地源免批 || 远程源已受信)。

	fail-closed：远程源（github/npm）未在插件信任文件批准 → 视为禁用
	（不进入 MCP scope / skills / hooks），需显式 ``approve`` 才激活。
	"""
	if not cfg.plugin_enabled(p.name):
		return False
	if p.manifest.source_type == "local":
		return True
	try:
		from extension.plugin_fetcher import is_plugin_trusted

		return is_plugin_trusted(cwd, p.name, source_type=p.manifest.source_type)
	except Exception:  # noqa: BLE001 — 信任读取失败按 fail-closed 处理
		return False


def loaded_plugins_with_errors(
	cwd: str | None = None,
	*,
	config: ExtensionConfig | None = None,
) -> tuple[list[LoadedPlugin], list[str]]:
	"""集成校验用：返回 (成功插件, 错误消息列表)。"""
	cfg = config if config is not None else load_ext_config(cwd)
	errors: list[str] = []
	home_plugins: list[Plugin] = []
	ws_plugins: list[Plugin] = []
	for root_ctx, bucket in (
		(Path("~/.xeyo").expanduser() / "plugins", home_plugins),
		((Path(cwd).expanduser().resolve() / ".xeyo" / "plugins") if cwd else None, ws_plugins),
	):
		if root_ctx is None:
			continue
		if not root_ctx.is_dir():
			continue
		try:
			for child in sorted(root_ctx.iterdir()):
				if not child.is_dir():
					continue
				try:
					bucket.append(load_manifest(child))
				except ManifestError as e:
					errors.append(str(e))
		except OSError as e:
			errors.append(f"cannot scan {root_ctx}: {e}")
	by_name: dict[str, LoadedPlugin] = {}
	for p in home_plugins:
		by_name[p.name.casefold()] = LoadedPlugin(p, cfg.plugin_enabled(p.name), "home")
	for p in ws_plugins:
		by_name[p.name.casefold()] = LoadedPlugin(p, cfg.plugin_enabled(p.name), "workspace")
	return [by_name[k] for k in sorted(by_name)], errors
