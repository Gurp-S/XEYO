"""扩展层控制路径（P0b 最小版）：``GET/POST /v1/extensions/settings``。

与 ``/v1/skills`` 同源安全模型：``require_loopback``（非本机直接拒绝）。
POST 走 push reconcile（``set_mcp_enabled``/``set_skill_enabled``/
``set_extensions_enabled``）：settings.json 原子写 + T_now 活页块按 digest
幂等发布，由本进程下一次 chat 轮的 ``run_pre_llm_inject`` 消费注入。

GUI 完整面板（工具勾选矩阵/日志流）留 P1；本端点只暴露**启停**语义。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from server.local_gate import require_loopback

router = APIRouter(tags=["extensions"])


class _EntryToggle(BaseModel):
    enabled: bool


class ExtensionsSettingsBody(BaseModel):
    """POST 体：只收启停语义（新增 server/skill 声明走 mcp.json / plugins）。"""

    workspace: str | None = Field(default=None, max_length=1024)
    enabled_extensions: bool | None = None
    mcp_servers: dict[str, _EntryToggle] | None = None
    skills: dict[str, _EntryToggle] | None = None
    plugins: dict[str, _EntryToggle] | None = None
    plugins: dict[str, _EntryToggle] | None = None


def _merged_view(ws: str | None) -> dict[str, Any]:
    from extension.config import home_settings_path, load_ext_config, workspace_settings_path

    cfg = load_ext_config(ws)
    return {
        "ok": True,
        "enabled_extensions": bool(cfg.enabled_extensions),
        "paths": {
            "workspace_settings": str(workspace_settings_path(ws)) if ws else "",
            "home_settings": str(home_settings_path()),
        },
        "plugins": {k: {"enabled": bool(v.get("enabled", False))} for k, v in (cfg.plugins or {}).items()},
        "skills": {k: {"enabled": bool(v.get("enabled", True))} for k, v in (cfg.skills or {}).items()},
        "mcp_servers": {
            k: {
                "enabled": bool(v.get("enabled", False)),
                "auto_start": bool(v.get("auto_start", True)),
            }
            for k, v in (cfg.mcp_servers or {}).items()
        },
    }


@router.get("/v1/extensions/settings")
def get_extensions_settings(
    request: Request,
    workspace: str | None = Query(default=None, max_length=1024),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """返回合并视图（home + workspace）的扩展层启停状态。"""
    _ = authorization
    require_loopback(request)
    from server.deps import CWD

    ws = (workspace or "").strip() or (CWD or "")
    try:
        return _merged_view(ws or None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}


@router.post("/v1/extensions/settings")
def post_extensions_settings(
    body: ExtensionsSettingsBody,
    request: Request,
    workspace: str | None = Query(default=None, max_length=1024),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """应用启停变更（workspace 级；push reconcile：原子写 + 活页块幂等）。

    ``workspace`` 可走 query（与 GET 一致）或 body；缺省回退已登记 UI cwd。
    """
    _ = authorization
    require_loopback(request)
    from extension.config import (
        set_extensions_enabled,
        set_mcp_enabled,
        set_skill_enabled,
    )
    from server.deps import CWD

    ws = (workspace or body.workspace or "").strip() or (CWD or "")
    applied: dict[str, Any] = {"mcp_servers": [], "skills": [], "master": None}
    errors: list[str] = []
    try:
        if body.enabled_extensions is not None:
            set_extensions_enabled(ws or None, bool(body.enabled_extensions))
            applied["master"] = bool(body.enabled_extensions)
        for sid, toggle in (body.mcp_servers or {}).items():
            try:
                set_mcp_enabled(ws or None, str(sid), bool(toggle.enabled))
                applied["mcp_servers"].append({"id": str(sid), "enabled": bool(toggle.enabled)})
            except Exception as exc:  # noqa: BLE001 — 单项失败不影响其它项
                errors.append(f"mcp_servers/{sid}: {exc}")
        for name, toggle in (body.skills or {}).items():
            try:
                set_skill_enabled(ws or None, str(name), bool(toggle.enabled))
                applied["skills"].append({"name": str(name), "enabled": bool(toggle.enabled)})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"skills/{name}: {exc}")
        for name, toggle in (body.plugins or {}).items():
            try:
                set_plugin_enabled(ws or None, str(name), bool(toggle.enabled))
                applied["plugins"].append({"name": str(name), "enabled": bool(toggle.enabled)})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"plugins/{name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc), "applied": applied, "errors": errors}
    out = _merged_view(ws or None)
    out["applied"] = applied
    if errors:
        out["errors"] = errors
    return out
