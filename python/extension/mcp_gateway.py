"""MCP 网关工具 ``Mcp``（P0b F2/F2.5）：会话内新增工具的唯一通道。

设计（对齐 MCP×SKILL 企业级融合冻结稿 #40 §F2/§F2.5/§F6b）：

- 扩展开启即常驻注册（静态 schema ~150 token，tools 数组冻结红线内）；
- ``action=list``：全量 server 侧集合（含 hidden 标注）——hidden-but-registered
  工具的「按需描述」入口；
- ``action=describe``：按 (server, tool) 返回入参 schema（模型 call 前确认）；
- ``action=call``：身份经**已知工具集解析**（resolve_tool），绝不从 args 之外的
  通道取身份 → 指纹 v2 / 企业 deny / tool_policies 全部按目标工具三态判定
  （permissions/policy._evaluate_mcp_gateway）；执行直呼目标 McpTool.execute，
  审计 ``mcp.tool.call`` 硬字段由写入端保证。

红线：本工具不绕权限 —— registry.run 的 ASK/DENY 在 execute 之前已按目标
策略裁决；子代理注册表只来自静态工厂，本工具天然不可达。
"""

from __future__ import annotations

import json
import time
from typing import Any

from engine.abort import AbortController
from tools.base_tool import Tool, ToolResult

#: list/describe 输出上限（字符）—— 网关响应也要守 token 预算。
_GATEWAY_OUTPUT_BUDGET = 4000

GATEWAY_TOOL_NAME = "Mcp"

_SCHEMA: dict[str, Any] = {
    "name": GATEWAY_TOOL_NAME,
    "description": (
        "MCP gateway. action=list: enumerate servers & tools (hidden tools flagged). "
        "action=describe: show one tool's input schema (server+tool required). "
        "action=call: execute a server tool (server+tool+args; args per describe). "
        "action=resources: list server resources (optional server, cursor). "
        "action=read_resource: read one resource by uri (server+uri required). "
        "Describe before call. Unlisted/unchecked tools may still be callable - use list."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "describe", "call", "resources", "read_resource"],
                "description": (
                    "list=enumerate; describe=schema; call=execute; "
                    "resources=list; read_resource=fetch content"
                ),
            },
            "server": {
                "type": "string",
                "description": "server id (describe/call/read_resource; resources optional)",
            },
            "tool": {"type": "string", "description": "raw tool name (describe/call)"},
            "args": {
                "type": "object",
                "description": "arguments per the describe schema (call)",
            },
            "uri": {"type": "string", "description": "resource uri (read_resource)"},
            "cursor": {"type": "string", "description": "pagination cursor (resources)"},
        },
        "required": ["action"],
    },
}


def _clip(text: str, budget: int = _GATEWAY_OUTPUT_BUDGET) -> str:
    if len(text) <= budget:
        return text
    return text[:budget] + f"\n…[clipped at {budget} chars; narrow the query]"


