"""MCP 面板控制路径（smoke-test #8 / 设计 40 §5 P1 最小落地）。

``GET /v1/mcp``
    面板视图：总开关 + 三来源 server 状态（declared/unapproved/denied/
    ready/failed）+ 运行中工具清单（含 hidden 标注与勾选态）。
``POST /v1/mcp/op``
    approve（写 trust） / enable / disable / reload（重置管理器,下次 attach 生效）。

与 extensions/skills 同源安全模型：``require_loopback``（非本机直接拒绝）。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from server.local_gate import require_loopback

router = APIRouter(tags=["mcp"])


class McpOpBody(BaseModel):
    """控制动作体。"""

    server: str = Field(min_length=1, max_length=128)
    op: str = Field(min_length=1, max_length=16)
    workspace: str | None = Field(default=None, max_length=1024)
    # op == "tool" 时使用：单工具勾选（写回声明 mcp.json 的 enabled_tools）。
    raw_tool: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None


def _ws_of(request: Request, workspace: str | None) -> str | None:
    from server.deps import CWD

    return (workspace or "").strip() or (CWD or "") or None


def _write_trust_entry(ws: str | None, spec: dict[str, Any]) -> None:
    """project 级批准：按声明 hash 写 ``<ws>/.xeyo/mcp-trust.json``（原子）。"""
    from extension.mcp_scopes import declaration_hash, trust_path

    path = trust_path(ws)
    trust: dict[str, Any] = {}
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                trust = raw
    except (OSError, json.JSONDecodeError):
        trust = {}
    trust[declaration_hash(spec)] = {"approved": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(
        json.dumps(trust, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


@router.get("/v1/mcp")
def get_mcp_status(
    request: Request,
    workspace: str | None = Query(default=None, max_length=1024),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """面板视图：总开关、server 状态、运行中工具（含勾选态）。"""
    _ = authorization
    require_loopback(request)
    ws = _ws_of(request, workspace)
    try:
        from extension.config import load_ext_config
        from extension.mcp_manager import get_mcp_manager
        from extension.mcp_scopes import is_server_trusted, mcp_server_denied

        cfg = load_ext_config(ws)
        mgr = get_mcp_manager(ws)
        specs = mgr.collect_specs(config=cfg)
        catalog = {c["server"]: c for c in mgr.gateway_catalog()}
        servers: list[dict[str, Any]] = []
        for sid in sorted(specs):
            spec = specs[sid]
            denied = mcp_server_denied(sid)
            trusted = not spec.get("_requires_trust") or is_server_trusted(ws, spec)
            entry = catalog.get(sid)
            if denied:
                status = "denied"
            elif not trusted:
                status = "unapproved"
            elif entry is not None:
                status = str(entry.get("state") or "failed")
            else:
                status = "declared"
            tools = [
                {
                    "name": str(t.get("tool") or ""),
                    "description": str(t.get("description") or ""),
                    "hidden": bool(t.get("hidden")),
                }
                for t in (entry or {}).get("tools", [])
            ]
            servers.append(
                {
                    "id": str(sid),
                    "scope": str(spec.get("_scope") or ""),
                    "enabled": cfg.mcp_enabled(str(sid)),
                    "auto_start": cfg.mcp_auto_start(str(sid)),
                    "required": bool(spec.get("required", False)),
                    "denied": denied,
                    "trusted": trusted,
                    "status": status,
                    "error": None,
                    "enabled_tools": spec.get("enabled_tools"),
                    "raw_tools": list(t["name"] for t in tools),
                    "tools": tools,
                }
            )
        return {
            "ok": True,
            "enabled_extensions": bool(cfg.enabled_extensions),
            "workspace": ws or "",
            "servers": servers,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc), "servers": []}


@router.post("/v1/mcp/op")
def post_mcp_op(
    body: McpOpBody,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """approve / enable / disable / reload。

    - approve：project 级信任落盘（``/mcp approve`` 语义）,管理器重置,
      下次 attach 生效（当前会话仍按批准前目录）；
    - enable/disable：``set_mcp_enabled``（push reconcile,DENY 门即时生效）;
    - reload：重置管理器（下个会话/attach 按最新声明重建）。
    """
    _ = authorization
    require_loopback(request)
    ws = _ws_of(request, body.workspace)
    sid = (body.server or "").strip()
    op = (body.op or "").strip().lower()
    if not sid:
        return {"ok": False, "message": "server is required"}
    if op not in ("approve", "enable", "disable", "reload", "tool"):
        return {"ok": False, "message": "op must be one of: approve / enable / disable / reload / tool"}
    try:
        if op == "tool":
            raw = (body.raw_tool or "").strip()
            if not raw or body.enabled is None:
                return {"ok": False, "message": "tool op requires raw_tool and enabled"}
            from extension.mcp_manager import set_mcp_tool_enabled

            msg = set_mcp_tool_enabled(ws, sid, raw, bool(body.enabled))
            return {
                "ok": True,
                "server": sid,
                "op": op,
                "raw_tool": raw,
                "enabled": bool(body.enabled),
                "message": msg,
            }
        if op in ("enable", "disable"):
            from extension.config import set_mcp_enabled

            set_mcp_enabled(ws, sid, op == "enable")
            return {"ok": True, "server": sid, "op": op, "enabled": op == "enable"}
        if op in ("approve", "reload"):
            from extension.mcp_manager import get_mcp_manager, reset_managers

            mgr = get_mcp_manager(ws)
            specs = mgr.collect_specs()
            spec = specs.get(sid)
            if op == "approve":
                if spec is None:
                    return {"ok": False, "message": f"server {sid!r} 未声明，无法批准"}
                _write_trust_entry(ws, spec)
            reset_managers()
            return {
                "ok": True,
                "server": sid,
                "op": op,
                "message": (
                    "已批准（当前会话按原目录运行；新会话/重新 attach 生效）"
                    if op == "approve"
                    else "已重置 MCP 管理器（新会话/重新 attach 按最新声明重建）"
                ),
            }
        return {"ok": False, "message": "unreachable"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}
