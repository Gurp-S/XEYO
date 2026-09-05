"""F3 mcp 权限闭环：企业 deny / 三态 / grant / 实例只读 flag。

运行：``py -3.11 -m pytest tests/test_mcp_policy.py -q``
"""

from __future__ import annotations

import asyncio
import os

import pytest

from engine.abort import AbortController
from extension import mcp_scopes as scopes
from extension.mcp_client import (
	McpClientSpec,
	McpTool,
	mcp_tool_name,
	spec_read_only,
)
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from permissions.policy import (
	evaluate_policy,
	evaluate_policy_impl,
	readonly_gate,
	set_permission_mode,
)
from tools.tool_registry import ToolRegistry


def _tool(*, policy="outbound_ask", read_only=False, concurrency_safe=False, client=None, spec=None):
	spec = spec or McpClientSpec(id="fs", command="x")
	raw = {"name": "read_file", "inputSchema": {"type": "object", "properties": {}}}
	tn = mcp_tool_name("fs", "read_file")
	return McpTool(
		client, spec, server_id="fs", raw_name="read_file", tool_name=tn,
		raw_schema=raw, policy=policy, read_only=read_only,
		concurrency_safe=concurrency_safe,
	)


def _cwd(tmp_path):
	return os.path.abspath(str(tmp_path))


def test_always_allow_is_allow(tmp_path):
	tool = _tool(policy="always_allow")
	d = evaluate_policy_impl(tool.name, {}, cwd=_cwd(tmp_path), tool=tool)
	assert d.decision == PermissionDecision.ALLOW
	assert d.matched_rule == "mcp_always_allow"


def test_outbound_ask_is_ask(tmp_path):
	tool = _tool(policy="outbound_ask")
	d = evaluate_policy_impl(tool.name, {}, cwd=_cwd(tmp_path), tool=tool)
	assert d.decision == PermissionDecision.ASK
	assert d.matched_rule == "mcp_outbound_ask"


def test_unknown_policy_falls_back_ask(tmp_path):
	spec = McpClientSpec(id="fs", command="x", tools_policy="weird")
	tool = _tool(policy="weird", spec=spec)
	d = evaluate_policy_impl(tool.name, {}, cwd=_cwd(tmp_path), tool=tool)
	assert d.decision == PermissionDecision.ASK


def test_enterprise_tool_deny_wins(tmp_path, monkeypatch):
	pol_path = tmp_path / "policy.json"
	monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol_path))
	pol_path.write_text(
		'{"mcp_tool_deny": ["fs/read_file", "other/*"]}', encoding="utf-8"
	)
	tool = _tool(policy="always_allow")
	d = evaluate_policy_impl(tool.name, {}, cwd=_cwd(tmp_path), tool=tool)
	# deny 最严胜出，覆盖 always_allow。
	assert d.decision == PermissionDecision.DENY
	assert d.matched_rule == "mcp_enterprise_deny"


def test_enterprise_server_deny_wins(tmp_path, monkeypatch):
	pol_path = tmp_path / "policy.json"
	monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol_path))
	pol_path.write_text('{"mcp_server_deny": ["fs"]}', encoding="utf-8")
	tool = _tool(policy="always_allow")
	d = evaluate_policy_impl(tool.name, {}, cwd=_cwd(tmp_path), tool=tool)
	assert d.decision == PermissionDecision.DENY


def test_grant_hit_returns_allow(tmp_path):
	from permissions.store import default_grant_store, grant_fingerprint

	cwd = _cwd(tmp_path)
	tool = _tool(policy="outbound_ask")
	# 先得到 ASK 决策的 matched_rule，再据此落 grant。
	base = evaluate_policy_impl(tool.name, {}, cwd=cwd, tool=tool)
	assert base.decision == PermissionDecision.ASK
	fp = grant_fingerprint(tool.name, {}, matched_rule=str(base.matched_rule or ""))
	default_grant_store().add(tool_name=tool.name, fingerprint=fp, scope=cwd)
	d = evaluate_policy(tool.name, {}, cwd=cwd, tool=tool)
	assert d.decision == PermissionDecision.ALLOW
	assert d.matched_rule == "grant_store"


def test_no_coordinator_ask_becomes_deny_via_registry(tmp_path):
	# registry.run + ASK + 无 coordinator → DENY（fail-safe）。
	reg = ToolRegistry(cwd=str(tmp_path))
	tool = _tool(policy="outbound_ask")
	reg.register(tool)

	async def _run():
		return await reg.run(ToolUse(id="1", name=tool.name, input={}), AbortController())

	result = asyncio.run(_run())
	assert result.is_error is True
	assert result.metadata.get("permission_reason") == "needs_confirmation"
	assert "no resolver" in result.content


def test_instance_readonly_flows_through_gate(tmp_path):
	# read_only 实例 → readonly_gate 放行（readonly preset 下）。
	tool = _tool(read_only=True, concurrency_safe=True)
	assert tool.is_read_only() is True
	assert tool.is_concurrency_safe() is True
	# readonly_gate(agent mode) 无条件放行；readonly preset 也放行只读实例。
	assert readonly_gate(tool.name, tool=tool) is None


def test_default_mcp_tool_not_readonly():
	tool = _tool()
	assert tool.is_read_only() is False
	assert tool.is_concurrency_safe() is False


def test_spec_read_only_manifest_declared():
	spec = McpClientSpec(id="fs", command="x", read_only_tools=("read_file",))
	assert spec_read_only(spec, "read_file") is True
	assert spec_read_only(spec, "write_file") is False


def test_spec_read_only_trust_annotations():
	spec = McpClientSpec(id="fs", command="x", trust_annotations=True)
	assert (
		spec_read_only(spec, "t", raw_schema={"annotations": {"readOnlyHint": True}}) is True
	)
	assert (
		spec_read_only(
			spec, "t", raw_schema={"annotations": {"readOnlyHint": True, "destructiveHint": True}}
		)
		is False
	)
	# 缺省不信 server：trust_annotations false → 不判只读。
	spec0 = McpClientSpec(id="fs", command="x")
	assert spec_read_only(spec0, "t", raw_schema={"annotations": {"readOnlyHint": True}}) is False


def test_early_speculative_eligible_for_readonly_mcp(tmp_path):
	from engine.query_loop import _eligible_for_early

	reg = ToolRegistry(cwd=str(tmp_path))
	# 只读 MCP 工具 + always_allow → 可早期投机。
	spec = McpClientSpec(id="fs", command="x", read_only_tools=("read_file",))
	tool = _tool(policy="always_allow", read_only=True, concurrency_safe=True, spec=spec)
	reg.register(tool)
	ok = _eligible_for_early(reg, ToolUse(id="9", name=tool.name, input={}), forced_wrap_up=False)
	assert ok is True
	# 默认非只读 MCP 工具不可早期。
	reg2 = ToolRegistry(cwd=str(tmp_path))
	tool2 = _tool(policy="always_allow")
	reg2.register(tool2)
	ok2 = _eligible_for_early(reg2, ToolUse(id="9", name=tool2.name, input={}), forced_wrap_up=False)
	assert ok2 is False
