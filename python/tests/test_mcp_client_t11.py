"""T11 MCP stdio client tests.

Covers the four acceptance bullets (skip-and-log, bounded crash-loop, no-name
collapse, permission 3-way gate) plus the feasible extras: timeout split, schema
sanitize + 5KB degrade, whole-generation replacement, settings HMR reconnect hook.

Production subprocesses are never spawned: the client drives the abstract
:class:`McpTransport` through a :class:`FakeMcpTransport` that synthesizes JSON-RPC
responses from a configurable tool list. Running from ``python/``:
``py -3.11 -m pytest tests/test_mcp_client_t11.py -q --timeout=180``.
"""

from __future__ import annotations

import json
import logging
import queue
import time

import pytest

from engine.abort import AbortController
from extension.mcp_client import (
	BACKOFF_BASE_S,
	BACKOFF_MAX_S,
	MAX_RECONNECT_ATTEMPTS,
	RESET_UPTIME_S,
	SCHEMA_BUDGET_BYTES,
	STARTUP_TIMEOUT_S,
	TOOL_TIMEOUT_S,
	McpClientSpec,
	McpError,
	McpSpawnError,
	McpStdioClient,
	McpTimeoutError,
	McpTool,
	McpServerRuntime,
	McpGeneration,
	ReconnectBackoff,
	build_tools,
	mcp_default_policy,
	mcp_policy_decision,
	mcp_tool_name,
	normalize_raw_tool_name,
	register_mcp_server,
	resolve_mcp_policy,
	sanitize_tool_schema,
)
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from tools.tool_registry import ToolRegistry


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class FakeMcpTransport:
	"""Synthesizes JSON-RPC responses from a configurable tool list. Never spawns."""

	def __init__(self, spec, *, logger=None, tools=None, spawn_error=None, list_error=None):
		self.spec = spec
		self.tools = list(tools or [])
		self.spawn_error = spawn_error
		self.list_error = list_error
		self.sent = []
		self._responses = queue.Queue()
		self._notifications = []
		self._alive = False
		self.spawn_calls = 0

	def spawn(self):
		self.spawn_calls += 1
		if self.spawn_error:
			raise McpSpawnError(f"spawn failed for {self.spec.id}: {self.spawn_error}")
		self._alive = True

	def send(self, message):
		self.sent.append(message)
		if "id" in message:
			self._responses.put(self._respond(message))
		else:
			self._notifications.append(message)

	def _respond(self, req):
		method = req["method"]
		rid = req["id"]
		if method == "initialize":
			return {
				"jsonrpc": "2.0",
				"id": rid,
				"result": {
					"protocolVersion": "2024-11-05",
					"capabilities": {"tools": {}},
					"serverInfo": {"name": "fake", "version": "0"},
				},
			}
		if method == "tools/list":
			if self.list_error:
				raise McpSpawnError(self.list_error)
			return {"jsonrpc": "2.0", "id": rid, "result": {"tools": list(self.tools)}}
		if method == "tools/call":
			return {
				"jsonrpc": "2.0",
				"id": rid,
				"result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
			}
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

	def crash(self):
		self._alive = False

	def inject_notification(self, method, params=None):
		self._responses.put({"jsonrpc": "2.0", "method": method, "params": params or {}})


class SilentTransport:
	"""Never responds — for timeout test."""

	def __init__(self, spec, *, logger=None):
		self.spec = spec
		self.alive_ = True

	def spawn(self):
		pass

	def send(self, message):
		pass

	def recv(self, timeout=None):
		return None

	def alive(self):
		return self.alive_

	def wait(self, timeout=None):
		return None

	def close(self):
		self.alive_ = False


def _spec(server_id="fs", **kw):
	return McpClientSpec(id=server_id, command="x", **kw)


def _transport_for(spec, **kw):
	return FakeMcpTransport(spec, **kw)


def _client(spec, **kw):
	transport = _transport_for(spec, **kw)
	client = McpStdioClient(spec, transport_factory=lambda spec, logger=None: transport)
	return client, transport


# --------------------------------------------------------------------------- #
# 1) skip-and-log: a bad server must not crash startup
# --------------------------------------------------------------------------- #

def test_bad_server_start_skipped_not_raised(caplog):
	spec = _spec("bad")
	client, transport = _client(spec, spawn_error="cannot exec nope")
	with caplog.at_level(logging.WARNING):
		ok = client.start()
	assert ok is False
	assert client.ready is False
	assert any("failed to start" in r.getMessage() for r in caplog.records)