class McpGatewayTool(Tool):
    """静态注册的 MCP 网关：元动作只读放行，call 走目标工具权限三态。"""

    def __init__(self, manager: Any) -> None:
        super().__init__()
        self._manager = manager
        self.name = GATEWAY_TOOL_NAME
        #: registry._apply_output_budget 实例 seam：网关响应自带预算，豁免 spill。
        self.output_budget = 0
        #: policy 侧识别（_evaluate_mcp_gateway 以 name 分支，此标记供调试/测试）。
        self.gateway = True

    def schema(self) -> dict[str, Any]:
        return json.loads(json.dumps(_SCHEMA))  # 深拷贝，防调用方改静态表

    def is_read_only(self) -> bool:
        # call 有副作用；list/describe 的放行由 policy 分支决定，不走只读白名单。
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    # -- 执行 ---------------------------------------------------------------

    async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
        if abort is not None:
            abort.raise_if_aborted()
        started = time.monotonic()
        data = input if isinstance(input, dict) else {}
        action = str(data.get("action") or "").strip().lower()
        try:
            if action == "list":
                out = self._act_list()
            elif action == "describe":
                out = self._act_describe(data)
            elif action == "resources":
                out = self._act_resources(data)
            elif action == "read_resource":
                out = self._act_read_resource(data)
            elif action == "call":
                return await self._act_call(data, abort)
            else:
                return ToolResult(
                    content=f"Mcp gateway: unknown action {action!r} "
                    "(use list / describe / call / resources / read_resource)",
                    is_error=True,
                )
        except Exception as e:  # noqa: BLE001 — 网关不炸工具循环
            return ToolResult(content=f"Mcp gateway error: {e}", is_error=True)
        _ = started  # 审计由 registry tool.started/finished 覆盖元动作
        if isinstance(out, ToolResult):
            return out  # 动作自带错误语义（unknown server 等）
        return ToolResult(content=out, is_error=False)

    # -- 动作实现 ------------------------------------------------------------

    def _act_list(self) -> str:
        try:
            catalog = self._manager.gateway_catalog()
        except Exception as e:  # noqa: BLE001
            return f"Mcp gateway error: {e}"
        if not catalog:
            return "no MCP servers attached (extension layer may be off or none enabled)"
        lines: list[str] = []
        for srv in catalog:
            lines.append(
                f"- {srv['server']} ({srv['state']}{'/required' if srv['required'] else ''})"
            )
            for t in srv["tools"]:
                flag = " [hidden]" if t["hidden"] else ""
                desc = f" — {t['description']}" if t["description"] else ""
                lines.append(f"  - {t['tool']}{flag}{desc}")
        return _clip("\n".join(lines))

    def _act_describe(self, data: dict[str, Any]) -> str:
        target = self._resolve(data)
        if target is None:
            return self._unknown_message(data)
        schema = target.schema()
        payload = {
            "server": target.server_id,
            "tool": target.raw_name,
            "registered_name": target.name,
            "hidden": target.exposure == "hidden",
            "inputSchema": schema.get("input_schema") or schema.get("inputSchema") or {},
        }
        return _clip(json.dumps(payload, ensure_ascii=False, indent=1))

    async def _act_call(self, data: dict[str, Any], abort: AbortController) -> ToolResult:
        target = self._resolve(data)
        if target is None:
            return ToolResult(content=self._unknown_message(data), is_error=True)
        args = data.get("args")
        if not isinstance(args, dict):
            args = {}
        return await target.execute(args, abort)

    # -- F6b：resources 网关化（read_path 级只读） ---------------------------

    def _servers_for_resources(self, data: dict[str, Any]) -> list[tuple[str, Any]]:
        """(server_id, client) 列表：指定 server 或全部就绪 server。"""
        server = str(data.get("server") or "").strip()
        if server:
            client = getattr(self._manager, "client_for", None)
            if not callable(client):
                return []
            got = client(server)
            return [(server, got)] if got is not None else []
        catalog = getattr(self._manager, "gateway_catalog", None)
        if not callable(catalog):
            return []
        out: list[tuple[str, Any]] = []
        for srv in catalog():
            if srv.get("state") != "ready":
                continue
            got = self._client_of(srv["server"])
            if got is not None:
                out.append((srv["server"], got))
        return out

    def _client_of(self, server_id: str) -> Any:
        client_for = getattr(self._manager, "client_for", None)
        return client_for(server_id) if callable(client_for) else None

    def _act_resources(self, data: dict[str, Any]) -> str:
        pairs = self._servers_for_resources(data)
        if not pairs:
            server = str(data.get("server") or "").strip()
            return (
                f"Mcp gateway: server {server!r} not ready or unknown — use action:list."
                if server
                else "no ready MCP servers with resources"
            )
        cursor = str(data.get("cursor") or "").strip() or None
        lines: list[str] = []
        for sid, client in pairs:
            try:
                result = client.list_resources(cursor=cursor)
            except Exception as e:  # noqa: BLE001 — server 不支持/断连 → 标注跳过
                lines.append(f"- {sid}: resources/list failed ({e})")
                continue
            items = result.get("resources") or []
            lines.append(f"- {sid}:")
            for res in items:
                if not isinstance(res, dict):
                    continue
                uri = str(res.get("uri") or "")
                name = str(res.get("name") or "")
                mime = str(res.get("mimeType") or "")
                suffix = f" ({mime})" if mime else ""
                label = f" {name}" if name else ""
                lines.append(f"  - {uri}{label}{suffix}")
            nxt = str(result.get("nextCursor") or "")
            if nxt:
                lines.append(
                    f'  (nextCursor: {nxt} — action:"resources", server:"{sid}", cursor:"{nxt}")'
                )
        return _clip("\n".join(lines) or "(no resources)")

    def _act_read_resource(self, data: dict[str, Any]) -> "str | ToolResult":
        server = str(data.get("server") or "").strip()
        uri = str(data.get("uri") or "").strip()
        if not server or not uri:
            return ToolResult(
                content="Mcp gateway: read_resource requires server and uri.",
                is_error=True,
            )
        client = self._client_of(server)
        if client is None:
            return ToolResult(
                content=(
                    f"Mcp gateway: server {server!r} not ready or unknown — use action:list."
                ),
                is_error=True,
            )
        try:
            result = client.read_resource(uri)
        except Exception as e:  # noqa: BLE001
            return f"Mcp gateway: resources/read failed for {uri}: {e}"
        contents = result.get("contents") or []
        if not isinstance(contents, list) or not contents:
            return f"(no content for {uri})"
        lines: list[str] = []
        for item in contents:
            if not isinstance(item, dict):
                continue
            mime = str(item.get("mimeType") or "")
            head = f"[{item.get('uri') or uri}{' | ' + mime if mime else ''}]"
            if "text" in item:
                lines.append(head)
                lines.append(str(item.get("text") or ""))
            elif "blob" in item:
                blob = str(item.get("blob") or "")
                lines.append(f"{head} [binary: {len(blob)} base64 chars — not shown]")
            else:
                lines.append(f"{head} [unsupported content block]")
        return _clip("\n".join(lines))

    # -- 解析与文案 ----------------------------------------------------------

    def resolve_target(self, server_id: str, raw_name: str) -> Any:
        """policy 侧身份解析入口（只委托 manager 的已知工具集，注入免疫）。"""
        resolve = getattr(self._manager, "resolve_tool", None)
        if not callable(resolve):
            return None
        return resolve(server_id, raw_name)

    def _resolve(self, data: dict[str, Any]) -> Any:
        server = str(data.get("server") or "").strip()
        raw = str(data.get("tool") or "").strip()
        return self.resolve_target(server, raw)

    def _unknown_message(self, data: dict[str, Any]) -> str:
        server = str(data.get("server") or "").strip()
        raw = str(data.get("tool") or "").strip()
        return (
            f"Mcp gateway: unknown tool {server}/{raw} — fail-closed. "
            "Use action=list to enumerate servers/tools; the tool may be "
            "unchecked or its server disabled/unapproved."
        )
