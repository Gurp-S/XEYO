"""F2 网关工具 ``Mcp``（P0b）：元动作放行 + call 按目标三态 + 身份 fail-closed。

运行：``py -3.11 -m pytest tests/extension/test_mcp_gateway.py -q``
"""

from __future__ import annotations

import asyncio
import json
import queue

import pytest

from engine.abort import AbortController
from extension import mcp_manager as mm
from extension.mcp_client import mcp_tool_name
from extension.mcp_gateway import GATEWAY_TOOL_NAME
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.tool_registry import ToolRegistry


class FakeMcpTransport:
    def __init__(self, spec, *, logger=None, tools=None, call_text="ok",
                 resources=None, resource_text="resource body"):
        self.spec = spec
        self.tools = list(tools or [])
        self.call_text = call_text
        self.resources = list(resources or [])
        self.resource_text = resource_text
        self.sent = []
        self._responses = queue.Queue()
        self._alive = False

    def spawn(self):
        self._alive = True

    def send(self, message):
        self.sent.append(message)
        if "id" in message:
            self._responses.put(self._respond(message))

    def _respond(self, req):
        method, rid, params = req["method"], req["id"], req.get("params") or {}
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "fake"}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": list(self.tools)}}
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": self.call_text}], "isError": False}}
        if method == "resources/list":
            res = [{"uri": u, "name": u.rsplit("/", 1)[-1], "mimeType": "text/plain"}
                   for u in self.resources]
            out: dict = {"resources": res}
            if res:
                out["nextCursor"] = "c2"
            return {"jsonrpc": "2.0", "id": rid, "result": out}
        if method == "resources/read":
            uri = str(params.get("uri") or "")
            return {"jsonrpc": "2.0", "id": rid, "result": {"contents": [
                {"uri": uri, "mimeType": "text/plain", "text": self.resource_text}
            ]}}
        return {"jsonrpc": "2.0", "id": rid, "result": {}}

    def recv(self, timeout=None):
        try:
            return self._responses.get(timeout=timeout if timeout is not None else 0.25)
        except queue.Empty:
            return None

    def alive(self):
        return self._alive

    def wait(self, timeout=None):
        return None

    def close(self):
        self._alive = False


def _raw(name="read_file", pad=0):
    schema = {"name": name, "inputSchema": {"type": "object", "properties": {}}}
    if pad:
        schema["description"] = "x" * pad
    return schema


def _setup(tmp_path, *, tools, spec_extra=None, call_text="ok", resources=None,
           resource_text="resource body"):
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}),
        encoding="utf-8",
    )
    from memory.instruction import xeyo_home

    p = xeyo_home() / "mcp.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"servers": {"fs": {"command": "node", "args": [], **(spec_extra or {})}}}),
        encoding="utf-8",
    )
    mgr = mm.McpManager(
        str(ws),
        transport_factory=lambda spec, logger=None: FakeMcpTransport(
            spec, tools=tools, call_text=call_text, resources=resources,
            resource_text=resource_text,
        ),
    )
    reg = ToolRegistry(cwd=str(ws))
    mgr.attach_mcp_tools(reg)
    return ws, mgr, reg


def _run(reg, name, payload):
    return asyncio.run(
        reg.run(ToolUse(id="t1", name=name, input=payload), AbortController())
    )


def test_gateway_registered_and_in_schemas(tmp_path):
    _, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")])
    assert reg.get(GATEWAY_TOOL_NAME) is not None
    names = [t["name"] for t in reg.schemas()]
    assert GATEWAY_TOOL_NAME in names


def test_gateway_list_and_describe_allow(tmp_path):
    """元动作 list/describe：ALLOW（无 coordinator 也直接执行）。"""
    _, _, reg = _setup(tmp_path, tools=[_raw("read_file", pad=20)])
    res = _run(reg, GATEWAY_TOOL_NAME, {"action": "list"})
    assert res.is_error is False
    assert "fs" in res.content and "read_file" in res.content

    res = _run(
        reg, GATEWAY_TOOL_NAME,
        {"action": "describe", "server": "fs", "tool": "read_file"},
    )
    assert res.is_error is False
    payload = json.loads(res.content)
    assert payload["tool"] == "read_file"
    assert payload["inputSchema"]["type"] == "object"


def test_gateway_list_marks_hidden(tmp_path):
    _, _, reg = _setup(
        tmp_path, tools=[_raw("read_file"), _raw("write_file")],
        spec_extra={"enabled_tools": ["read_file"]},
    )
    res = _run(reg, GATEWAY_TOOL_NAME, {"action": "list"})
    assert res.is_error is False
    assert "write_file [hidden]" in res.content
    assert "read_file" in res.content and "[hidden]" not in (
        res.content.split("read_file")[1].split("\n")[0]
    )


def test_gateway_call_ask_then_deny_without_coordinator(tmp_path):
    """call（outbound_ask 目标）：策略 ASK → 无 coordinator fail-safe DENY。"""
    _, _, reg = _setup(tmp_path, tools=[_raw("read_file")])
    res = _run(
        reg, GATEWAY_TOOL_NAME,
        {"action": "call", "server": "fs", "tool": "read_file", "args": {"p": 1}},
    )
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "needs_confirmation"