def test_register_mcp_server_returns_none_for_bad_server(caplog):
	registry = ToolRegistry(cwd=".")
	spec = _spec("bad")
	with caplog.at_level(logging.WARNING):
		runtime = register_mcp_server(
			registry, spec, transport_factory=lambda spec, logger=None: _transport_for(spec, spawn_error="boom")
		)
	assert runtime is None
	assert registry.schemas() == []  # nothing got registered


def test_register_mcp_server_good_server_registers_tools():
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw = {"name": "read", "inputSchema": {"type": "object"}}
	runtime = register_mcp_server(
		registry, spec, transport_factory=lambda spec, logger=None: _transport_for(spec, tools=[raw])
	)
	assert runtime is not None
	assert runtime.tool_names()
	assert registry.get(runtime.tool_names()[0]) is not None


def test_handshake_failure_skipped(caplog):
	# spawn OK but initialize never returns -> startup timeout -> skipped, no raise.
	spec = _spec("hang", startup_timeout_s=0.01, tool_timeout_s=300)
	transport = SilentTransport(spec)
	client = McpStdioClient(spec, transport_factory=lambda spec, logger=None: transport)
	with caplog.at_level(logging.WARNING):
		ok = client.start()
	assert ok is False
	assert client.ready is False


# --------------------------------------------------------------------------- #
# 2) bounded crash-loop: backoff capped + max attempts, no infinite hot loop
# --------------------------------------------------------------------------- #

def test_backoff_sequence_and_cap():
	b = ReconnectBackoff(base=BACKOFF_BASE_S, maximum=BACKOFF_MAX_S, max_attempts=MAX_RECONNECT_ATTEMPTS)
	delays = [b.next_delay() for _ in range(MAX_RECONNECT_ATTEMPTS)]
	# 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0 (capped), then 30.0 ...
	assert delays[0] == BACKOFF_BASE_S
	assert delays[5] == 16.0
	assert delays[6] == BACKOFF_MAX_S  # capped at 30s
	assert all(d <= BACKOFF_MAX_S for d in delays)
	assert b.exhausted() is True


def test_backoff_reset_for_uptime():
	b = ReconnectBackoff(reset_uptime=RESET_UPTIME_S)
	b.next_delay()
	b.next_delay()
	b.next_delay()
	assert b.attempts == 3
	assert b.maybe_reset_for_uptime(RESET_UPTIME_S + 1) is True
	assert b.attempts == 0
	# below the reset threshold -> no reset
	b.next_delay()
	assert b.maybe_reset_for_uptime(RESET_UPTIME_S - 1) is False
	assert b.attempts == 1


def test_crash_loop_bounded_and_exhausts():
	spec = _spec("flaky")
	client, transport = _client(spec)
	client._sleep = lambda d: None
	assert client.start() is True
	assert client.ready is True
	# crash then fail every respawn.
	transport.crash()
	transport.spawn_error = "crash-loop"
	with pytest.raises(McpError) as exc:
		client.call_tool("read", {})
	assert "not connected" in str(exc.value)
	assert transport.spawn_calls == 1 + MAX_RECONNECT_ATTEMPTS  # initial + 10 attempts
	assert client._backoff.attempts == MAX_RECONNECT_ATTEMPTS  # bounded, no infinite loop
	assert client._backoff.exhausted() is True


def test_reconnect_success_after_crash_resets_budget():
	spec = _spec("flaky")
	client, transport = _client(spec, tools=[{"name": "read", "inputSchema": {"type": "object"}}])
	client._sleep = lambda d: None
	assert client.start() is True
	assert client.ready is True
	# Simulate a prior outage that already burned most of the budget.
	client._backoff._attempts = MAX_RECONNECT_ATTEMPTS - 1
	# If the process stayed up > reset_uptime and then died, the budget resets.
	transport.crash()
	client._spawn_time = time.monotonic() - (RESET_UPTIME_S + 5)
	transport.spawn_error = None
	assert client._ensure_running(fetch=False) is True
	assert client.ready is True
	# Reset happened (budget was re-armed), so only one fresh attempt was consumed.
	assert client._backoff.attempts == 1
	# A short-lived crash-loop must NOT get a fresh budget -> continues accumulating.
	client._backoff._attempts = MAX_RECONNECT_ATTEMPTS - 1
	transport.crash()
	client._spawn_time = time.monotonic() - 1.0  # short uptime
	transport.spawn_error = "crash"
	assert client._ensure_running(fetch=False) is False
	assert client._backoff.exhausted() is True


# --------------------------------------------------------------------------- #
# 3) no name collapse: two servers / colliding raws get distinct tool names
# --------------------------------------------------------------------------- #

