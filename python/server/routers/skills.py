"""Skill 域路由：``GET /v1/skills`` 返回结构化技能清单（供 GUI 的 + 快捷菜单渲染）。

与 ``/v1/slash`` 同源安全模型：``require_loopback`` + Bearer 头（本地桌面给 API key，
非本机客户端直接拒绝）。不改 MessageStore / JSONL，不进 system prompt——技能内容仍走
Skill 工具按需加载（AGENTS.md 扩展层硬规则），本端点只提供**展示与引用**所需的元数据。

数据源：``extension.skill_loader.discover_skills(ws)``（workspace > home > plugin 三源，
同名默认禁止覆盖）。扩展层关闭（``enabled_extensions: false``）时返回空列表 + 标记，
由前端渲染空态而非报错。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Request

from server.local_gate import require_loopback

router = APIRouter(tags=["skills"])


@router.get("/v1/skills")
def list_skills(
    request: Request,
    workspace: str | None = Query(default=None, max_length=1024),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """返回当前工作区的技能清单。

    ``workspace`` 缺省时回退到已登记 UI cwd（与 ``/v1/slash`` 的 ``_workspace`` 语义一致）。
    扩展层关闭 → ``{ok: true, enabled_extensions: false, skills: []}``。
    """
    _ = authorization  # 门禁放行本机；保留 Bearer 语义位，前端无需再单独校验。
    require_loopback(request)

    from extension.config import load_ext_config
    from extension.skill_loader import discover_skills
    from server.deps import CWD

    ws = (workspace or "").strip() or (CWD or "")
    try:
        cfg = load_ext_config(ws or None)
        enabled = bool(cfg.enabled_extensions)
        if not enabled:
            return {"ok": True, "enabled_extensions": False, "skills": []}
        entries = discover_skills(ws or None, config=cfg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "enabled_extensions": False, "skills": [], "message": str(exc)}

    skills = [
        {
            "name": e.name,
            "description": e.description or "",
            "source": e.source,
            "plugin": e.plugin or "",
            "tags": list(e.tags),
            "model_hint": e.model_hint or "",
        }
        # F4（§2 决策 3）：user_invocable:false → 用户菜单不展示
        # （model_invocable:false 仍对用户可见，仅模型侧不列）。
        for e in entries
        if e.user_invocable
    ]
    return {"ok": True, "enabled_extensions": True, "skills": skills}
