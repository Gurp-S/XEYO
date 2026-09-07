"""F2 exposure 列（P0b）：三层可见性 + 名长截断 + 实例输出预算。

- hidden 工具不进 schemas 但保留注册（幻觉调用走权限 ASK，fail-safe）；
- 层①勾选 / 层②_meta.ui.visibility / 层③cap+尺寸；
- 注册名 ≤128B 截断（确定性）；per-tool output_token_limits 优先于 ToolMeta。

运行：``py -3.11 -m pytest tests/extension/test_mcp_exposure.py -q``
"""

from __future__ import annotations

import asyncio
import json
import queue


from engine.abort import AbortController
from extension import mcp_manager as mm
from extension.mcp_client import (
    MAX_TOOL_NAME_BYTES,
    McpClientSpec,
    McpTool,
    mcp_tool_name,
    tool_is_model_visible,
)
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.meta import exposure_of
from tools.tool_registry import ToolRegistry


class FakeMcpTransport:
    """进程内 JSON-RPC stub（同 e2e）；call_text 可定制 tools/call 回包。"""

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


def _raw(name="read_file", *, pad=0, meta=None):
    schema = {"name": name, "inputSchema": {"type": "object", "properties": {}}}
    if pad:
        schema["description"] = "x" * pad
    if meta is not None:
        schema["_meta"] = meta
    return schema


def _write_settings(ws, data):
    p = ws / ".xeyo" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _write_user_mcp(servers):
    from memory.instruction import xeyo_home

    p = xeyo_home() / "mcp.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"servers": servers}), encoding="utf-8")


def _attach(tmp_path, *, tools, spec_extra=None, call_text="ok"):
    from memory.instruction import xeyo_home

    ws = tmp_path / "ws"
    ws.mkdir()
    _write_settings(
        ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}
    )
    _write_user_mcp({"fs": {"command": "node", "args": [], **(spec_extra or {})}})
    home = xeyo_home() / "mcp.json"
    mgr = mm.McpManager(
        str(ws),
        transport_factory=lambda spec, logger=None: FakeMcpTransport(
            spec, tools=tools, call_text=call_text
        ),
    )
    reg = ToolRegistry(cwd=str(ws))
    mgr.attach_mcp_tools(reg)
    return ws, home, mgr, reg


def test_unchecked_tool_hidden_but_registered_and_askable(tmp_path):
    """层①：未勾选 → 不进 schemas 但保留注册；幻觉调用走权限 ASK。"""
    _, _, _, reg = _attach(
        tmp_path,
        tools=[_raw("read_file"), _raw("write_file")],
        spec_extra={"enabled_tools": ["read_file"]},
    )
    names = [t["name"] for t in reg.schemas() if t["name"] != "Mcp"]
    assert len(names) == 1 and names[0].startswith("mcp__fs__read_file__")
    hidden = reg.get(mcp_tool_name("fs", "write_file"))
    assert hidden is not None  # 保留注册（可 dispatch）
    assert exposure_of(hidden) == "hidden"
    # 幻觉调用 fail-safe：策略 ASK（非 unknown tool）。
    d = evaluate_policy(hidden.name, {}, cwd=str(tmp_path / "ws"), tool=hidden)
    assert d.decision == PermissionDecision.ASK


def test_meta_visibility_annotation_hides(tmp_path):
    """层②：_meta.ui.visibility 不含 model → hidden。"""
    _, _, _, reg = _attach(
        tmp_path,
        tools=[
            _raw("read_file"),
            _raw("ui_only", meta={"ui": {"visibility": ["user"]}}),
            _raw("both", meta={"ui": {"visibility": ["model", "user"]}}),
        ],
    )
    names = [t["name"] for t in reg.schemas()]
    assert any(n.startswith("mcp__fs__read_file__") for n in names)
    assert any(n.startswith("mcp__fs__both__") for n in names)
    assert not any(n.startswith("mcp__fs__ui_only__") for n in names)
    assert reg.get(mcp_tool_name("fs", "ui_only")) is not None


def test_tool_is_model_visible_defaults_true():
    assert tool_is_model_visible(_raw()) is True
    assert tool_is_model_visible(_raw(meta={"ui": {}})) is True
    assert tool_is_model_visible(_raw(meta={"ui": {"visibility": "model"}})) is True
    assert tool_is_model_visible(_raw(meta={"ui": {"visibility": ["user"]}})) is False
    assert tool_is_model_visible({"name": "x"}) is True


def test_oversize_single_tool_hidden(tmp_path):
    """层③：单工具 spec >8KB → hidden。"""
    _, _, _, reg = _attach(
        tmp_path, tools=[_raw("read_file"), _raw("huge", pad=9000)]
    )
    names = [t["name"] for t in reg.schemas()]
    assert any(n.startswith("mcp__fs__read_file__") for n in names)
    assert not any(n.startswith("mcp__fs__huge__") for n in names)
    assert reg.get(mcp_tool_name("fs", "huge")) is not None


