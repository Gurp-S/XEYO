"""MCP 运行时接线（F1）：workspace 级进程单例，把 MCP server 挂到会话 registry。

设计（对齐 ``docs/设计/40-MCP与SKILL企业级融合设计.md`` §F1）：

- ``McpManager`` 按 resolved cwd 进程级单例（``get_mcp_manager(cwd)``）。
- ``collect_specs`` 汇三来源（plugin>user>project 按 id 冲突 project 胜出，企业
  deny 一票否决）——见 ``extension.mcp_scopes``。
- server 身份 = canonical 配置 sha256；attach 时按身份复用 ready client
  （Codex ``reusable_client`` 语义），身份变更才重连（引擎重建不重 spawn）。
- ``required:true`` server 启动失败 → 不挡会话（工具不进快照）+ 挂 T_now 警告
  ``# MCP 依赖异常（background only）`` + 审计。
- ``attach_mcp_tools(registry, cwd)`` 用现有 ``McpTool`` 注册工具；扩展层关 →
  一次读盘 no-op（内置 21 工具零变化）。
- env 契约：字面 K/V + ``env_vars`` 白名单 + ``bearer_token_env_var`` 按名密钥，
  无 ``${VAR}`` 展开（见 ``extension.mcp_client.sanitize_env``）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.abort import AbortController  # noqa: F401  # 保持类型引用一致性
from extension.config import (
	ExtensionConfig,
	home_settings_path,
	load_ext_config,
	workspace_settings_path,
	write_settings,
)
from extension.errors import ConfigError
from extension import mcp_client as mc
from extension import mcp_scopes as scopes
from extension.mcp_client import (
	MAX_SERVER_SCHEMA_BYTES,
	MAX_TOOL_SCHEMA_BYTES,
	STARTUP_TIMEOUT_S,
	TOOL_TIMEOUT_S,
	McpClientSpec,
	McpServerRuntime,
	McpTool,
	make_mcp_tool,
	max_visible_tools,
	spec_tool_enabled,
	tool_is_model_visible,
)

_log = logging.getLogger(__name__)

#: 进程级单例表（按 realpath cwd）。
MANAGERS: dict[str, "McpManager"] = {}
_MANAGER_LOCK = threading.Lock()


@dataclass
class _ServerRuntime:
	"""一个 server 的运行时 + 身份（config sha256）+ 复用客户端。"""

	identity: str
	client: Any  # McpStdioClient
	runtime: McpServerRuntime
	spec: McpClientSpec
	started: bool = False
	error: str = ""
	#: F2：本次注册被降级 hidden 的注册名（snapshot//mcp 标注用）。
	hidden_tools: list[str] = field(default_factory=list)
	#: F2 网关：raw 工具名 → 本次注册的 McpTool（含 hidden；resolve 用）。
	tools: dict[str, "McpTool"] = field(default_factory=dict)

	def stop(self) -> None:
		try:
			self.runtime.stop()
		except Exception:  # noqa: BLE001
			_log.debug("mcp server stop failed", exc_info=True)


def _resolve_cwd(cwd: str | None) -> str:
	raw = (cwd or "").strip() or os.getcwd()
	try:
		return os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
	except OSError:
		return raw


class McpManager:
	"""按 workspace 进程级单例的 MCP 生命周期/接线协调器。"""

	def __init__(self, cwd: str | None = None, *, transport_factory: Any = None) -> None:
		self._cwd = _resolve_cwd(cwd)
		self._lock = threading.Lock()
		self._transport_factory = transport_factory
		self._servers: dict[str, _ServerRuntime] = {}
		self._required_failed: dict[str, str] = {}
		self._unapproved: dict[str, str] = {}
		self._config: ExtensionConfig | None = None
		self._config_sig: tuple[tuple[int, int], ...] | None = None
		#: attach 期静默外部 diff 探测（会话重建不误报「工具面变更」）。
		self._diff_quiet = False
		#: 探针用的当前 spec 声明缓存（settings 签名失效）。
		self._spec_cache: dict[str, dict[str, Any]] | None = None
		self._spec_cache_sig: tuple[tuple[int, int], ...] | None = None

	@property
	def cwd(self) -> str:
		return self._cwd

	# -- config (cached; mtime-based invalidation => extension-off = +1 read) ---

	def _settings_sig(self) -> tuple[tuple[int, int], ...]:
		"""失效签名：settings/mcp.json 两级 × (mtime_ns, size)。

		size 参与：同 tick 内连续写入（测试/原子替换）mtime 可能不变。
		"""

		def _sig(p: Any) -> tuple[int, int]:
			try:
				st = p.stat()
				return (int(st.st_mtime_ns), int(st.st_size))
			except OSError:
				return (0, 0)

		project_mcp, user_mcp = scopes.mcp_scope_paths(self._cwd)
		return (
			_sig(home_settings_path()),
			_sig(workspace_settings_path(self._cwd)),
			_sig(project_mcp),
			_sig(user_mcp),
		)

	def _load_config(self) -> ExtensionConfig:
		sig = self._settings_sig()
		if self._config is not None and self._config_sig == sig:
			return self._config
		new_cfg = load_ext_config(self._cwd)
		# F2.5 pull 兜底：会话运行中检出**外部**启停变化（另一进程/CLI 写盘）
		# → 补发一次活页块（digest 幂等）；attach 期静默（catalog 本就重塑）。
		if self._config is not None and not self._diff_quiet:
			self._publish_config_diff(self._config, new_cfg)
		self._config = new_cfg
		self._config_sig = sig
		return self._config

	def _publish_config_diff(self, old: ExtensionConfig, new: ExtensionConfig) -> None:
		"""外部启停变化 → 活页块（digest 幂等；探测失败静默）。"""
		try:
			from extension.reconcile import publish_if_changed

			changed: dict[str, bool] = {}
			for sid in sorted(set(old.mcp_servers) | set(new.mcp_servers)):
				was = old.mcp_enabled(sid)
				now = new.mcp_enabled(sid)
				if was != now:
					changed[sid] = now
			if not changed:
				return

			def _build() -> str:
				from extension.reconcile import build_mcp_block

				parts = ["# 工具面变更（background only — 非用户新提问）"]
				for sid, now in changed.items():
					kind = "启用" if now else "停用"
					parts.append(
						f"- MCP 服务 `{sid}` 已被{kind}（会话内即时生效：停用→调用被拒绝；"
						"原生目录下个会话重塑）。"
					)
				_ = build_mcp_block  # 保持同源文案引用
				return "\n".join(parts)

			publish_if_changed("mcp_external", dict(changed), _build)
		except Exception:  # noqa: BLE001 — 兜底通知失败不影响配置读取
			_log.debug("mcp config diff publish failed", exc_info=True)

	def collect_specs(self, *, config: ExtensionConfig | None = None) -> dict[str, dict[str, Any]]:
		"""三来源汇集（见 ``mcp_scopes.collect_mcp_specs``）。"""
		cfg = config if config is not None else self._load_config()
		return scopes.collect_mcp_specs(self._cwd, config=cfg)

	def config_snapshot(self) -> ExtensionConfig:
		return self._load_config()

	# -- attach -------------------------------------------------------------

	def attach_mcp_tools(self, registry: Any, cwd: str | None = None) -> "McpManager":
		"""把启用的 MCP server 工具挂到 ``registry``（F1 接线点调用）。

		扩展层关 → 一次读盘 no-op（返回自身）。幂等：同一 registry 重复 attach
		不会重复注册同名工具（registry.register 覆盖，但 tools 数组不变例外）。
		P0b：同时常驻注册网关工具 ``Mcp``（会话内新增/探查工具的唯一通道）。
		"""
		_ = cwd
		self._diff_quiet = True
		try:
			cfg = self._load_config()
		finally:
			self._diff_quiet = False
		if not cfg.enabled_extensions:
			return self
		specs = self.collect_specs(config=cfg)
		apply_vision = self._registry_vision(registry)
		with self._lock:
			for sid in sorted(specs):
				if not cfg.mcp_enabled(sid):
					continue
				if not scopes.is_server_trusted(self._cwd, specs[sid]):
					self._unapproved[sid] = "unapproved project-scope server (run /mcp approve)"
					self._servers.pop(sid, None)
					continue
				self._attach_one(registry, sid, specs[sid], apply_vision)
		try:
			from extension.mcp_gateway import McpGatewayTool

			registry.register(McpGatewayTool(self))
		except Exception:  # noqa: BLE001 — 网关注册失败不搞挂 attach
			_log.warning("mcp gateway registration failed", exc_info=True)
		return self

	def _attach_one(self, registry: Any, sid: str, spec_d: dict[str, Any], apply_vision: bool) -> None:
		spec = _client_spec_from_dict(spec_d)
		identity = scopes.declaration_hash(spec_d)
		entry = self._servers.get(sid)
		if entry is None or entry.identity != identity:
			if entry is not None:
				entry.stop()
			runtime = McpServerRuntime(
				spec,
				registry=None,
				transport_factory=self._transport_factory,
			)  # registry none → manager 直接注册
			started = False
			start_error = ""
			try:
				started = runtime.start(fetch=True, force=False)
			except Exception as e:  # noqa: BLE001 — 单个坏 server 不搞挂 attach
				_log.warning("mcp server %s start raised: %s", spec.id, e)
				start_error = str(e)
			if started and not runtime.client.ready:
				started = False  # auto_start=false / 未连上 → 不注册工具
			entry = _ServerRuntime(
				identity=identity,
				client=runtime.client,
				runtime=runtime,
				spec=spec,
				started=started,
				error=start_error,
			)
			self._servers[sid] = entry
		else:
			# 身份复用：客户端已 ready，不重 spawn；仅刷新 started 兜底。
			entry.started = bool(entry.client.ready)
		if entry.started:
			self._register_generation(registry, entry, apply_vision)
			self._required_failed.pop(sid, None)
		else:
			if spec.required:
				self._required_failed[sid] = "required server not ready"
			self._log_server_failure(sid, entry)

	def _register_generation(self, registry: Any, entry: _ServerRuntime, apply_vision: bool) -> None:
		"""从复用客户端把当前 generation 的工具注册进本会话 registry。

		F2 三层可见性（P0b）：**全量注册**（含未勾选/超限），hidden 只影响
		是否进 schemas（``ToolRegistry.schemas`` 按 exposure 过滤）—— 模型
		幻觉调用 hidden 工具仍走权限三态（fail-safe，§2 决策 4 完整语义）。
		hidden 集合在会话内不变（tools 数组冻结红线）。
		"""
		client = entry.client
		spec = entry.spec
		built: list[McpTool] = []
		total = 0
		for name, raw_schema in client.tool_schemas().items():
			raw_name = str(raw_schema.get("name") or "")
			if not raw_name:
				continue
			tool = make_mcp_tool(client, spec, raw_schema, name, apply_vision=apply_vision)
			# F2.5 移除→DENY 门：探针按 mtime 缓存即时读效（push/pull 双通道）。
			tool.enabled_probe = self._make_enabled_probe(spec, raw_name)
			hidden = False
			# ① GUI 勾选 enabled_tools：未勾选 → hidden。
			if not spec_tool_enabled(spec, raw_name):
				hidden = True
			# ② server 自标注 _meta.ui.visibility 不含 "model" → hidden。
			if not hidden and not tool_is_model_visible(raw_schema):
				hidden = True
			# ③ 尺寸预算：单工具 >8KB → hidden；server 总量 >64KB → 溢出隐藏。
			try:
				size = len(json.dumps(raw_schema, ensure_ascii=False).encode("utf-8"))
			except Exception:  # noqa: BLE001 — 不可序列化 spec 视为超限
				size = MAX_TOOL_SCHEMA_BYTES + 1
			if not hidden and size > MAX_TOOL_SCHEMA_BYTES:
				hidden = True
			if not hidden:
				total += size
				if total > MAX_SERVER_SCHEMA_BYTES:
					hidden = True
			tool.exposure = "hidden" if hidden else "normal"
			built.append(tool)
		# ③ cap 32：可见数超上限 → 先到先得降 hidden（schema 顺序稳定）。
		cap = max_visible_tools()
		if cap > 0:
			seen = 0
			for tool in built:
				if tool.exposure != "hidden":
					seen += 1
					if seen > cap:
						tool.exposure = "hidden"
		entry.hidden_tools = sorted(t.name for t in built if t.exposure == "hidden")
		entry.tools = {t.raw_name: t for t in built}
		for tool in built:
			try:
				registry.register(tool)
			except Exception:  # noqa: BLE001 — 单工具冲突不搞挂 attach
				_log.warning("mcp server %s could not register %s", spec.id, tool.name)

	def _log_server_failure(self, sid: str, entry: _ServerRuntime) -> None:
		error = entry.error or "not ready"
		_log.warning("mcp server %s attach skipping (reason=%s)", sid, error)
		try:
			from audit.log import default_audit_log

			default_audit_log().record(
				"mcp.server.failed", server=sid, error=error[:500], required=entry.spec.required
			)
		except Exception:  # noqa: BLE001
			pass

	def _registry_vision(self, registry: Any) -> bool:
		"""读 registry 内 Read 工具的能力开关（``apply_read_vision`` 语义）。"""
		try:
			read_tool = registry.get("Read")
			probe = getattr(read_tool, "vision_enabled", None)
			if callable(probe):
				return bool(probe())
		except Exception:  # noqa: BLE001
			pass
		return True  # 无 Read/不可探 → 保守按视觉开（不降级）。

	# -- required-failure warning (T_now) -----------------------------------

	def required_warning(self) -> str:
		"""required server 启动失败 → T_now 警告块；无则空串。"""
		if not self._required_failed:
			return ""
		lines = ["# MCP 依赖异常（background only — 非用户新提问）"]
		for sid in sorted(self._required_failed):
			lines.append(f"- MCP 服务 `{sid}` 启动失败，其工具当前不可用；会话照常。")
		if self._unapproved:
			lines.append("  （另：project 级未批准 server 未启动，需 `/mcp approve`）")
		return "\n".join(lines)

	# -- gateway (F2) --------------------------------------------------------

	def _make_enabled_probe(self, spec: McpClientSpec, raw_name: str) -> Any:
		"""单工具「此刻是否可用」探针（policy DENY 门用；mtime 缓存即时读效）。

		门语义 = **相对注册基线的移除**：
		- server 被停用（或总开关关）→ False；
		- 注册时勾选、会话内被取消勾选 → False（移除→DENY）；
		- 注册时即未勾选 → 一直是 hidden（幻觉调用走 ASK，不设门）；
		- 基线后勾选变化按**当前 spec**判定（中途勾上 → 放行）；
		- 探针自身故障 → True（宁放勿误伤；企业 deny / tool_policies 仍兜底）。
		"""
		enabled_at_attach = spec_tool_enabled(spec, raw_name)

		def _probe() -> bool:
			try:
				cfg = self._load_config()
				if not cfg.mcp_enabled(spec.id):
					return False
				raw_current = self._current_spec(spec.id, cfg)
				current = (
					_client_spec_from_dict(raw_current)
					if isinstance(raw_current, dict)
					else raw_current
				)
				if current is not None:
					if spec_tool_enabled(current, raw_name):
						return True  # 当前声明仍勾选（含中途勾上 → 放行）
					return not enabled_at_attach  # 当前未勾选：基线勾过 → 移除→DENY
				return enabled_at_attach  # 当前声明不可得 → 保守按基线
			except Exception:  # noqa: BLE001
				return True

		return _probe

	def _current_spec(self, sid: str, cfg: ExtensionConfig) -> dict[str, Any] | None:
		"""按 settings 签名缓存的**当前** server 声明（勾选变化即时读效）。"""
		try:
			sig = self._settings_sig()
			if self._spec_cache is None or self._spec_cache_sig != sig:
				self._spec_cache = self.collect_specs(config=cfg)
				self._spec_cache_sig = sig
			return self._spec_cache.get(sid)
		except Exception:  # noqa: BLE001
			return None

	def client_for(self, server_id: str) -> Any | None:
		"""F6b：就绪 server 的 stdio client（resources 网关化用）；未就绪 → None。"""
		entry = self._servers.get((server_id or "").strip())
		if entry is None or not entry.started:
			return None
		return entry.client

	def resolve_tool(self, server_id: str, raw_name: str) -> "McpTool | None":
		"""网关身份解析：**只在已知工具集内**匹配（注入免疫的根基）。

		精确 raw 名优先，casefold 兜底（模型常小写）；未启动/未注册 → None
		（policy 侧 fail-closed DENY）。
		"""
		sid = (server_id or "").strip()
		raw = (raw_name or "").strip()
		if not sid or not raw:
			return None
		entry = self._servers.get(sid)
		if entry is None or not entry.started:
			return None
		tool = entry.tools.get(raw)
		if tool is None:
			tool = next(
				(t for n, t in entry.tools.items() if n.casefold() == raw.casefold()),
				None,
			)
		return tool

	def gateway_catalog(self) -> list[dict[str, Any]]:
		"""``Mcp{action:list}`` 数据源：全量 server 侧集合（含 hidden 标注）。"""
		out: list[dict[str, Any]] = []
		for sid in sorted(self._servers):
			entry = self._servers[sid]
			tools: list[dict[str, Any]] = []
			for raw in sorted(entry.tools):
				tool = entry.tools[raw]
				try:
					desc = str(tool.schema().get("description") or "").splitlines()
				except Exception:  # noqa: BLE001
					desc = []
				tools.append(
					{
						"tool": raw,
						"name": tool.name,
						"hidden": tool.exposure == "hidden",
						"description": (desc[0].strip() if desc else "")[:160],
					}
				)
			out.append(
				{
					"server": sid,
					"state": "ready" if entry.started else "failed",
					"required": entry.spec.required,
					"tools": tools,
				}
			)
		return out

	def snapshot(self) -> dict[str, Any]:
		"""调试/面板视图：server 状态 + 工具 + hidden 标注 + 脱敏。"""
		out: dict[str, Any] = {"servers": {}, "required_failed": dict(self._required_failed)}
		for sid, entry in self._servers.items():
			out["servers"][sid] = {
				"state": "ready" if entry.started else "failed",
				"tools": sorted(entry.client.tool_schemas()) if entry.client else [],
				"hidden_tools": list(entry.hidden_tools),
				"required": entry.spec.required,
			}
		return out

	def shutdown(self) -> None:
		"""停止全部 server（app lifespan finally 调用）。"""
		with self._lock:
			for entry in list(self._servers.values()):
				entry.stop()
			self._servers.clear()


def set_mcp_tool_enabled(
	cwd: str | None, server_id: str, raw_name: str, enabled: bool
) -> str:
	"""F2.5 控制路径：勾选/取消勾选单工具（写回**声明它的** mcp.json）。

	- 找声明文件：project（``<ws>/.xeyo/mcp.json``）优先，其次 user（``~/.xeyo/mcp.json``）；
	- ``enabled_tools`` 缺省（全量）→ 先从运行中 client 枚举全量再落白名单；
	- 原子写（config.write_settings）；返回人话结果，失败抛 ConfigError。
	"""
	sid = (server_id or "").strip()
	raw = (raw_name or "").strip()
	if not sid or not raw:
		raise ConfigError("set_mcp_tool_enabled: server_id/raw_name required")
	project, user = scopes.mcp_scope_paths(cwd)
	target: Path | None = None
	data: dict[str, Any] | None = None
	for cand in (project, user):
		if cand is None or not Path(cand).is_file():
			continue
		try:
			parsed = json.loads(Path(cand).read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			continue
		if isinstance(parsed, dict) and sid in (parsed.get("servers") or {}):
			target = Path(cand)
			data = parsed
			break
	if target is None or data is None:
		raise ConfigError(f"server {sid!r} 未在 project/user mcp.json 声明，无法勾选")
	servers = dict(data.get("servers") or {})
	entry = dict(servers.get(sid) or {})
	current = entry.get("enabled_tools")
	if not isinstance(current, list):
		# 全量缺省 → 从运行中 client 枚举（server 未运行则要求先启动）。
		mgr = get_mcp_manager(cwd)
		client = mgr.client_for(sid)
		if client is None:
			raise ConfigError(
				f"server {sid!r} 未运行，无法枚举全量工具名；请先启动后再勾选"
			)
		try:
			schemas = client.tool_schemas()
		except Exception as e:  # noqa: BLE001
			raise ConfigError(f"枚举 {sid!r} 工具失败: {e}") from e
		current = [str(v.get("name") or "") for v in schemas.values() if v.get("name")]
	names = [str(x) for x in current if str(x)]
	if enabled:
		if raw not in names:
			names.append(raw)
	else:
		names = [n for n in names if n != raw]
	entry["enabled_tools"] = names
	servers[sid] = entry
	data["servers"] = servers
	write_settings(target, data)
	return (
		f"已勾选 {sid}/{raw}" if enabled else f"已取消勾选 {sid}/{raw}"
	) + f"（白名单 {len(names)} 项；下个会话进/出目录，会话内调用侧即时生效）"


def _client_spec_from_dict(d: dict[str, Any]) -> McpClientSpec:
	"""配置契约 dict → :class:`McpClientSpec`（字段容错 + 默认值）。"""
	args = d.get("args")
	env = d.get("env")
	tool_policies = d.get("tool_policies")
	read_only = d.get("read_only_tools")
	enabled_tools = d.get("enabled_tools")
	output_limits = d.get("output_token_limits")
	env_vars = d.get("env_vars")
	try:
		startup = float(d.get("startup_timeout_s", d.get("startup_timeout_sec", STARTUP_TIMEOUT_S)))
	except (TypeError, ValueError):
		startup = STARTUP_TIMEOUT_S
	try:
		tool_timeout = float(d.get("tool_timeout_s", d.get("tool_timeout_sec", TOOL_TIMEOUT_S)))
	except (TypeError, ValueError):
		tool_timeout = TOOL_TIMEOUT_S
	limits: dict[str, int] = {}
	for k, v in (output_limits or {}).items():
		try:
			limits[str(k)] = int(v)
		except (TypeError, ValueError):
			continue
	return McpClientSpec(
		id=str(d.get("id") or ""),
		command=str(d.get("command") or ""),
		args=tuple(str(x) for x in args) if args else (),
		env={str(k): str(v) for k, v in (env or {}).items()},
		auto_start=bool(d.get("auto_start", True)),
		tools_policy=str(d.get("tools_policy") or "outbound_ask"),
		tool_policies={str(k): str(v) for k, v in (tool_policies or {}).items()},
		startup_timeout_s=startup,
		tool_timeout_s=tool_timeout,
		env_vars=tuple(str(x) for x in env_vars) if env_vars else (),
		bearer_token_env_var=str(d.get("bearer_token_env_var") or ""),
		env_mode=str(d.get("env_mode") or "scrub"),
		required=bool(d.get("required", False)),
		elicit=bool(d.get("elicit", False)),
		trust_annotations=bool(d.get("trust_annotations", False)),
		read_only_tools=tuple(str(x) for x in read_only) if read_only else (),
		enabled_tools=tuple(str(x) for x in enabled_tools) if enabled_tools is not None else None,
		output_token_limits=limits,
	)


# --------------------------------------------------------------------------- #
# 进程级单例 + 全局清理。
# --------------------------------------------------------------------------- #

def get_mcp_manager(cwd: str | None = None) -> McpManager:
	"""返回 resolved cwd 的进程级单例。"""
	key = _resolve_cwd(cwd)
	with _MANAGER_LOCK:
		mgr = MANAGERS.get(key)
		if mgr is None:
			mgr = McpManager(key)
			MANAGERS[key] = mgr
		return mgr


def shutdown_all_managers() -> None:
	"""全局清理（server/app.py lifespan finally 调用）。"""
	with _MANAGER_LOCK:
		mgrs = list(MANAGERS.values())
	for mgr in mgrs:
		mgr.shutdown()


def mcp_required_warning_block(cwd: str | None = None) -> str:
	"""T_now 注入点：当前 workspace 无 required 失败则空串。"""
	try:
		return get_mcp_manager(cwd).required_warning()
	except Exception:  # noqa: BLE001
		return ""


def attach_mcp_tools(registry: Any, cwd: str | None = None) -> McpManager | None:
	"""接线点薄封装（session_pool._build / build_default_engine 调用）。

	扩展层关 → 一次读盘 no-op；开 → 挂工具。返回 manager（供测试/调试）。
	"""
	mgr = get_mcp_manager(cwd)
	mgr.attach_mcp_tools(registry)
	return mgr


# 供测试重开单例（进程内并发场景）。
def reset_managers() -> None:
	with _MANAGER_LOCK:
		for mgr in MANAGERS.values():
			mgr.shutdown()
		MANAGERS.clear()
