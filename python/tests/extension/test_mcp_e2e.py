"""P0a 主链 e2e（设计 §9 P0a 出口 / §15.5 主链「启用→调用→审计」）。

链路：settings 启用 → user/plugin scope server（fake transport，不 spawn 真进程）
→ ``McpManager.attach_mcp_tools`` → ``mcp__server__raw__hex`` 进 schemas
→ ``ToolRegistry.run``（无 coordinator）：policy ASK → fail-safe DENY
→ 落 grant（指纹 = matched_rule）→ ``evaluate_policy`` → ALLOW
→ 再 ``registry.run`` 真执行 → 审计含 ``mcp.tool.call``（server/raw_tool 硬字段，
设计 §15.4：写入端保证，不靠读端解析）。

运行：``py -3.11 -m pytest tests/extension/test_mcp_e2e.py -q``
"""

from __future__ import annotations

import asyncio
import json
import queue
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy, evaluate_policy_impl
from tools.tool_registry import ToolRegistry


class FakeMcpTransport:
	"""合成 JSON-RPC 响应（同 tests/extension/test_mcp_manager.py 的进程内 stub）。"""

	def __init__(self, spec, *, logger=None, tools=None):
		self.spec = spec
		self.tools = list(tools or [])
		self.sent = []
		self._responses = queue.Queue()
		self._alive = False
		self.spawn_calls = 0

	def spawn(self):
		self.spawn_calls += 1
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
				"content": [{"type": "text", "text": "ok"}], "isError": False}}
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


class _SharedFakeSpec:
	"""共享 fake 的占位 spec（错误文案才用到 id，主链不触发）。"""


def _raw(name="read_file"):
	return {"name": name, "inputSchema": {"type": "object", "properties": {}}}


def _write_settings(ws: Path, data: dict) -> None:
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(json.dumps(data), encoding="utf-8")


def _write_user_mcp(servers: dict) -> None:
	"""写 user scope mcp.json（免批）；XEYO_HOME 由 conftest 钉进 tmp。"""
	from memory.instruction import xeyo_home

	p = xeyo_home() / "mcp.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(json.dumps({"servers": servers}), encoding="utf-8")


@pytest.fixture
def audit(monkeypatch, tmp_path) -> Path:
	"""审计/企业策略/审批模式隔离：空审计文件 + 无 deny + 非 always 模式。"""
	from audit.log import reset_default_audit_log

	log = tmp_path / "audit.jsonl"
	monkeypatch.setenv("XEYO_AUDIT_LOG", str(log))
	# 机器级 ~/.xeyo/policy.json 不得泄漏（deny 一票否决会打断主链）。
	monkeypatch.setenv(
		"XEYO_ENTERPRISE_POLICY", str(tmp_path / "enterprise-policy.json")
	)
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	reset_default_audit_log()
	yield log
	reset_default_audit_log()


def _mcp_names(reg: ToolRegistry, prefix: str) -> list[str]:
	return [t["name"] for t in reg.schemas() if t["name"].startswith(prefix)]


def test_main_chain_enable_ask_deny_grant_allow_audit(tmp_path, audit):
	"""主链：启用 → attach → ASK/DENY → grant → ALLOW → 执行 → 审计。"""
	from extension import mcp_manager as mm

	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(
		ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}
	)
	_write_user_mcp({"fs": {"command": "node", "args": []}})

	mgr = mm.McpManager(
		str(ws),
		transport_factory=lambda spec, logger=None: FakeMcpTransport(
			spec, tools=[_raw()]
		),
	)
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)

	# ① schemas：唯一 mcp__fs__read_file__<12hex>，schema 名 = 注册名（dispatch 键）。
	mcp_names = _mcp_names(reg, "mcp__fs__")
	assert len(mcp_names) == 1
	tool_name = mcp_names[0]
	schema = next(t for t in reg.schemas() if t["name"] == tool_name)
	assert schema["name"] == tool_name
	tool = reg.get(tool_name)
	assert tool is not None
	assert tool.server_id == "fs"
	assert tool.raw_name == "read_file"
	assert mgr.snapshot()["servers"]["fs"]["state"] == "ready"

	# ② 无 grant / 无 coordinator：policy ASK → registry.run fail-safe DENY。
	res1 = asyncio.run(
		reg.run(ToolUse(id="t1", name=tool_name, input={}), AbortController())
	)
	assert res1.is_error is True
	assert res1.metadata.get("permission_reason") == "needs_confirmation"
	assert "no resolver" in res1.content

	# ③ 落 grant（指纹 = matched_rule）→ evaluate_policy → ALLOW。
	base = evaluate_policy_impl(tool_name, {}, cwd=str(ws), tool=tool)
	assert base.decision == PermissionDecision.ASK
	assert base.matched_rule == "mcp_outbound_ask"

	from permissions.store import default_grant_store, grant_fingerprint

	fp = grant_fingerprint(tool_name, {}, matched_rule=str(base.matched_rule or ""))
	# P0b 指纹 v2：MCP 调用点身份哈希（args 永不参与），v1 裸 matched_rule 已淘汰。
	assert fp.startswith("v2:")
	default_grant_store().add(tool_name=tool_name, fingerprint=fp, scope=str(ws))
	decision = evaluate_policy(tool_name, {}, cwd=str(ws), tool=tool)
	assert decision.decision == PermissionDecision.ALLOW
	assert decision.matched_rule == "grant_store"

	# ④ 放行后真执行：fake server 回 "ok"；审计含 mcp.tool.call 硬字段。
	res2 = asyncio.run(
		reg.run(ToolUse(id="t2", name=tool_name, input={}), AbortController())
	)
	assert res2.is_error is False
	assert res2.content == "ok"

	from audit.log import AuditLog

	rows = AuditLog(audit).read_all()
	calls = [r for r in rows if r.get("kind") == "mcp.tool.call"]
	assert len(calls) == 1
	call = calls[0]
	assert call["server"] == "fs"
	assert call["raw_tool"] == "read_file"
	assert call["is_error"] is False
	assert "duration_ms" in call
	# registry 写入端执行审计同样落地（带注册名）。
	finished = [
		r
		for r in rows
		if r.get("kind") == "tool.finished" and r.get("tool_name") == tool_name
	]
	assert len(finished) == 1
	assert finished[0]["is_error"] is False


