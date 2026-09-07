"""mcp_name_manifest_shadow — 【侧挂模块·默认关】MCP 工具「name-manifest 暴露档」。

依据：MCP 工具 name-manifest 暴露档设计（侧挂 ⑫：工具只显示 name、description 按需）。
权威约束：extension/mcp_gateway.py + mcp_client.py 的冻结面契约（tools 数组会话内绝对冻结、`_schemas_cache`
会话内永不失效、零前缀重缓存红线）。

## 为什么（收益目标：省 token）
- 动机：大量带长 `inputSchema` 的工具永远用不到却被全量塞进 prompt。
- 本模块提供一个「name-manifest」**快照构建器**：把一个工具的 schema 收缩为 `name + 一句短描述`
  （丢弃 `inputSchema`/`parameters`），并保留到完整 schema 的按需取回通道（`Mcp describe`）。

## 侧挂契约（不改主逻辑 / 不走 live 冻结面）
- `enabled()`：读 `XEYO_MCP_NAME_MANIFEST`（默认 0=关）。
- `build_snapshot(schemas, *, describe_name="Mcp") -> list[dict]`：纯函数，把一组 schema 收缩成
  name-manifest 快照（`name` + 短 `description`），原 `inputSchema` 不进快照；每个工具保留
  `_mcp_full_schema_via: "Mcp(action=describe)"` 指针，供按需取回。
- **red line 遵守**：本模块**不** monkey-patch `ToolRegistry.schemas()`、**不**触碰
  `_schemas_cache`、**不**改变会话内冻结面。它只在「会话建立时」由调用方**显式选用**去构建
  发给模型的 tools 数组（一次性、冻结前）。一旦选用，须保证该会话内不再重建（冻结红线）。
- **升格前提（收益门）**：必须先用一次**真实 MCP server + 真实会话**跑 A/B，测出 token 下降
  并确保 `tests/extension/test_freeze_invariants.py`（schemas 逐字节不变）等契约全绿、P0a 零回归，
  才允许接进 live 冻结快照。未能测量前，本模块保持默认关、仅作 safe building block。
- **fail-open**：`build_snapshot` 任何 schema 异常 → 该工具回退为「保留原 schema」（宁可见勿丢）；
  整体异常 → 返回原 schemas（逐位不变）。
"""

from __future__ import annotations

import os

_ENV = "XEYO_MCP_NAME_MANIFEST"
#: 完整 schema 的按需取回通道（网关 `Mcp{action:describe}`）。
_DESCRIBE_NAME = "Mcp"
_DESCRIBE_ACTION = "describe"


def enabled() -> bool:
    """是否可构建 name-manifest 快照（默认关）。"""
    raw = os.environ.get(_ENV, "").strip().lower()
    if not raw:
        return False
    return raw not in ("0", "false", "off", "no", "")


def build_snapshot(
    schemas: list[dict],
    *,
    describe_name: str = _DESCRIBE_NAME,
    include_full_ref: bool = True,
) -> list[dict]:
    """把一组工具 schema 收缩为 name-manifest 快照。

    - 每个工具：`name` + `description`（短句）；**不含** `inputSchema`/`parameters`/`$schema`。
    - 附加 `_xeyo_full_schema` 元数据：`{"via": "<describe_name>", "action": "describe", "tool": "<name>"}`，
      提示模型用 `Mcp(action=describe)` 按需取回完整参数 schema。
    - 任一工具的 schema 异常 → 保留其原名/原 description，跳过收缩（fail-open，宁可见勿丢）；
      整体异常 → 返回原 schemas 逐位不变。
    """
    if not enabled():
        return schemas
    try:
        out: list[dict] = []
        for sch in schemas or []:
            if not isinstance(sch, dict):
                raise ValueError(f"schema not dict: {type(sch)}")
            name = str(sch.get("name") or "")
            if not name:
                raise ValueError("schema missing name")
            item = {
                "name": name,
                "description": _short_desc(sch),
            }
            if include_full_ref and describe_name:
                item["_xeyo_full_schema"] = {
                    "via": describe_name,
                    "action": _DESCRIBE_ACTION,
                    "tool": name,
                }
            out.append(item)
        return out
    except Exception:  # noqa: BLE001 — fail-open：收缩失败 → 保留原 schemas
        return schemas


def full_schema_ref(schema_name: str, *, describe_name: str = _DESCRIBE_NAME) -> dict:
    """给单个工具生成完整 schema 的取回指引（供 `Mcp{action:describe}` 用）。"""
    return {
        "via": describe_name,
        "action": _DESCRIBE_ACTION,
        "tool": schema_name,
    }


def _short_desc(schema: dict) -> str:
    """取 schema 的短描述：优先 `description`，退 `summary`/`title`，否则空串。"""
    for k in ("description", "summary", "title"):
        v = schema.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""