def test_mcp_tool_name_shape_and_12hex():
	name = mcp_tool_name("fs", "read_file")
	assert name.startswith("mcp__fs__read_file__")
	suffix = name.rsplit("__", 1)[-1]
	assert len(suffix) == 12
	assert all(c in "0123456789abcdef" for c in suffix)


def test_two_servers_same_raw_name_not_collapsed():
	a = mcp_tool_name("serverA", "read_file")
	b = mcp_tool_name("serverB", "read_file")
	assert a != b
	assert "serverA" in a and "serverB" in b


def test_normalized_collision_still_unique():
	# "Read_File" and "read file" both normalize to "read_file" but never collide
	# (the 12-hex tag is keyed on the raw name).
	a = mcp_tool_name("fs", "Read_File")
	b = mcp_tool_name("fs", "read file")
	assert normalize_raw_tool_name("Read_File") == normalize_raw_tool_name("read file")
	assert a != b


def test_two_servers_registered_distinct_names_in_registry():
	registry = ToolRegistry(cwd=".")
	spec_a = _spec("serverA")
	spec_b = _spec("serverB")
	raw = {"name": "read_file", "inputSchema": {"type": "object", "properties": {}}}
	rt_a = McpServerRuntime(spec_a, registry=registry, transport_factory=lambda spec, logger=None: _transport_for(spec, tools=[raw]))
	rt_b = McpServerRuntime(spec_b, registry=registry, transport_factory=lambda spec, logger=None: _transport_for(spec, tools=[raw]))
	assert rt_a.start() is True
	assert rt_b.start() is True
	na = rt_a.tool_names()[0]
	nb = rt_b.tool_names()[0]
	assert na != nb
	assert registry.get(na) is not None
	assert registry.get(nb) is not None
	assert na != nb and len({na, nb}) == 2


# --------------------------------------------------------------------------- #
# 4) permission 3-way gate: default outbound_ask, never bypassed
# --------------------------------------------------------------------------- #

def test_default_policy_is_outbound_ask():
	assert mcp_default_policy() == "outbound_ask"
	spec = _spec("fs")
	assert resolve_mcp_policy(spec, "read_file") == "outbound_ask"


def test_always_allow_only_when_explicitly_declared():
	spec = _spec("fs")
	assert resolve_mcp_policy(spec, "read_file") == "outbound_ask"
	spec_allow = _spec("fs", tools_policy="always_allow")
	assert resolve_mcp_policy(spec_allow, "read_file") == "always_allow"
	# per-tool override beats server policy
	spec_mixed = _spec("fs", tools_policy="outbound_ask", tool_policies={"read_file": "always_allow"})
	assert resolve_mcp_policy(spec_mixed, "read_file") == "always_allow"
	assert resolve_mcp_policy(spec_mixed, "other") == "outbound_ask"


def test_policy_decision_three_way():
	assert mcp_policy_decision("mcp__fs__x__abc", "outbound_ask").decision == PermissionDecision.ASK
	assert mcp_policy_decision("mcp__fs__x__abc", "outbound_ask").matched_rule == "mcp_outbound_ask"
	assert mcp_policy_decision("mcp__fs__x__abc", "always_allow").decision == PermissionDecision.ALLOW
	assert mcp_policy_decision("mcp__fs__x__abc", "ui_ask").decision == PermissionDecision.ASK
	assert mcp_policy_decision("mcp__fs__x__abc", "ui_ask").matched_rule == "mcp_ui_ask"


def test_dynamic_tool_goes_through_registry_gate_as_ask():
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw = {"name": "read_file", "inputSchema": {"type": "object", "properties": {}}}
	tool = McpTool(None, spec, server_id="fs", raw_name="read_file", tool_name=mcp_tool_name("fs", "read_file"), raw_schema=raw, policy=resolve_mcp_policy(spec, "read_file"))
	registry.register(tool)
	tool_use = ToolUse(id="1", name=tool.name, input={})
	result = _run_registry(registry, tool_use)
	# ASK + no coordinator -> the gate refuses to execute (no resolver), so it never
	# reaches McpTool.execute. This is the hard-rule enforcement: dynamic tools never
	# bypass the 3-way gate.
	assert result.is_error is True
	assert result.metadata.get("permission_reason") is not None
	assert "no resolver" in result.content