def test_gateway_call_grant_roundtrip_via_target_identity(tmp_path):
    """grant 以目标注册名落库（v2）→ 网关回环命中 → ALLOW → 真执行。"""
    from permissions.store import default_grant_store, grant_fingerprint

    ws, _, reg = _setup(tmp_path, tools=[_raw("read_file")], call_text="gateway-ok")
    target_name = mcp_tool_name("fs", "read_file")
    fp = grant_fingerprint("Mcp", {}, mcp_target=target_name)
    # control.py 落库语义：tool_name = mcp_target or tool_name。
    default_grant_store().add(tool_name=target_name, fingerprint=fp, scope=str(ws))
    res = _run(
        reg, GATEWAY_TOOL_NAME,
        {"action": "call", "server": "fs", "tool": "read_file", "args": {"p": 1}},
    )
    assert res.is_error is False
    assert res.content == "gateway-ok"


def test_gateway_native_grant_same_identity(tmp_path):
    """同一工具：原生路径落的 grant 对网关 call 同样生效（身份统一）。"""
    from permissions.store import default_grant_store, grant_fingerprint

    ws, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")], call_text="native-ok")
    target_name = mcp_tool_name("fs", "read_file")
    target = mgr.resolve_tool("fs", "read_file")
    assert target is not None
    fp = grant_fingerprint(target_name, {})
    default_grant_store().add(tool_name=target_name, fingerprint=fp, scope=str(ws))
    res = _run(
        reg, GATEWAY_TOOL_NAME,
        {"action": "call", "server": "fs", "tool": "read_file", "args": {}},
    )
    assert res.is_error is False and res.content == "native-ok"


def test_gateway_resources_list_and_read(tmp_path):
    """F6b：resources 分页列 + read_resource 按 uri 读（只读放行）。"""
    ws, mgr, reg = _setup(
        tmp_path, tools=[_raw("read_file")],
        resources=["file:///ws/notes.md"], resource_text="hello resource",
    )
    d = evaluate_policy(
        "Mcp", {"action": "read_resource", "server": "fs", "uri": "file:///ws/notes.md"},
        cwd=str(ws), tool=reg.get("Mcp"),
    )
    assert d.decision == PermissionDecision.ALLOW
    assert d.matched_rule == "mcp_gateway_read"

    res = _run(reg, "Mcp", {"action": "resources", "server": "fs"})
    assert res.is_error is False
    assert "file:///ws/notes.md" in res.content and "nextCursor: c2" in res.content

    res = _run(
        reg, "Mcp",
        {"action": "read_resource", "server": "fs", "uri": "file:///ws/notes.md"},
    )
    assert res.is_error is False
    assert "hello resource" in res.content

    # 未就绪 server → 明确报错（不炸）。
    res = _run(
        reg, "Mcp",
        {"action": "read_resource", "server": "nope", "uri": "file:///x"},
    )
    assert res.is_error is True and "not ready" in res.content


def test_gateway_schema_has_all_p0b_actions(tmp_path):
    _, _, reg = _setup(tmp_path, tools=[_raw("read_file")])
    schema = reg.get("Mcp").schema()
    actions = schema["inputSchema"]["properties"]["action"]["enum"]
    assert actions == ["list", "describe", "call", "resources", "read_resource"]


def test_gateway_unknown_tool_fail_closed(tmp_path):
    """未知/伪装身份：DENY（不 ASK、不执行）。"""
    _, _, reg = _setup(tmp_path, tools=[_raw("read_file")])
    res = _run(
        reg, GATEWAY_TOOL_NAME,
        {"action": "call", "server": "evil", "tool": "bomb", "args": {}},
    )
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "mcp_gateway_unknown_tool"
    # 大小写兜底能解析到 → 走正常三态（不误伤）。
    d = evaluate_policy(
        GATEWAY_TOOL_NAME,
        {"action": "call", "server": "fs", "tool": "READ_FILE"},
        cwd=str(tmp_path / "ws"),
        tool=reg.get(GATEWAY_TOOL_NAME),
    )
    assert d.decision == PermissionDecision.ASK


def test_gateway_enterprise_deny_by_target(tmp_path, monkeypatch):
    pol = tmp_path / "policy.json"
    monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol))
    pol.write_text('{"mcp_tool_deny": ["fs/read_file"]}', encoding="utf-8")
    _, _, reg = _setup(tmp_path, tools=[_raw("read_file")])
    res = _run(
        reg, GATEWAY_TOOL_NAME,
        {"action": "call", "server": "fs", "tool": "read_file", "args": {}},
    )
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "mcp_enterprise_deny"


def test_gateway_bad_action_denied(tmp_path):
    _, _, reg = _setup(tmp_path, tools=[_raw("read_file")])
    d = evaluate_policy(
        GATEWAY_TOOL_NAME, {"action": "shutdown"},
        cwd=str(tmp_path / "ws"), tool=reg.get(GATEWAY_TOOL_NAME),
    )
    assert d.decision == PermissionDecision.DENY
    assert d.matched_rule == "mcp_gateway_bad_action"


def test_gateway_casefold_resolve_and_disabled_server(tmp_path):
    ws, mgr, _ = _setup(tmp_path, tools=[_raw("read_file")])
    assert mgr.resolve_tool("fs", "READ_FILE") is not None
    assert mgr.resolve_tool("fs", "nope") is None
    assert mgr.resolve_tool("nope", "read_file") is None
    assert mgr.resolve_tool("", "read_file") is None
    # 未启动 server：伪造 entry state（直接构造 manager 查询）。
    mgr2 = mm.McpManager(str(ws))
    assert mgr2.resolve_tool("fs", "read_file") is None