def test_plugin_scope_server_attaches_without_trust(tmp_path, audit):
	"""插件 manifest ``mcp_servers``（plugin scope 免批）→ attach 即用，默认 ASK。"""
	from extension import mcp_manager as mm

	ws = tmp_path / "ws"
	plug = ws / ".xeyo" / "plugins" / "demo"
	plug.mkdir(parents=True)
	(plug / "plugin.json").write_text(
		json.dumps(
			{
				"name": "demo",
				"version": "0.1.0",
				"description": "demo plugin",
				"mcp_servers": [
					{
						"id": "plug",
						"transport": "stdio",
						"command": "node",
						"args": [],
						"tools_policy": "outbound_ask",
					}
				],
			}
		),
		encoding="utf-8",
	)
	_write_settings(
		ws,
		{
			"enabled_extensions": True,
			"plugins": {"demo": {"enabled": True}},
			"mcp_servers": {"plug": {"enabled": True}},
		},
	)

	# 共享 fake（factory 忽略传入 spec），spawn_calls 在 attach 时 +1。
	fake = FakeMcpTransport(_SharedFakeSpec(), tools=[_raw("list_items")])
	mgr = mm.McpManager(str(ws), transport_factory=lambda spec, logger=None: fake)
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)

	# 插件 scope 免批：无 mcp-trust.json 也 spawn。
	assert fake.spawn_calls == 1
	mcp_names = _mcp_names(reg, "mcp__plug__")
	assert len(mcp_names) == 1
	tool_name = mcp_names[0]
	tool = reg.get(tool_name)
	assert tool is not None
	assert tool.server_id == "plug"
	assert tool.raw_name == "list_items"

	# 默认 outbound_ask → ASK；无 coordinator → DENY（fail-safe，不绕权限三态）。
	res = asyncio.run(
		reg.run(ToolUse(id="t1", name=tool_name, input={}), AbortController())
	)
	assert res.is_error is True
	assert res.metadata.get("permission_reason") == "needs_confirmation"
	# 未放行 → 不执行 → 无 mcp.tool.call。
	from audit.log import AuditLog

	assert not [r for r in AuditLog(audit).read_all() if r.get("kind") == "mcp.tool.call"]


def test_enterprise_tool_deny_blocks_main_chain(tmp_path, audit):
	"""企业 deny（policy 层）一票否决：grant 不得触碰 DENY（最严胜出）。"""
	from extension import mcp_manager as mm

	# mcp_tool_deny 不参与 collect 层剔除（server 照常 spawn/注册），
	# 在权限评估层一票否决 —— 与 server_deny 的 collect 层剔除互补。
	(tmp_path / "enterprise-policy.json").write_text(
		'{"mcp_tool_deny": ["fs/read_file"]}', encoding="utf-8"
	)
	ws = tmp_path / "ws"
	ws.mkdir()
	_write_settings(
		ws, {"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}
	)
	_write_user_mcp({"fs": {"command": "node", "args": []}})

	mgr = mm.McpManager(
		str(ws),
		transport_factory=lambda spec, logger=None: FakeMcpTransport(
			spec, tools=[_raw()]
		),
	)
	reg = ToolRegistry(cwd=str(ws))
	mgr.attach_mcp_tools(reg)

	mcp_names = _mcp_names(reg, "mcp__fs__")
	assert len(mcp_names) == 1
	tool_name = mcp_names[0]
	tool = reg.get(tool_name)
	assert tool is not None

	decision = evaluate_policy_impl(tool_name, {}, cwd=str(ws), tool=tool)
	assert decision.decision == PermissionDecision.DENY
	assert decision.matched_rule == "mcp_enterprise_deny"

	# grant 不得触碰 DENY。
	from permissions.store import default_grant_store, grant_fingerprint

	fp = grant_fingerprint(tool_name, {}, matched_rule="mcp_outbound_ask")
	default_grant_store().add(tool_name=tool_name, fingerprint=fp, scope=str(ws))
	outer = evaluate_policy(tool_name, {}, cwd=str(ws), tool=tool)
	assert outer.decision == PermissionDecision.DENY

	res = asyncio.run(
		reg.run(ToolUse(id="t1", name=tool_name, input={}), AbortController())
	)
	assert res.is_error is True
	assert res.metadata.get("permission_reason") == "mcp_enterprise_deny"
	# 未执行 → 无 mcp.tool.call。
	from audit.log import AuditLog

	assert not [
		r for r in AuditLog(audit).read_all() if r.get("kind") == "mcp.tool.call"
	]
