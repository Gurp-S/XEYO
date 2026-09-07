"""插件全局发现与合并。

发现源（优先级 workspace > home）：
1. ``<workspace root>/.xeyo/plugins/*``
2. ``~/.xeyo/plugins/*``（``XEYO_HOME`` 可覆盖）

命名冲突：同名（casefold）以 workspace 为准，同名家目录条目丢弃。
坏 manifest：捕获 :class:`ManifestError`，跳过并记录，不让单个坏插件搞挂启动。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
			enabled=_plugin_active(cfg, cwd, p, scope="home"),
			source_scope="home",
		)
	for p in ws_plugins:
		by_name[p.name.casefold()] = LoadedPlugin(
			plugin=p,
			enabled=_plugin_active(cfg, cwd, p, scope="workspace"),
			source_scope="workspace",
		)
	return [by_name[k] for k in sorted(by_name)]


def _lockfile_source_type(cwd: str | None, name: str, *, scope: str) -> str | None:
	"""安装期真实来源：读 ``plugins-lock.json`` 登记条目的 ``sourceType``。

	lockfile 由安装流程写入（install_from_path/github 各带真实 source_type），
	不受插件自带 ``plugin.json``（manifest）里可被攻击者声明的字段影响。
	返回 None = 该插件未登记（手工拷贝/未受管）。
	"""
	try:
		from extension.plugin_store import default_lock_path, load_plugins

		lock_path = default_lock_path(cwd if scope == "workspace" else None)
		entry = (load_plugins(lock_path) or {}).get(name)
		st = str((entry or {}).get("sourceType") or "") if isinstance(entry, dict) else ""
		return st if st in ("local", "github", "npm") else None
	except Exception:  # noqa: BLE001 — lockfile 读失败按未登记处理(fail-closed)
		return None


def _plugin_active(cfg: ExtensionConfig, cwd: str | None, p: Plugin, *, scope: str = "workspace") -> bool:
	"""插件是否激活：配置文件启用 && (本地源免批 || 远程源已受信)。

	fail-closed：远程源（github/npm）未在插件信任文件批准 → 视为禁用
	（不进入 MCP scope / skills / hooks），需显式 ``approve`` 才激活。

	G136: 来源类型以 lockfile 安装期记录为准，**不再信 manifest 自声明的
	``source_type``**（GitHub 插件把 plugin.json 写成 ``"local"`` 也无法免批）。
	仅在 lockfile 无登记(手工拷贝/本地开发目录)时回退 manifest 声明；
	lock 有登记的 github/npm 一律需显式批准。
	"""
	if not cfg.plugin_enabled(p.name):
		return False
	effective = _lockfile_source_type(cwd, p.name, scope=scope)
	if effective is None:
		# 未登记目录:本地开发手工放置仍可用;声明为远程而未登记的仍 fail-closed。
		claimed = getattr(p.manifest, "source_type", "local") or "local"
		effective = claimed if claimed in ("local", "github", "npm") else None
	if effective == "local":
		return True
	try:
		from extension.plugin_fetcher import is_plugin_trusted

		# effective∈{github,npm,None(未管理/声明未知)} 全部走信任文件;local 已在上面放行。
		return is_plugin_trusted(
			cwd, p.name, source_type=effective or "unmanaged"
		)
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