def test_skip_ask_executes_via_gate_escape_hatch():
	# skip_ask=True is the explicit scaffold/test escape hatch: the gate still runs,
	# but once ALLOWed it executes the tool (here through a real client+fake transport).
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw = {"name": "read_file", "inputSchema": {"type": "object", "properties": {}}}
	client, transport = _client(spec, tools=[raw])
	assert client.start() is True
	tool = McpTool(client, spec, server_id="fs", raw_name="read_file", tool_name=mcp_tool_name("fs", "read_file"), raw_schema=raw, policy=resolve_mcp_policy(spec, "read_file"))
	registry.register(tool)
	tool_use = ToolUse(id="2", name=tool.name, input={})
	result = _run_registry(registry, tool_use, skip_ask=True)
	assert result.is_error is False
	assert "ok" in result.content


def _run_registry(registry, tool_use, *, skip_ask=False):
	import asyncio

	async def _run():
		return await registry.run(tool_use, AbortController(), skip_ask=skip_ask)

	return asyncio.run(_run())


def test_mcp_tool_execute_fails_closed_when_disconnected():
	# A bad server that exhausts its reconnect budget: the tool returns an error
	# result (fail closed) instead of raising through the tool loop.
	spec = _spec("down")
	client = McpStdioClient(
		spec,
		transport_factory=lambda spec, logger=None: _transport_for(spec, spawn_error="down"),
		sleep=lambda d: None,  # no real backoff sleep in tests
	)
	tool = McpTool(
		client, spec, server_id="down", raw_name="read",
		tool_name=mcp_tool_name("down", "read"),
		raw_schema={"name": "read", "inputSchema": {"type": "object"}},
		policy="outbound_ask",
	)
	result = _run_tool(tool, {})
	assert result.is_error is True
	assert "error" in result.content


def _run_tool(tool, input):
	import asyncio

	async def _run():
		return await tool.execute(input, AbortController())

	return asyncio.run(_run())


# --------------------------------------------------------------------------- #
# Timeout split (30s startup / 300s tool) hoisted + applied
# --------------------------------------------------------------------------- #

def test_timeout_constants_hoisted():
	assert STARTUP_TIMEOUT_S == 30.0
	assert TOOL_TIMEOUT_S == 300.0
	assert BACKOFF_BASE_S == 0.5
	assert BACKOFF_MAX_S == 30.0
	assert MAX_RECONNECT_ATTEMPTS == 10
	assert RESET_UPTIME_S == 30.0


def test_spec_defaults_carry_timeout_split():
	spec = McpClientSpec(id="fs", command="x")
	assert spec.startup_timeout_s == STARTUP_TIMEOUT_S
	assert spec.tool_timeout_s == TOOL_TIMEOUT_S


def test_timeout_split_applied_to_requests():
	spec = _spec("fs")
	raw = {"name": "read", "inputSchema": {"type": "object"}}
	client, transport = _client(spec, tools=[raw])
	timeouts = []
	original = client._request

	def spy(method, params=None, *, timeout=None):
		timeouts.append((method, timeout))
		return original(method, params, timeout=timeout)

	client._request = spy
	assert client.start() is True
	client.call_tool("read", {})
	assert ("initialize", STARTUP_TIMEOUT_S) in timeouts
	assert ("tools/list", STARTUP_TIMEOUT_S) in timeouts  # startup budget for list too
	assert ("tools/call", TOOL_TIMEOUT_S) in timeouts  # per-tool budget


def test_request_times_out_raises():
	spec = _spec("fs")
	transport = SilentTransport(spec)
	client = McpStdioClient(spec, transport_factory=lambda spec, logger=None: transport)
	with pytest.raises(McpTimeoutError):
		client._request("tools/call", {}, timeout=0.001)


def test_sanitize_env_strips_secrets_and_xeyo_then_merges_whitelist(monkeypatch):
	from extension.mcp_client import sanitize_env

	monkeypatch.setenv("XEYO_SECRET", "x")
	monkeypatch.setenv("MONKEY", "kept")  # 'key' substring must NOT be stripped
	monkeypatch.setenv("API_TOKEN", "drop")
	monkeypatch.setenv("PATH", "C:\\bin")
	env = sanitize_env(whitelist={"FS_ALLOW": "ok"})
	assert "XEYO_SECRET" not in env
	assert "API_TOKEN" not in env
	assert "MONKEY" in env  # over-strip guard
	assert "PATH" in env
	assert env.get("FS_ALLOW") == "ok"


# --------------------------------------------------------------------------- #
# Schema sanitize + 5KB tiered degradation
# --------------------------------------------------------------------------- #

