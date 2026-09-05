"""MCP scope 文件读取：project / user / plugin 三来源汇集 + 信任 + 企业 deny。

契约（对齐 ``docs/设计/40-MCP与SKILL企业级融合设计.md`` §7 配置契约）：

- project scope：``<ws>/.xeyo/mcp.json``（首次 spawn 前需 approve，存信任）
- user scope：``~/.xeyo/mcp.json``（免批）
- plugin scope：插件 manifest ``mcp_servers``（免批）

同名 id 冲突优先级 **project > user > plugin**（高优先级覆盖低优先级）；企业
deny（``~/.xeyo/policy.json``，env ``XEYO_ENTERPRISE_POLICY`` 可覆盖路径）
**一票否决**——命中 deny 的 server/tool 无条件剔除，低级 scope 不可覆盖。

本模块只负责「配置/信任/deny 的纯读取与合并」，不做 spawn / 生命周期（见
``extension.mcp_manager``）。坏配置一律跳过并记录（broken-but-listed），不让单个
坏文件搞挂启动。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from extension.config import ExtensionConfig, load_ext_config
from extension.loader import discover_plugins

_log = logging.getLogger(__name__)

#: 允许的 MCP 权限分类（与 tools.meta / manifest.McpPolicy 对齐）。
MCP_POLICIES = ("always_allow", "outbound_ask", "ui_ask")
#: 允许的 env_mode。
ENV_MODES = ("scrub", "minimal")

# 企业 deny 文件（env 可覆盖路径）。
_DEFAULT_ENTERPRISE_POLICY = Path.home() / ".xeyo" / "policy.json"


# --------------------------------------------------------------------------- #
# 配置契约字段（mcp.json server 声明的合法键）。
# --------------------------------------------------------------------------- #

#: 声明为原始字符串键即可；解析时按 McpClientSpec 名义字段映射。
_MCP_SERVER_FIELDS = {
	"command",
	"args",
	"env",
	"env_vars",
	"bearer_token_env_var",
	"env_mode",
	"auto_start",
	"required",
	"elicit",
	"trust_annotations",
	"startup_timeout_s",
	"tool_timeout_s",
	"tools_policy",
	"tool_policies",
	"read_only_tools",
	"enabled_tools",
	"output_token_limits",
}


def mcp_scope_paths(cwd: str | None) -> tuple[Path | None, Path]:
	"""返回 (project scope path|None, user scope path)。"""
	project = None
	if cwd:
		try:
			project = (
				Path(cwd).expanduser().resolve() / ".xeyo" / "mcp.json"
			)
		except OSError:
			project = None
	from memory.instruction import xeyo_home

	return project, xeyo_home() / "mcp.json"


def read_mcp_scope_files(cwd: str | None) -> dict[str, dict[str, Any]]:
	"""读取 project + user 两处 scope 文件；坏读/缺文件 → 空 dict（skip-and-log）。

	返回 ``{"project": {...}, "user": {...}}``（原始 JSON 对象；仅取 ``servers``）。
	"""
	out: dict[str, dict[str, Any]] = {"project": {}, "user": {}}
	project, user = mcp_scope_paths(cwd)
	if project is not None:
		raw = _read_json_file(project, "project")
		if raw and isinstance(raw.get("servers"), dict):
			out["project"] = raw["servers"]
	user_raw = _read_json_file(user, "user")
	if user_raw and isinstance(user_raw.get("servers"), dict):
		out["user"] = user_raw["servers"]
	return out


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
	"""读取一个 mcp.json；坏 JSON → 空 dict + 记录。"""
	if not path.is_file():
		return {}
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
		if isinstance(raw, dict):
			return raw
		_log.warning("mcp.json at %s (%s) is not an object; skipping", path, label)
		return {}
	except (OSError, json.JSONDecodeError) as e:
		_log.warning("bad mcp.json at %s (%s): %s; skipping", path, label, e)
		return {}


# --------------------------------------------------------------------------- #
# 插件 scope：从插件 manifest 汇集 mcp_servers。
# --------------------------------------------------------------------------- #

def load_plugin_mcp_specs(
	cwd: str | None = None,
	*,
	config: ExtensionConfig | None = None,
) -> dict[str, dict[str, Any]]:
	"""从启用的插件 manifest 汇集 ``mcp_servers``。

	插件 scope 免批；仅在插件 enabled（且主开关开）时纳入。返回
	``{server_id: manifest_spec_dict}``。
	"""
	out: dict[str, dict[str, Any]] = {}
	cfg = config if config is not None else load_ext_config(cwd)
	if not cfg.enabled_extensions:
		return out
	for lp in discover_plugins(cwd, config=cfg):
		if not lp.enabled:
			continue
		manifest = lp.plugin.manifest
		for spec in manifest.mcp_servers:
			raw = _spec_to_dict(spec)
			# 插件属性：来源标 plugin，带插件名。
			raw["_scope"] = "plugin"
			raw["_plugin"] = lp.name
			out.setdefault(str(raw.get("id") or ""), raw)
	return out


def _spec_to_dict(spec: Any) -> dict[str, Any]:
	"""把 manifest.McpServerSpec → 规整 dict。"""
	if hasattr(spec, "model_dump"):
		try:
			return dict(spec.model_dump(exclude_none=True))
		except Exception:  # noqa: BLE001
			pass
	d: dict[str, Any] = {}
	for f in _MCP_SERVER_FIELDS:
		if not hasattr(spec, f):
			continue
		v = getattr(spec, f)
		if v is not None:
			d[f] = v
	return d


# --------------------------------------------------------------------------- #
# 三来源合并（project > user > plugin）。
# --------------------------------------------------------------------------- #

def collect_mcp_specs(
	cwd: str | None = None,
	*,
	config: ExtensionConfig | None = None,
) -> dict[str, dict[str, Any]]:
	"""三来源汇集同一 ``servers.<id>``，冲突按 project > user > plugin。

	返回 ``{server_id: spec_dict}``。企业 deny 在此处一票否决（命中即剔除）。
	"""
	cfg = config if config is not None else load_ext_config(cwd)
	scoped = read_mcp_scope_files(cwd)
	plugin = load_plugin_mcp_specs(cwd, config=cfg)

	merged: dict[str, dict[str, Any]] = {}
	# 低优先级先入，高优先级后入覆盖（project 最后）。
	for scope in ("plugin", "user", "project"):
		source = (
			plugin
			if scope == "plugin"
			else scoped.get(scope, {})
		)
		for sid, raw in source.items():
			d = dict(raw)
			d["_scope"] = scope
			d.setdefault("id", sid)
			# project scope 标记需信任；user/plugin 免批。
			d.setdefault("_requires_trust", scope == "project")
			merged[sid] = d

	# 企业 deny 一票否决。
	pol = load_enterprise_policy()
	sid_list = list(merged.keys())
	for sid in sid_list:
		if sid in pol["mcp_server_deny"]:
			_log.info("mcp server %s denied by enterprise policy", sid)
			del merged[sid]
	return merged


# --------------------------------------------------------------------------- #
# 企业 deny 读取（~/.xeyo/policy.json，env XEYO_ENTERPRISE_POLICY 可覆盖）。
# --------------------------------------------------------------------------- #

def enterprise_policy_path() -> Path:
	override = os.environ.get("XEYO_ENTERPRISE_POLICY", "").strip()
	if override:
		return Path(override).expanduser()
	return _DEFAULT_ENTERPRISE_POLICY


def _default_enterprise_policy() -> dict[str, list[str]]:
	return {
		"mcp_server_deny": [],
		"mcp_tool_deny": [],
		"skill_deny": [],
		"plugin_market_allow": [],
		"plugin_deny": [],
	}


def load_enterprise_policy() -> dict[str, list[str]]:
	"""读取企业 deny 策略；坏读 → keep-last-good / 空（record + 审计）。"""
	path = enterprise_policy_path()
	if not path.is_file():
		return _default_enterprise_policy()
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
		if isinstance(raw, dict):
			return _normalize_policy(raw)
		_log.warning("policy.json at %s not an object; using defaults", path)
		_record_policy_invalid(path, "not a JSON object")
		return _default_enterprise_policy()
	except (OSError, json.JSONDecodeError) as e:
		_log.warning("bad policy.json at %s: %s; using defaults", path, e)
		_record_policy_invalid(path, str(e))
		return _default_enterprise_policy()


def _normalize_policy(raw: dict[str, Any]) -> dict[str, list[str]]:
	def _as_list(key: str) -> list[str]:
		v = raw.get(key)
		if isinstance(v, list):
			return [str(x) for x in v if str(x).strip()]
		return []

	return {
		"mcp_server_deny": _as_list("mcp_server_deny"),
		"mcp_tool_deny": _as_list("mcp_tool_deny"),
		"skill_deny": _as_list("skill_deny"),
		"plugin_market_allow": _as_list("plugin_market_allow"),
		"plugin_deny": _as_list("plugin_deny"),
	}


def _record_policy_invalid(path: Path, error: str) -> None:
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"config.invalid", path=str(path), error=error, action="enterprise_policy_defaults"
		)
	except Exception:  # noqa: BLE001 — 审计故障不影响回退
		pass


def mcp_server_denied(server_id: str, *, policy: dict[str, list[str]] | None = None) -> bool:
	"""企业 deny 是否命中 server（一票否决）。"""
	if not (server_id or "").strip():
		return False
	pol = policy if policy is not None else load_enterprise_policy()
	return server_id in pol["mcp_server_deny"]


def mcp_tool_denied(
	server_id: str, raw_name: str, *, policy: dict[str, list[str]] | None = None
) -> bool:
	"""企业 deny 是否命中单个工具（``server/raw`` 或 ``server/*``）。"""
	server_id = (server_id or "").strip()
	raw_name = (raw_name or "").strip()
	if not server_id or not raw_name:
		return False
	pol = policy if policy is not None else load_enterprise_policy()
	denies = pol["mcp_tool_deny"]
	if f"{server_id}/{raw_name}" in denies:
		return True
	if f"{server_id}/*" in denies:
		return True
	return False


def skill_denied(name: str, *, policy: dict[str, list[str]] | None = None) -> bool:
	pol = policy if policy is not None else load_enterprise_policy()
	return (name or "").strip() in pol["skill_deny"]


def plugin_denied(name: str, *, policy: dict[str, list[str]] | None = None) -> bool:
	"""企业 deny：插件名命中 ``plugin_deny`` 即一票否决（不可被低级 scope 覆盖）。"""
	pol = policy if policy is not None else load_enterprise_policy()
	return (name or "").strip() in pol["plugin_deny"]


def plugin_market_allowed(
	source: str, *, policy: dict[str, list[str]] | None = None
) -> bool:
	"""市场白名单：``plugin_market_allow`` 非空时仅列出的来源允许；空=全放白名单外源。

	注意：白名单只决定「市场浏览/来源检索」，真正的安装限制仍由
	``plugin_deny`` 一票否决 + 总开关 ``plugin_market`` 控制。
	"""
	pol = policy if policy is not None else load_enterprise_policy()
	allow = pol["plugin_market_allow"]
	if not allow:
		return True
	return (source or "").strip() in allow


# --------------------------------------------------------------------------- #
# 信任（project scope 首次 spawn 前 approve）。
# --------------------------------------------------------------------------- #

def trust_path(cwd: str | None) -> Path:
	from memory.instruction import xeyo_home

	if cwd:
		try:
			return Path(cwd).expanduser().resolve() / ".xeyo" / "mcp-trust.json"
		except OSError:
			pass
	return xeyo_home() / "mcp-trust.json"


def load_mcp_trust(cwd: str | None) -> dict[str, Any]:
	"""读取 ``<ws>/.xeyo/mcp-trust.json``（若不存在则是 user-level 兜底）。

	返回 ``{declaration_hash: {"approved": true, ...}}``。
	"""
	path = trust_path(cwd)
	if not path.is_file():
		return {}
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
		return dict(raw) if isinstance(raw, dict) else {}
	except (OSError, json.JSONDecodeError):
		return {}


def declaration_hash(spec: dict[str, Any]) -> str:
	"""server 声明（canonical JSON）的 sha256；信任键即按此 hash。"""
	canon = _canonical_declaration(spec)
	return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _canonical_declaration(spec: dict[str, Any]) -> str:
	"""对 server 声明做规范化序列化（键排序、无空白），作为身份/信任键。"""
	d = {k: v for k, v in spec.items() if not k.startswith("_")}
	return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def is_server_trusted(cwd: str | None, spec: dict[str, Any]) -> bool:
	"""project scope 是否已批准（按声明 hash）；user/plugin 免批恒 True。"""
	if not spec.get("_requires_trust"):
		return True
	h = declaration_hash(spec)
	trust = load_mcp_trust(cwd)
	entry = trust.get(h)
	return bool(entry and entry.get("approved"))
