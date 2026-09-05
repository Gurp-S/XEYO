"""插件管理控制路径：``GET /v1/plugins`` + ``POST /v1/plugins/{install|update|remove}`` + ``GET /v1/plugins/market``。

与 ``/v1/extensions/settings`` 同源安全模型：``require_loopback``（非本机直接拒绝）。

安全约定：
- 安装/更新/卸载均要求扩展层主开关已开（否则 fail-closed 返回错误）。
- 安装前检查企业 ``plugin_deny`` 一票否决；命中则回滚并报错。
- 远程源安装默认未受信（fail-closed），需 ``approve`` 后才激活；本地源免批。
- 安装失败/失败 rollback 都尽力而为（单脚本失败不阻断；错误带 ``errors`` 列表）。

GUI 完整安装 UI 留后续；本端点只暴露**控制语义**（安装/更新/卸载/列表/市场）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from server.local_gate import require_loopback

router = APIRouter(tags=["plugins"])


class InstallBody(BaseModel):
	source: str = Field(min_length=1, max_length=1024)
	allow_update: bool = False


class UpdateBody(BaseModel):
	name: str = Field(min_length=1, max_length=256)


class RemoveBody(BaseModel):
	name: str = Field(min_length=1, max_length=256)


def _plugins_view(ws: str | None) -> dict[str, Any]:
	from extension.config import load_ext_config, workspace_settings_path
	from extension.loader import discover_plugins, loaded_plugins_with_errors
	from extension.plugin_store import default_lock_path, detect_drift, load_plugins

	cfg = load_ext_config(ws)
	lock = default_lock_path(ws)
	items: list[dict[str, Any]] = []
	for lp in discover_plugins(ws, config=cfg):
		man = lp.plugin.manifest
		items.append(
			{
				"name": lp.name,
				"enabled": bool(lp.enabled),
				"declared": bool(man.enabled),
				"source_scope": getattr(lp, "source_scope", ""),
				"version": man.version,
				"min_xeyo": man.min_xeyo,
				"description": man.description[:200],
				"source": man.source,
				"source_type": man.source_type,
				"skills": list(man.skills),
				"mcp_servers": [s.id for s in man.mcp_servers],
				"has_hooks": bool(getattr(man, "hooks", [])),
			}
		)
	_, errs = loaded_plugins_with_errors(ws, config=cfg)
	registered = load_plugins(lock)
	return {
		"ok": True,
		"enabled_extensions": bool(cfg.enabled_extensions),
		"plugin_market": bool(cfg.plugin_market_enabled()),
		"workspace_settings": str(workspace_settings_path(ws)) if ws else "",
		"plugins": items,
		"registered": list(registered.keys()),
		"errors": errs,
		"drift": detect_drift(lock),
	}


@router.get("/v1/plugins")
def get_plugins(
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""返回插件视图（发现 + lockfile 登记 + 漂移 + 坏清单）。"""
	_ = authorization
	require_loopback(request)
	from server.deps import CWD

	ws = (workspace or "").strip() or (CWD or "")
	try:
		return _plugins_view(ws or None)
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "message": str(exc)}


@router.post("/v1/plugins/install")
def install_plugin(
	body: InstallBody,
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""安装插件（source 见 extension.plugin_fetcher.parse_source）。"""
	_ = authorization
	require_loopback(request)
	from server.deps import CWD

	ws = (workspace or "").strip() or (CWD or "")
	try:
		return _do_install(ws or None, body.source, body.allow_update)
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "message": str(exc)}


def _do_install(ws: str | None, source: str, allow_update: bool) -> dict[str, Any]:
	from extension.config import load_ext_config
	from extension.mcp_scopes import plugin_denied
	from extension.plugin_fetcher import install_from_spec, remove_plugin

	cfg = load_ext_config(ws)
	if not cfg.enabled_extensions:
		return {
			"ok": False,
			"message": "扩展层默认关闭；先在 .xeyo/settings.json 打开 enabled_extensions。",
		}
	res = install_from_spec(ws, source, allow_update=allow_update)
	name = str(res["name"])
	entry = res["entry"]
	# 企业 deny 一票否决：命中 → 回滚（fail-closed）。
	if plugin_denied(name):
		try:
			remove_plugin(ws, name, owner_source=str(entry.get("source") or ""))
		except Exception:  # noqa: BLE001
			pass
		return {"ok": False, "message": f"plugin '{name}' is denied by enterprise policy."}
	view = _plugins_view(ws)
	view["ok"] = True
	view["installed"] = {"name": name, "source": entry.get("source"), "source_type": entry.get("sourceType")}
	return view


@router.post("/v1/plugins/update")
def update_plugin(
	body: UpdateBody,
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""按登记来源重拉（update）；未登记 → 错误。"""
	_ = authorization
	require_loopback(request)
	from server.deps import CWD

	ws = (workspace or "").strip() or (CWD or "")
	from extension.config import load_ext_config
	from extension.plugin_fetcher import update_from_registry

	if not load_ext_config(ws or None).enabled_extensions:
		return {"ok": False, "message": "扩展层默认关闭。"}
	try:
		entry = update_from_registry(ws, body.name)
		view = _plugins_view(ws or None)
		view["ok"] = True
		view["updated"] = {"name": body.name, "source": entry.get("source")}
		return view
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "message": str(exc)}


@router.post("/v1/plugins/remove")
def remove_plugin_endpoint(
	body: RemoveBody,
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""卸载（归属校验：仅允许删本来源登记条目）。"""
	_ = authorization
	require_loopback(request)
	from server.deps import CWD

	ws = (workspace or "").strip() or (CWD or "")
	from extension.plugin_fetcher import remove_plugin
	from extension.plugin_store import default_lock_path, load_plugins

	entry = load_plugins(default_lock_path(ws)).get(body.name)
	try:
		existed = remove_plugin(ws, body.name, owner_source=str(entry.get("source") or "") if entry else "")
		view = _plugins_view(ws or None)
		view["ok"] = True
		view["removed"] = body.name
		view["existed"] = existed
		return view
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "message": str(exc)}


@router.get("/v1/plugins/market")
def plugin_market(
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""市场白名单源列表（``<home>/plugin-market.json`` + 企业白名单过滤）。"""
	_ = authorization
	require_loopback(request)
	from server.deps import CWD

	ws = (workspace or "").strip() or (CWD or "")
	from extension.config import load_ext_config

	cfg = load_ext_config(ws or None)
	if not cfg.plugin_market_enabled():
		return {"ok": True, "enabled": False, "sources": []}
	from extension.mcp_scopes import load_enterprise_policy, plugin_market_allowed
	from server.plugin_market import load_market_registry

	pol = load_enterprise_policy()
	registry = load_market_registry()
	sources = [s for s in registry if plugin_market_allowed(str(s.get("source") or ""), policy=pol)]
	return {"ok": True, "enabled": True, "sources": sources}
