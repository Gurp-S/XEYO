"""F2.5 reconcile（P0b）：push 活页块 + digest 幂等 + 移除→DENY 门 + skill 拒载。

运行：``py -3.11 -m pytest tests/extension/test_reconcile.py -q``
"""

from __future__ import annotations

import asyncio
import json
import queue

import pytest

from engine.abort import AbortController
from extension import mcp_manager as mm
from extension.config import (
    load_ext_config,
    set_mcp_enabled,
    set_skill_enabled,
    workspace_settings_path,
    write_settings,
)
from extension.mcp_client import mcp_tool_name
from extension.reconcile import (
    consume_reconcile_blocks,
    publish_if_changed,
    reconcile_digest,
    reset_reconcile_state,
)
from msgtypes.message import ToolUse
from tools.skill_tool.skill_tool import SkillTool
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


def _raw(name="read_file"):
    return {"name": name, "inputSchema": {"type": "object", "properties": {}}}


def _setup(tmp_path, *, tools, spec_extra=None, call_text="ok"):
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
            spec, tools=tools, call_text=call_text
        ),
    )
    reg = ToolRegistry(cwd=str(ws))
    mgr.attach_mcp_tools(reg)
    return ws, mgr, reg


def _run(reg, name, payload):
    return asyncio.run(
        reg.run(ToolUse(id="t1", name=name, input=payload), AbortController())
    )


# -- push：原子写 + 活页块（digest 幂等） ------------------------------------


def test_set_mcp_enabled_atomic_write_and_readback(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True}), encoding="utf-8"
    )
    set_mcp_enabled(str(ws), "fs", True)
    cfg = load_ext_config(str(ws))
    assert cfg.mcp_enabled("fs") is True
    p = workspace_settings_path(str(ws))
    assert json.loads(p.read_text(encoding="utf-8"))["mcp_servers"]["fs"]["enabled"] is True
    leftovers = [x.name for x in p.parent.iterdir() if ".tmp" in x.name]
    assert leftovers == []


