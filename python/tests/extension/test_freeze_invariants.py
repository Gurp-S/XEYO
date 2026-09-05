"""P0b 验收件：冻结不变量 + 活页块幂等（§9.2 出口标准）。

- 冻结不变量：会话内启停（push/pull、重复 attach）**永不触碰**
  ``ToolRegistry.schemas()`` 的逐字节输出；
- 活页块幂等：同值 set 不发布；A→B→A 每次变化各发一块；
- 指纹 v2 组独立成文件（tests/test_mcp_fingerprint_v2.py），此处只做冒烟引用。

运行：``py -3.11 -m pytest tests/extension/test_freeze_invariants.py -q``
"""

from __future__ import annotations

import asyncio
import json
import queue

import pytest

from engine.abort import AbortController
from extension import mcp_manager as mm
from extension.config import set_mcp_enabled
from extension.mcp_client import mcp_tool_name
from extension.reconcile import (
    consume_reconcile_blocks,
    reset_reconcile_state,
)
from msgtypes.message import ToolUse
from tools.tool_registry import ToolRegistry


@pytest.fixture(autouse=True)
def _clean_reconcile():
    reset_reconcile_state()
    yield
    reset_reconcile_state()


class FakeMcpTransport:
    def __init__(self, spec, *, logger=None, tools=None, call_text="ok"):
        self.spec = spec
        self.tools = list(tools or [])
        self.call_text = call_text
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
        method, rid = req["method"], req["id"]
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "fake"}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": list(self.tools)}}
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": self.call_text}], "isError": False}}
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


def _raw(name):
    return {"name": name, "inputSchema": {"type": "object", "properties": {}}}


def _schemas_bytes(reg: ToolRegistry) -> str:
    """schemas() 逐字节快照（排序键稳定化，等价会话内视图）。"""
    return json.dumps(reg.schemas(), sort_keys=True, ensure_ascii=False)


def _setup(tmp_path, *, tools, spec_extra=None):
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
        transport_factory=lambda spec, logger=None: FakeMcpTransport(spec, tools=tools),
    )
    reg = ToolRegistry(cwd=str(ws))
    mgr.attach_mcp_tools(reg)
    return ws, mgr, reg


def test_schemas_byte_frozen_across_config_changes(tmp_path):
    """会话内启停（含重复 attach）→ schemas() 逐字节不变（F2.5 冻结红线）。"""
    ws, mgr, reg = _setup(
        tmp_path,
        tools=[_raw("read_file"), _raw("write_file")],
        spec_extra={"enabled_tools": ["read_file"]},
    )
    before = _schemas_bytes(reg)
    assert "mcp__fs__read_file__" in before
    assert "mcp__fs__write_file__" not in before  # 未勾选 → hidden 不进 schemas
    assert '"Mcp"' in before or '"name": "Mcp"' in before or "Mcp" in before

    # ① 会话内停用 server（push 写盘 + 探针即时生效）→ schemas 不变。
    set_mcp_enabled(str(ws), "fs", False)
    consume_reconcile_blocks()
    assert _schemas_bytes(reg) == before

    # ② 停用态下重复 attach（同一 registry）→ 不注册不注销 → 逐字节不变。
    mgr.attach_mcp_tools(reg)
    assert _schemas_bytes(reg) == before

    # ③ 重新启用 + 重复 attach（重注册同名同 exposure）→ 逐字节不变。
    set_mcp_enabled(str(ws), "fs", True)
    consume_reconcile_blocks()
    mgr.attach_mcp_tools(reg)
    assert _schemas_bytes(reg) == before

    # ④ 无配置变化的幂等 attach → 不变。
    mgr.attach_mcp_tools(reg)
    assert _schemas_bytes(reg) == before


def test_disabled_server_execution_path_survives_freeze(tmp_path):
    """冻结的同时执行侧即时生效：schemas 含 native 名，但探针 DENY。"""
    ws, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")])
    before = _schemas_bytes(reg)
    set_mcp_enabled(str(ws), "fs", False)
    consume_reconcile_blocks()
    # schemas 逐字节不变（含 native 工具名——模型视图冻结）。
    assert _schemas_bytes(reg) == before
    # 幻觉调用 → DENY（探针）而非 unknown tool。
    res = asyncio.run(
        reg.run(
            ToolUse(id="t1", name=mcp_tool_name("fs", "read_file"), input={}),
            AbortController(),
        )
    )
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "mcp_disabled"


def test_reconcile_blocks_idempotent_toggle_cycle(tmp_path):
    """A→B→A：每次真实变化恰一块；同值 set 零块；消费即清。"""
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True}), encoding="utf-8"
    )
    set_mcp_enabled(str(ws), "fs", True)
    assert len(consume_reconcile_blocks()) == 1
    set_mcp_enabled(str(ws), "fs", True)  # 同值 → 不发
    assert consume_reconcile_blocks() == []
    set_mcp_enabled(str(ws), "fs", False)
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1 and "停用" in blocks[0]
    set_mcp_enabled(str(ws), "fs", True)
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1 and "启用" in blocks[0]
    assert consume_reconcile_blocks() == []


def test_fingerprint_v2_smoke_in_full_chain(tmp_path):
    """链路冒烟：网关 call ASK 的挂起项/授权身份 = 目标注册名（v2 语义）。"""
    from permissions.policy import evaluate_policy
    from permissions.filesystem import PermissionDecision
    from permissions.store import grant_fingerprint

    ws, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")])
    gateway = reg.get("Mcp")
    d = evaluate_policy(
        "Mcp",
        {"action": "call", "server": "fs", "tool": "read_file", "args": {}},
        cwd=str(ws),
        tool=gateway,
    )
    target = mcp_tool_name("fs", "read_file")
    assert d.decision == PermissionDecision.ASK
    assert d.mcp_target == target
    # 指纹与身份对称：网关与原生路径同 hash。
    fp_via_gateway = grant_fingerprint("Mcp", {}, mcp_target=target)
    fp_native = grant_fingerprint(target, {})
    assert fp_via_gateway == fp_native and fp_via_gateway.startswith("v2:")
