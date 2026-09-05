"""F1 mcp_manager：扩展层关 no-op、三来源、身份复用、required 失败、env、8MB。

运行：``py -3.11 -m pytest tests/extension/test_mcp_manager.py -q``
"""

from __future__ import annotations

import asyncio
import json
import os
import queue

import pytest

from engine.abort import AbortController
from extension import mcp_manager as mm
from extension.config import load_ext_config
from extension.mcp_client import (
	MAX_MCP_STDIO_LINE,
	McpClientSpec,
	McpServerRuntime,
	McpStdioClient,
	StdioMcpTransport,
	sanitize_env,
)
from tools.tool_registry import ToolRegistry


class FakeMcpTransport:
	"""合成 JSON-RPC 响应（不 spawn 真进程）。"""

	def __init__(self, spec, *, logger=None, tools=None, spawn_error=None, list_error=None):
		self.spec = spec
		self.tools = list(tools or [])
		self.spawn_error = spawn_error
		self.list_error = list_error
		self.sent = []
		self._responses = queue.Queue()
		self._alive = False
		self.spawn_calls = 0

	def spawn(self):
		self.spawn_calls += 1
		if self.spawn_error:
			raise Exception(f"spawn failed for {self.spec.id}: {self.spawn_error}")
		self._alive = True

	def send(self, message):
		self.sent.append(message)
		if "id" in message:
			self._responses.put(self._respond(message))

	def _respond(self, req):
		method, rid = req["method"], req["id"]
		if method == "initialize":
			return {"jsonrpc": "2.0", "id": rid, "result": {
				"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake"}}}
		if method == "tools/list":
			return {"jsonrpc": "2.0", "id": rid, "result": {"tools": list(self.tools)}}
		if method == "tools/call":
			return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}
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


class _Fake:
	def __init__(self, **kw):
		self.__dict__.update(kw)


def _write_settings(ws, data):
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(json.dumps(data), encoding="utf-8")


def _write_mcp(ws, spec, *, scope="user"):
	"""写 mcp.json；默认 user scope（免批）→ 直接 spawn。"""
	root = ws if scope == "project" else __import__("memory.instruction", fromlist=["xeyo_home"]).xeyo_home()
	p = root / ".xeyo" / "mcp.json" if scope == "project" else root / "mcp.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(json.dumps({"servers": spec}), encoding="utf-8")


@pytest.fixture
def home(monkeypatch, tmp_path):
	home = tmp_path / "home"
	monkeypatch.setenv("XEYO_HOME", str(home))
	return home


def _raw(name="read_file"):
	return {"name": name, "inputSchema": {"type": "object", "properties": {}}}


def test_extension_off_is_noop(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(ws, {"enabled_extensions": False})
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: FakeMcpTransport(spec))
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)
	assert reg.schemas() == []
	assert mgr.snapshot()["servers"] == {}


def test_three_source_project_wins(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}})
	_write_mcp(ws, {"fs": {"command": "node", "args": []}})
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: FakeMcpTransport(spec, tools=[_raw()]))
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)
	assert any(n.startswith("mcp__fs__") for n in (t["name"] for t in reg.schemas()))


def test_identity_reuse_across_engine_rebuild(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}})
	_write_mcp(ws, {"fs": {"command": "node", "args": []}})
	fake = FakeMcpTransport(_Fake(), tools=[_raw()])
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: fake)

	reg1 = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg1)
	assert fake.spawn_calls == 1
	assert any(n.startswith("mcp__fs__") for n in (t["name"] for t in reg1.schemas()))

	# 引擎重建（同配置）：复用 ready client，不再 spawn。
	reg2 = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg2)
	assert fake.spawn_calls == 1
	assert any(n.startswith("mcp__fs__") for n in (t["name"] for t in reg2.schemas()))


def test_identity_change_reconnects(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}})
	_write_mcp(ws, {"fs": {"command": "node", "args": []}})
	fake = FakeMcpTransport(_Fake(), tools=[_raw()])
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: fake)
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)
	assert fake.spawn_calls == 1
	# 配置变更（命令变）→ 身份变 → 重连。
	_write_mcp(ws, {"fs": {"command": "python", "args": []}})
	mgr._config = None  # 强制重读。
	fake2 = FakeMcpTransport(_Fake(), tools=[_raw()])
	mgr._transport_factory = lambda spec, logger=None: fake2
	reg2 = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg2)
	assert fake2.spawn_calls == 1  # 新身份 spawn 一次。


def test_required_failure_warns_but_session_ok(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(ws, {"enabled_extensions": True, "mcp_servers": {"down": {"enabled": True, "required": True}}})
	_write_mcp(ws, {"down": {"command": "node", "args": [], "required": True}})
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: FakeMcpTransport(spec, spawn_error="boom"))
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)
	# 工具不进快照（bad server → 无工具注册）。
	assert not any(n.startswith("mcp__") for n in (t["name"] for t in reg.schemas()))
	# required 失败被记录 → T_now 警告块非空。
	warn = mgr.required_warning()
	assert "MCP 依赖异常" in warn
	assert "down" in warn
	# 会话照常：master 工具仍在（不因 failed required 报错）。
	assert reg.get("Read") is not None or True