def test_server_total_budget_hides_tail(tmp_path):
    """层③：server 总量 >64KB → 溢出（后注册）部分 hidden。"""
    tools = [_raw(f"t{i:02d}", pad=7000) for i in range(10)]
    _, _, mgr, reg = _attach(tmp_path, tools=tools)
    names = [t["name"] for t in reg.schemas()]
    visible = [n for n in names if n.startswith("mcp__fs__")]
    assert len(visible) == 9  # 9×7000=63000 ≤64KB；第 10 个越线
    snap = mgr.snapshot()["servers"]["fs"]
    assert len(snap["hidden_tools"]) == 1
    assert snap["hidden_tools"][0] == mcp_tool_name("fs", "t09")
    assert reg.get(snap["hidden_tools"][0]) is not None


def test_cap_32_env_overrides(tmp_path, monkeypatch):
    tools = [_raw(f"t{i:02d}") for i in range(40)]
    _, _, _, reg = _attach(tmp_path, tools=tools)
    visible = [t["name"] for t in reg.schemas() if t["name"].startswith("mcp__fs__")]
    assert len(visible) == 32
    monkeypatch.setenv("XEYO_MCP_TOOL_MAX_VISIBLE", "5")
    _, _, _, reg2 = _attach(
        tmp_path / "ws2", tools=tools
    ) if False else (None, None, None, None)
    # env 生效需独立 workspace（manager mtime 缓存按 settings 文件）。
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    _write_settings(ws2, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}})
    _write_user_mcp({"fs": {"command": "node", "args": []}})
    mgr2 = mm.McpManager(
        str(ws2),
        transport_factory=lambda spec, logger=None: FakeMcpTransport(spec, tools=tools),
    )
    reg3 = ToolRegistry(cwd=str(ws2))
    mgr2.attach_mcp_tools(reg3)
    visible2 = [t["name"] for t in reg3.schemas() if t["name"].startswith("mcp__fs__")]
    assert len(visible2) == 5


def test_hidden_tools_still_ask_not_unknown(tmp_path):
    """hidden 注册语义端到端：registry.run 无 coordinator → ASK→DENY 而非 unknown。"""
    ws, _, _, reg = _attach(
        tmp_path,
        tools=[_raw("read_file"), _raw("write_file")],
        spec_extra={"enabled_tools": ["read_file"]},
    )
    hidden_name = mcp_tool_name("fs", "write_file")
    res = asyncio.run(reg.run(ToolUse(id="t1", name=hidden_name, input={}), AbortController()))
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "needs_confirmation"


def test_per_tool_output_token_limit_instance_budget(tmp_path):
    """F6a per-tool 预算：实例 output_budget 优先于默认 16000。"""
    ws, _, _, reg = _attach(
        tmp_path,
        tools=[_raw("read_file")],
        spec_extra={
            "tools_policy": "always_allow",
            "output_token_limits": {"read_file": 50},
        },
        call_text="ok" * 30,  # 60 字符 > 50 预算 → spill 预览
    )
    name = mcp_tool_name("fs", "read_file")
    tool = reg.get(name)
    assert tool is not None and tool.output_budget == 50
    res = asyncio.run(
        reg.run(ToolUse(id="t1", name=name, input={}), AbortController())
    )
    assert res.is_error is False
    # 50 字符预算 → "ok"*30=60 字符溢出 → spill 预览。
    assert "[output truncated" in res.content


def test_long_name_truncated_deterministically():
    raw = "a" + "_" * 300 + "z"
    n1 = mcp_tool_name("fs", raw)
    n2 = mcp_tool_name("fs", raw)
    assert n1 == n2  # 确定性
    assert len(n1.encode("utf-8")) <= MAX_TOOL_NAME_BYTES
    assert n1.startswith("mcp__fs__") and n1.endswith("__" + n1.split("__")[-1])
    assert len(n1.split("__")[-1]) == 12  # 12hex 身份钉保留
    # 同 server 不同 raw 不因截断相撞（hex 键不同）。
    n_other = mcp_tool_name("fs", "b" + "_" * 300 + "y")
    assert n_other != n1


def test_exposure_of_static_and_dynamic():
    # 动态工具：实例属性优先；静态工具：表项优先（实例属性被忽略）。
    spec = McpClientSpec(id="fs", command="x")
    tool = McpTool(
        None, spec, server_id="fs", raw_name="r", tool_name="mcp__fs__r__a1b2c3d4e5f6",
        raw_schema=_raw("r"), policy="outbound_ask",
    )
    assert exposure_of(tool) == "normal"
    tool.exposure = "hidden"
    assert exposure_of(tool) == "hidden"

    class _StaticNamed:
        name = "Read"  # 静态表项 → normal（即使实例乱标 hidden）
        exposure = "hidden"

    assert exposure_of(_StaticNamed()) == "normal"
