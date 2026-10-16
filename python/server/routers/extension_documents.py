"""Local, scoped configuration editor. No installation, approval, or process spawn."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from extension.config_documents import ConfigConflict, SETTINGS_KEYS, read_document, save_document, validate_document
from server.deps import api_error
from server.local_gate import require_loopback
from server.routers.extensions import require_workspace_arg

router = APIRouter(tags=["extensions"], dependencies=[Depends(require_loopback)])
Scope = Literal["workspace", "home"]
Kind = Literal["mcp", "settings"]


def _target(scope: Scope, kind: Kind, workspace: str | None) -> Path:
    from memory.instruction import xeyo_home
    ws = require_workspace_arg(workspace)
    if scope == "workspace" and not ws:
        raise api_error(422, "workspace is required for workspace scope", "invalid_request")
    root = Path(ws) / ".xeyo" if scope == "workspace" else xeyo_home()
    return root / ("mcp.json" if kind == "mcp" else "settings.json")


@router.get("/v1/extensions/configuration")
def get_configuration(scope: Scope, kind: Kind, workspace: str | None = Query(None, max_length=1024)) -> dict[str, Any]:
    path = _target(scope, kind, workspace)
    try:
        data, revision = read_document(path)
        view = {"servers": data.get("servers", {})} if kind == "mcp" else {k: v for k, v in data.items() if k in SETTINGS_KEYS}
        return {"ok": True, "scope": scope, "kind": kind, "path": str(path), "revision": revision, "data": view}
    except (ValueError, OSError):
        raise api_error(422, "configuration could not be read; existing file was not changed", "invalid_configuration")


class ConfigurationBody(BaseModel):
    scope: Scope
    kind: Kind
    workspace: str | None = Field(None, max_length=1024)
    data: dict[str, Any]
    revision: str = Field(min_length=64, max_length=64)
    validate_only: bool = True


@router.post("/v1/extensions/configuration")
def post_configuration(body: ConfigurationBody) -> dict[str, Any]:
    path = _target(body.scope, body.kind, body.workspace)
    if len(json.dumps(body.data).encode()) > 256 * 1024:
        raise api_error(422, "configuration exceeds 256 KiB", "invalid_configuration")
    try:
        validate_document(body.kind, body.data)
        _, revision = read_document(path)
        if revision != body.revision:
            raise ConfigConflict("configuration changed; reload before saving")
        if not body.validate_only:
            revision = save_document(path, body.kind, body.data, body.revision)
        return {"ok": True, "validated": True, "saved": not body.validate_only, "revision": revision, "path": str(path)}
    except ConfigConflict as exc:
        raise api_error(409, str(exc), "configuration_conflict") from exc
    except (ValueError, OSError) as exc:
        raise api_error(422, str(exc), "invalid_configuration") from exc
