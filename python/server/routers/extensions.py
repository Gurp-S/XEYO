"""扩展层控制路径（P0b 最小版）：``GET/POST /v1/extensions/settings``。

与 ``/v1/skills`` 同源安全模型：``require_loopback``（非本机直接拒绝）。
POST 走 push reconcile（``set_mcp_enabled``/``set_skill_enabled``/
``set_extensions_enabled``）：settings.json 原子写 + T_now 活页块按 digest
幂等发布，由本进程下一次 chat 轮的 ``run_pre_llm_inject`` 消费注入。

GUI 完整面板（工具勾选矩阵/日志流）留 P1；本端点只暴露**启停**语义。
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from server.deps import api_error
from server.local_gate import require_loopback

router = APIRouter(tags=["extensions"])

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def require_workspace_arg(raw: Any, *, field: str = "workspace") -> str:
    """``workspace`` 参数的路由边缘校验（skills / extensions / plugins 三面共用）。

    - 空 / 纯空白 → 返回空串，调用方照旧回退已登记 cwd（行为不变）。
    - 含控制字符（NUL / ``\\n`` / ``\\x1a`` …）→ **422**。这类字符会让
      ``Path.resolve()`` 抛 ``ValueError``，此前以 500 逃出路由。
    - 相对路径（``..`` / ``%2e%2e`` / ``a/b``）→ **422**。此前它们按**服务端进程
      cwd**解析，等于让调用者把 ``.xeyo/settings.json`` 写到任意目录。
    - 绝对路径仍要求是现存目录（复用 ``resolve_physical_cwd``），否则 422，
      避免「工作区不存在」被渲染成「什么都没装」。

    返回 ``realpath``，下游再 ``resolve()`` 即幂等。
    """
    value = str(raw if raw is not None else "").strip()
    if not value:
        return ""
    if _CONTROL_RE.search(value):
        raise api_error(422, f"{field} contains control characters", "invalid_request")
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        raise api_error(422, f"{field} must be an absolute path", "invalid_request")
    from session.workspace_path import resolve_physical_cwd

    try:
        return resolve_physical_cwd(expanded)
    except (OSError, ValueError) as exc:
        raise api_error(
            422,
            f"{field} is not a readable directory: {type(exc).__name__}",
            "invalid_request",
        ) from exc


def require_entry_name(raw: Any, *, field: str) -> str:
    """启停键 / 插件名的边缘校验：复用 ``sessions._require_stable_id``（与
    ``require_session_id`` 同一谓词，只换字段名）。

    键会进 settings.json、活页块句柄（``skill:<name>``）以及磁盘文件名，
    ``victim.`` / ``vi:ctim`` / 空白 / 300 字符都会与别的键撞在同一份状态上——
    一律 422，不静默清洗。

    注意适用边界：这条判据的前提是**名字会被清洗成文件名**。MCP server id 不走
    这条路（它只做 JSON 字典键与活页块句柄 ``mcp:<id>``），对它套 fixed-point
    会把 ``weird name`` / ``a.b`` 这类合法声明一并挡掉；那种输入真正要防的是下面
    那条：文字注入。
    """
    from server.routers.sessions import _require_stable_id

    return _require_stable_id(raw, field=field, filename_bearing=True)


def require_visible_ident(raw: Any, *, field: str) -> str:
    """要出现在**模型可见文本**里的标识符：挡掉换行与控制字符、以及反引号。

    ``extension.config.set_mcp_enabled`` 把调用方给的 server id 原样插进
    ``MCP 服务 \`{id}\``` 并作为 T_now 活页块发布 —— 带换行的 id 就能在模型注意力里
    凭空造出一行（甚至一个 ``#`` 头），那是引擎铁律「注意力里只出现信息，不出现
    导演」的反面，且入口是 HTTP 参数。这里只挡结构性字符：合法 id 里少见
    的空格/点号照常放行，不做清洗。
    """
    value = str(raw if raw is not None else "").strip()
    if not value:
        raise api_error(422, f"{field} is required", "invalid_request")
    if _CONTROL_RE.search(value):
        raise api_error(422, f"{field} contains control characters", "invalid_request")
    if "`" in value:
        raise api_error(422, f"{field} must not contain a backtick", "invalid_request")
    return value


class _EntryToggle(BaseModel):
    enabled: bool


class ExtensionsSettingsBody(BaseModel):
    """POST 体：只收启停语义（新增 server/skill 声明走 mcp.json / plugins）。"""

    workspace: str | None = Field(default=None, max_length=1024)
    enabled_extensions: bool | None = None
    mcp_servers: dict[str, _EntryToggle] | None = None
    skills: dict[str, _EntryToggle] | None = None
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

    ws = require_workspace_arg(workspace) or (CWD or "")
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
        set_plugin_enabled,
        set_skill_enabled,
    )
    from server.deps import CWD

    # 两个来源都校验（query 优先），谁都不允许带着非法值被静默忽略。
    for candidate in (workspace, body.workspace):
        require_workspace_arg(candidate)
    ws = require_workspace_arg(workspace or body.workspace) or (CWD or "")
    # 先校验所有键再落笔：半途 422 不会留下「一半已生效」的状态。
    for field, items in (
        ("mcp_server", body.mcp_servers),
        ("skill", body.skills),
        ("plugin", body.plugins),
    ):
        for key in (items or {}):
            require_entry_name(key, field=f"{field} name")
    applied: dict[str, Any] = {
        "mcp_servers": [],
        "plugins": [],
        "skills": [],
        "master": None,
    }
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
    try:
        out = _merged_view(ws or None)
    except Exception as exc:  # noqa: BLE001
        # 启停已落盘，但回读视图失败：以 ok=False + applied 如实报告，绝不让
        # ValueError/OSError 逃出路由（此前是 500，调用方无从知道哪些已生效）。
        return {
            "ok": False,
            "message": f"settings written but view failed: {exc}",
            "applied": applied,
            "errors": errors,
        }
    out["applied"] = applied
    if errors:
        out["errors"] = errors
    return out