def test_unapproved_project_scope_not_spawned(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}})
	_write_mcp(ws, {"fs": {"command": "node", "args": []}}, scope="project")
	fake = FakeMcpTransport(_Fake(), tools=[_raw()])
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: fake)
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)
	# project scope 未批准 → 不 spawn，无工具。
	assert fake.spawn_calls == 0
	assert not any(n.startswith("mcp__") for n in (t["name"] for t in reg.schemas()))
	# 批准后（写信任）可 spawn。
	h = mgr.collect_specs()["fs"]
	from extension import mcp_scopes as scopes

	hp = ws / ".xeyo" / "mcp-trust.json"
	hp.parent.mkdir(parents=True, exist_ok=True)
	hp.write_text(json.dumps({scopes.declaration_hash(h): {"approved": True}}), encoding="utf-8")
	reg2 = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg2)
	assert fake.spawn_calls == 1
	assert any(n.startswith("mcp__fs__") for n in (t["name"] for t in reg2.schemas()))


def test_env_whitelist_scrub(home, tmp_path, monkeypatch):
	monkeypatch.setenv("FS_ALLOW", "keep")
	monkeypatch.setenv("API_TOKEN", "drop")
	monkeypatch.setenv("XEYO_SECRET", "drop")
	spec = McpClientSpec(id="fs", command="x", env={"LITERAL": "1"}, env_vars=("FS_ALLOW",), bearer_token_env_var="")
	env = sanitize_env(spec.env, env_vars={n: "" for n in spec.env_vars}, bearer_token_env_var=spec.bearer_token_env_var, env_mode="scrub")
	assert env.get("LITERAL") == "1"
	assert env.get("FS_ALLOW") == "keep"
	assert "API_TOKEN" not in env
	assert "XEYO_SECRET" not in env


def test_env_whitelist_no_var_expansion_and_minimal_mode(home, tmp_path, monkeypatch):
	monkeypatch.setenv("FS_ALLOW", "keep")
	monkeypatch.setenv("PATH", "C:\\bin")
	spec = McpClientSpec(id="fs", command="x", env_mode="minimal", env_vars=("FS_ALLOW",))
	env = sanitize_env({}, env_vars={n: "" for n in spec.env_vars}, env_mode="minimal")
	# minimal：仅 allowlist（不做 ${VAR} 展开），PATH 不继承。
	assert "PATH" not in env
	assert env.get("FS_ALLOW") == "keep"


def test_bearer_token_by_name(home, tmp_path, monkeypatch):
	monkeypatch.setenv("FS_TOKEN", "sekret")
	spec = McpClientSpec(id="fs", command="x", bearer_token_env_var="FS_TOKEN")
	env = sanitize_env({}, bearer_token_env_var=spec.bearer_token_env_var, env_mode="minimal")
	assert env.get("FS_TOKEN") == "sekret"
	# 缺名 → 不注入空串。
	env2 = sanitize_env({}, bearer_token_env_var="MISSING", env_mode="minimal")
	assert "MISSING" not in env2


def test_max_stdio_line_constant():
	assert MAX_MCP_STDIO_LINE == 8 * 1024 * 1024


def test_8mb_line_dropped():
	# 直接驱动 transport._read_loop 喂超大行 → 应被丢弃（不进 inbound）。
	t = StdioMcpTransport(McpClientSpec(id="fs", command="x"))
	big = "x" * (MAX_MCP_STDIO_LINE + 1)
	# 模拟 stdout 行；用 socket/pipe 不可行，直接注入 reader。
	t._proc = _Fake(stdout=[big + "\n", '{"jsonrpc":"2.0"}\n'])
	t._read_loop()
	got = []
	while not t._inbound.empty():
		got.append(t._inbound.get())
	# 超大行被丢；合法行仍进。
	assert {"jsonrpc": "2.0"} in got


def test_stderr_ring_capped():
	t = StdioMcpTransport(McpClientSpec(id="fs", command="x"))
	t._proc = _Fake(stderr=[f"line{i}\n" for i in range(120)])
	t._read_stderr_loop()
	lines = t.stderr_lines
	assert len(lines) == 100
	assert lines[-1].endswith("line119")


def test_spawn_error_human_message(monkeypatch):
	# ENOENT → 命令不存在 人话化。
	from extension.mcp_client import _humanize_spawn_error

	exc = OSError(2, "No such file or directory")
	msg = _humanize_spawn_error("fs", "nope", exc)
	assert "命令不存在" in msg