def test_schema_sanitize_shapes():
	raw = {
		"name": "read_file",
		"description": "Read a file.",
		"inputSchema": {
			"type": "object",
			"required": ["path"],
			"properties": {"path": {"type": "string", "description": "The path."}},
			"additionalProperties": False,
		},
		"extra": "not allowed",
	}
	schema = sanitize_tool_schema(raw)
	assert schema["name"] == "read_file"
	assert "description" in schema
	assert "input_schema" in schema
	assert "extra" not in schema


def test_schema_degrades_oversized_to_budget():
	props = {}
	for i in range(300):
		props[f"p_{i}"] = {"type": "string", "description": "x" * 500, "default": "y" * 100}
	raw = {"name": "huge", "description": "huge", "inputSchema": {"type": "object", "properties": props}}
	schema = sanitize_tool_schema(raw, budget_bytes=SCHEMA_BUDGET_BYTES)
	assert len(json.dumps(schema["input_schema"])) <= SCHEMA_BUDGET_BYTES
	assert schema["input_schema"]["type"] == "object"


# --------------------------------------------------------------------------- #
# Whole-generation replacement (list_changed) + rollback + HMR hook
# --------------------------------------------------------------------------- #

def test_list_changed_replaces_generation():
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw_a = {"name": "alpha", "inputSchema": {"type": "object"}}
	client, transport = _client(spec, tools=[raw_a])
	rt = McpServerRuntime(spec, registry=registry, client=client)  # reuse client
	assert rt.start() is True
	old_name = rt.tool_names()[0]
	assert registry.get(old_name) is not None
	# server changes its tool list
	raw_b = {"name": "beta", "inputSchema": {"type": "object"}}
	transport.tools = [raw_b]
	gen = rt.on_list_changed()
	assert gen.applied is True
	assert rt.client.generation == 2
	assert "alpha" not in rt.tool_names()[0]
	assert registry.get(old_name) is None  # old generation removed
	assert registry.get(rt.tool_names()[0]) is not None  # new generation registered


def test_list_changed_fetch_failure_keeps_old_generation():
	spec = _spec("fs")
	raw_a = {"name": "alpha", "inputSchema": {"type": "object"}}
	client, transport = _client(spec, tools=[raw_a])
	rt = McpServerRuntime(spec, registry=None, client=client)
	assert rt.start() is True
	old_gen = rt.client.generation
	# make tools/list fail -> fetch error -> keep old generation
	transport.list_error = "tools/list failed"
	gen = rt.on_list_changed()
	assert gen.applied is False
	assert rt.client.generation == old_gen  # old generation preserved


def test_generation_conflict_rolls_back():
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw = {"name": "x", "inputSchema": {"type": "object"}}
	name = mcp_tool_name("fs", "x")
	# pre-own the exact name in the registry (another owner)
	class Dummy:
		name: str = ""

		def schema(self):
			return {"name": self.name}

	Dummy.name = name
	registry.register(Dummy())
	client, transport = _client(spec, tools=[raw])
	rt = McpServerRuntime(spec, registry=registry, client=client)
	assert rt.start() is True
	gen = rt.on_list_changed()
	# The new generation conflicts -> whole generation rolled back, nothing registered.
	assert gen.applied is True  # fetch succeeded
	assert rt.tool_names() == []  # registration rolled back (not applied)


def test_hot_reload_hook_disconnect_reconnect():
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw = {"name": "alpha", "inputSchema": {"type": "object"}}
	client, transport = _client(spec, tools=[raw])
	rt = McpServerRuntime(spec, registry=registry, client=client)
	assert rt.start() is True
	assert registry.get(rt.tool_names()[0]) is not None
	# HMR: disconnect + reconnect.
	assert rt.reload() is True
	assert rt.client.ready is True
	assert rt.tool_names()  # tools re-registered


# --------------------------------------------------------------------------- #
# build_tools + call_tool happy path
# --------------------------------------------------------------------------- #

def test_build_tools_and_call_tool():
	registry = ToolRegistry(cwd=".")
	spec = _spec("fs")
	raw_a = {"name": "alpha", "inputSchema": {"type": "object", "properties": {}}}
	client, transport = _client(spec, tools=[raw_a])
	assert client.start() is True
	gen = McpGeneration(generation=client.generation, tools=client.tool_schemas(), applied=True)
	tools = build_tools(client, gen)
	assert len(tools) == 1
	tool = tools[0]
	assert tool.name == mcp_tool_name("fs", "alpha")
	assert tool.policy == "outbound_ask"
	registry.register(tool)
	tool_use = ToolUse(id="3", name=tool.name, input={})
	result = _run_registry(registry, tool_use, skip_ask=True)
	assert result.is_error is False
	assert "ok" in result.content