def test_set_mcp_enabled_publishes_block_once(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    set_mcp_enabled(str(ws), "fs", True)
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1
    assert "# 工具面变更（background only — 非用户新提问）" in blocks[0]
    assert "启用" in blocks[0] and "fs" in blocks[0]
    # 同值重复 set → digest 未变 → 不再发布（幂等）。
    set_mcp_enabled(str(ws), "fs", True)
    assert consume_reconcile_blocks() == []


def test_set_skill_enabled_block_and_drain(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    set_skill_enabled(str(ws), "code-review", False)
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1
    assert "# 技能目录变更（background only — 非用户新提问）" in blocks[0]
    assert "−code-review" in blocks[0]
    assert consume_reconcile_blocks() == []  # 消费即清
    set_skill_enabled(str(ws), "code-review", True)
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1 and "+code-review" in blocks[0]


def test_publish_if_changed_digest_semantics():
    assert publish_if_changed("k", {"a": 1}, lambda: "b1") is True
    assert publish_if_changed("k", {"a": 1}, lambda: "b1") is False  # digest 未变
    assert publish_if_changed("k", {"a": 2}, lambda: "b2") is True
    assert reconcile_digest({"a": 1, "b": 2}) == reconcile_digest({"b": 2, "a": 1})
    assert consume_reconcile_blocks() == ["b1", "b2"]


# -- pull 兜底 + 移除→DENY 门 ------------------------------------------------


def test_disabled_server_native_call_denied_then_reenabled(tmp_path):
    ws, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")], call_text="ran")
    name = mcp_tool_name("fs", "read_file")
    # 基线：注册探针就位，正常走 ASK。
    res = _run(reg, name, {})
    assert res.metadata.get("permission_reason") == "needs_confirmation"
    # 会话内停用（push 写盘）→ 下次调用 DENY（探针 mtime 重读）。
    set_mcp_enabled(str(ws), "fs", False)
    consume_reconcile_blocks()
    res = _run(reg, name, {})
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "mcp_disabled"
    # grant 不可穿越：即使先落 allow 授权也被停用门拦截。
    from permissions.store import default_grant_store, grant_fingerprint

    default_grant_store().add(
        tool_name=name, fingerprint=grant_fingerprint(name, {}), scope=str(ws)
    )
    res = _run(reg, name, {})
    assert res.metadata.get("permission_reason") == "mcp_disabled"
    # 重新启用 → 恢复可用（授权命中 → 执行）。
    set_mcp_enabled(str(ws), "fs", True)
    consume_reconcile_blocks()
    res = _run(reg, name, {})
    assert res.is_error is False and res.content == "ran"


def test_unchecked_tool_disabled_by_probe(tmp_path):
    """注册时勾选、会话内被取消勾选 → 移除→DENY 门；注册时即未勾选 → 仍 ASK。"""
    ws, mgr, reg = _setup(
        tmp_path, tools=[_raw("read_file"), _raw("write_file")],
        spec_extra={"enabled_tools": ["read_file"]},
    )
    hidden_name = mcp_tool_name("fs", "write_file")
    # hidden-but-registered（attach 时即未勾选）：默认走 ASK（fail-safe，不设门）。
    res = _run(reg, hidden_name, {})
    assert res.metadata.get("permission_reason") == "needs_confirmation"
    # 注册时勾选的 read_file 被取消勾选（mcp.json 声明处）→ 探针 False → DENY。
    from memory.instruction import xeyo_home

    mp = xeyo_home() / "mcp.json"
    mdata = json.loads(mp.read_text(encoding="utf-8"))
    mdata["servers"]["fs"]["enabled_tools"] = ["write_file"]
    mp.write_text(json.dumps(mdata), encoding="utf-8")
    res = _run(reg, mcp_tool_name("fs", "read_file"), {})
    assert res.metadata.get("permission_reason") == "mcp_disabled"
    # write_file 保持基线（一直未勾选）→ 仍 ASK。
    res = _run(reg, hidden_name, {})
    assert res.metadata.get("permission_reason") == "needs_confirmation"


def test_gateway_call_disabled_target_denied(tmp_path):
    ws, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")])
    set_mcp_enabled(str(ws), "fs", False)
    consume_reconcile_blocks()
    res = _run(
        reg, "Mcp", {"action": "call", "server": "fs", "tool": "read_file", "args": {}}
    )
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "mcp_disabled"


def test_external_change_pull_publishes_block_once(tmp_path):
    """另一进程写盘 → 本进程 _load_config 检出 diff → 补发一次活页块。"""
    ws, mgr, reg = _setup(tmp_path, tools=[_raw("read_file")])
    data = json.loads(workspace_settings_path(str(ws)).read_text(encoding="utf-8"))
    data["mcp_servers"]["fs"]["enabled"] = False
    # 模拟外部写（直接写文件，不走 set_mcp_enabled 的 push 通道）。
    import os
    import time

    p = workspace_settings_path(str(ws))
    time.sleep(0.01)  # mtime 分辨率保护
    write_settings(p, data)
    os.utime(p, ns=(time.time_ns() + 10**7, time.time_ns() + 10**7))
    mgr._load_config()
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1 and "fs" in blocks[0] and "停用" in blocks[0]
    mgr._load_config()  # 未再变化 → 不重发
    assert consume_reconcile_blocks() == []


def test_skill_disabled_load_message(tmp_path):
    """会话内停用 skill → 加载侧即时拒绝（区别于未安装）。"""
    ws = tmp_path / "ws"
    skill_dir = ws / ".xeyo" / "skills" / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: 部署流程\n---\n\n# deploy\n步骤……",
        encoding="utf-8",
    )
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True}), encoding="utf-8"
    )
    tool = SkillTool(cwd=str(ws))  # 会话目录快照（含 deploy）
    res = asyncio.run(
        tool.execute({"name": "deploy"}, AbortController())
    )
    assert res.is_error is False
    set_skill_enabled(str(ws), "deploy", False)
    consume_reconcile_blocks()
    res = asyncio.run(
        tool.execute({"name": "deploy"}, AbortController())
    )
    assert res.is_error is True
    assert "已被用户停用" in res.content
    # 未安装的仍报 not found。
    res = asyncio.run(
        tool.execute({"name": "nope"}, AbortController())
    )
    assert res.is_error is True and "not found" in res.content


def test_pre_llm_inject_drains_reconcile_blocks():
    """注入点：consume 通道接入 pre_llm_inject（冒烟：函数可导入不炸）。"""
    from prompt.pre_llm_inject import run_pre_llm_inject  # noqa: F401

    from extension.reconcile import publish_reconcile_block

    publish_reconcile_block("# 工具面变更（background only）\n- smoke")
    blocks = consume_reconcile_blocks()
    assert blocks and "smoke" in blocks[0]
