"""Offline A/B contracts for the five Agent runtime repairs (no vendor calls)."""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from engine.abort import AbortController
from extension.mcp_client import McpClientSpec, McpStdioClient, McpTimeoutError, McpTool
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.orchestration import _run_one_tool
from tools.tool_registry import ToolRegistry


class Transport:
    def __init__(self, mode="normal"):
        self.mode = mode
        self.live = False
        self.responses = queue.Queue()
        self.sent = []
        self.effects = 0
        self.timer = None
        self.senders = {}
        self.b_sent = threading.Event()
        self.b_consumed = threading.Event()
        self.a_consumed = threading.Event()

    def spawn(self): self.live = True
    def alive(self): return self.live
    def close(self): self.live = False
    def wait(self, timeout=None): return None

    def send(self, request):
        self.sent.append(request)
        if "id" not in request:
            return
        method, rid = request["method"], request["id"]
        result = {"protocolVersion": "2024-11-05"} if method == "initialize" else {"tools": []}
        if method == "tools/call":
            name = request["params"]["name"]
            result = {"content": [{"type": "text", "text": name}]}
            if self.mode == "notification":
                self.responses.put({"method": "notifications/tools/list_changed"})
            if self.mode == "reversed":
                self.senders[threading.get_ident()] = name
                if name == "A":
                    self.a_id = rid
                    return
                self.responses.put({"id": rid, "result": result})
                self.responses.put({"id": self.a_id, "result": {"content": [{"type": "text", "text": "A"}]}})
                self.b_sent.set()
                return
            if self.mode == "delayed":
                def finish():
                    self.effects += 1
                    self.responses.put({"id": rid, "result": result})
                self.timer = threading.Timer(.3, finish)
                self.timer.start()
                return
        self.responses.put({"id": rid, "result": result})

    def recv(self, timeout=None):
        who = self.senders.get(threading.get_ident())
        if self.mode == "reversed" and who:
            if who == "A" and not self.b_consumed.is_set():
                self.b_sent.wait(.5)
                item = self.responses.get(timeout=.5)
                self.b_consumed.set()
                return item
            if who == "B" and not self.a_consumed.is_set():
                self.b_consumed.wait(.5)
                item = self.responses.get(timeout=.1)
                self.a_consumed.set()
                return item
            self.a_consumed.wait(.5)
        try:
            return self.responses.get(timeout=timeout or .02)
        except queue.Empty:
            return None


def client_for(monkeypatch, enabled, mode):
    monkeypatch.setenv("XEYO_MCP_ROUTER", str(int(enabled)))
    transport = Transport(mode)
    spec = McpClientSpec(id="test", command="unused", startup_timeout_s=.08, tool_timeout_s=.08)
    client = McpStdioClient(spec, transport_factory=lambda *a, **k: transport)
    assert client.start()
    return client, transport


@pytest.mark.parametrize("enabled", [False, True])
def test_mcp_notification_during_request_ab(monkeypatch, enabled):
    client, transport = client_for(monkeypatch, enabled, "notification")
    try:
        if enabled:
            assert client.call_tool("A").content == "A"
        else:
            with pytest.raises(McpTimeoutError):
                client.call_tool("A")
    finally:
        client.stop()


@pytest.mark.parametrize("enabled", [False, True])
def test_mcp_concurrent_reversed_replies_ab(monkeypatch, enabled):
    client, transport = client_for(monkeypatch, enabled, "reversed")
    def call(name):
        try:
            return client.call_tool(name).content
        except McpTimeoutError:
            return "timeout"
    try:
        with ThreadPoolExecutor(2) as executor:
            a = executor.submit(call, "A")
            deadline = time.monotonic() + 1
            while not hasattr(transport, "a_id") and time.monotonic() < deadline:
                time.sleep(.001)
            b = executor.submit(call, "B")
            assert [a.result(2), b.result(2)] == (["A", "B"] if enabled else ["timeout", "timeout"])
    finally:
        client.stop()


def test_mcp_timeout_cancel_late_reply_and_restart(monkeypatch):
    client, transport = client_for(monkeypatch, True, "delayed")
    try:
        with pytest.raises(McpTimeoutError):
            client.call_tool("A", timeout=.01)
        cancelled = [r for r in transport.sent if r.get("method") == "notifications/cancelled"]
        assert len(cancelled) == 1 and cancelled[0]["params"]["requestId"] == 3
        transport.timer.join(1)
        transport.mode = "normal"
        assert client.call_tool("B").content == "B"
        assert client.reconnect()
        assert client.call_tool("C").content == "C"
    finally:
        client.stop()


class PreapprovedRegistry(ToolRegistry):
    async def run(self, tu, abort, **kwargs):
        return await self._execute_audited(self.get(tu.name), tu, abort, session_id="repair", turn_id="turn")


def mcp_tool(client):
    from extension.mcp_client import build_tools
    from extension.mcp_client import McpGeneration, mcp_tool_name
    name = mcp_tool_name("test", "write")
    gen = McpGeneration(1, {name: {"name": "write", "inputSchema": {"type": "object"}}})
    return build_tools(client, gen)[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_outer_timeout_preserves_unknown_and_identity_ab(monkeypatch, enabled):
    monkeypatch.setenv("XEYO_TOOL_OUTCOME_CONTRACT", str(int(enabled)))
    monkeypatch.setenv("XEYO_ACTION_JOURNAL", "1")
    monkeypatch.setenv("XEYO_TOOL_TIMEOUT_S", ".06")
    client, transport = client_for(monkeypatch, True, "delayed")
    tool = mcp_tool(client)
    registry = PreapprovedRegistry()
    registry.register(tool)
    try:
        result = await _run_one_tool(registry, ToolUse(id="a", name=tool.name, input={}), AbortController(), None)
        assert result.status == ("unknown" if enabled else "error")
        assert result.retryable is (not enabled)
        assert bool(result.action_id) is enabled
        assert result.execution_metadata()["complete"] is (not enabled)
        for _ in range(50):
            if transport.timer is not None:
                break
            await asyncio.sleep(.01)
        await asyncio.to_thread(transport.timer.join, 1)
        assert transport.effects == 1  # timeout never proved remote cancellation
    finally:
        client.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_inner_timeout_does_not_repeat_unresolved_operation_ab(monkeypatch, enabled):
    monkeypatch.setenv("XEYO_TOOL_OUTCOME_CONTRACT", str(int(enabled)))
    monkeypatch.setenv("XEYO_ACTION_JOURNAL", "1")
    monkeypatch.setenv("XEYO_TOOL_TIMEOUT_S", "1")
    client, transport = client_for(monkeypatch, True, "delayed")
    from dataclasses import replace
    client.spec = replace(client.spec, tool_timeout_s=.01)
    tool = mcp_tool(client)
    registry = PreapprovedRegistry()
    registry.register(tool)
    try:
        one = await _run_one_tool(registry, ToolUse(id="a", name=tool.name, input={}), AbortController(), None)
        timer1 = transport.timer
        two = await _run_one_tool(registry, ToolUse(id="b", name=tool.name, input={}), AbortController(), None)
        await asyncio.to_thread(timer1.join, 1)
        await asyncio.to_thread(transport.timer.join, 1)
        assert transport.effects == (1 if enabled else 2)
        if enabled:
            assert one.status == two.status == "unknown"
            assert one.action_id == two.action_id
            from engine.action_journal import ActionJournal
            assert ActionJournal("repair").summary()["counts"]["unknown"] == 1
    finally:
        client.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_parent_child_followup_budget_ab(monkeypatch, enabled):
    from engine.budget import BudgetTracker
    from engine.shared_budget import task_budget_scope, current_budget
    monkeypatch.setenv("XEYO_SHARED_AGENT_BUDGET", str(int(enabled)))
    monkeypatch.setattr(BudgetTracker, "_usage_cny", lambda *a, **k: None)
    parent = BudgetTracker(usd_limit=.5, max_tokens=100)
    children = []
    @task_budget_scope
    async def root(*, budget):
        budget.add_usage({"total_tokens": 10, "usd": .1})
        async def child():
            first = BudgetTracker()
            first.add_usage({"total_tokens": 40, "usd": .2})
            followup = BudgetTracker()
            followup.add_usage({"total_tokens": 50, "usd": .2})
            children.extend([first, followup])
        await asyncio.create_task(child())
        yield "done"
    assert [event async for event in root(budget=parent)] == ["done"]
    assert parent.over_budget is enabled
    assert parent.over_token_budget() is enabled
    assert all(child.over_budget is enabled for child in children)
    assert current_budget.get() is None
    assert parent.used_usd == .1  # own usage remains distinct, no double count
    if enabled:
        assert parent.total_used_usd == .5
    parent.reset_for_new_submit(usd_limit=.5)
    assert not parent.over_budget


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_child_model_identity_ab(monkeypatch, tmp_path, enabled):
    from engine.subagent_runner import run_subagent, SubagentRunResult
    monkeypatch.setenv("XEYO_SUBAGENT_RESULT_CONTRACT", str(int(enabled)))
    received = {}
    async def body(**kwargs):
        received.update(kwargs)
        return SubagentRunResult()
    monkeypatch.setattr("engine.subagent_runner._run_subagent_body", body)
    client = SimpleNamespace(provider="anthropic", _model="claude-sonnet-4-5", last_usage={})
    await run_subagent(workspace_root=tmp_path, agent_id="child", task_prompt="task", tool_whitelist=[],
                       model_client=client, prompt_assembler=object(), write_store=None, main_session_id="parent")
    assert received["provider"] == ("anthropic" if enabled else "deepseek")
    assert received["model"] == ("claude-sonnet-4-5" if enabled else "deepseek-v4-flash")
    assert (received["model_client"] is client) is (not enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_child_adapter_usage_ab(monkeypatch, tmp_path, enabled):
    from engine.subagent_runner import SubagentRunResult
    from tools.agent_tool.agent_tool import AgentTool, AgentInput
    monkeypatch.setenv("XEYO_SUBAGENT_RESULT_CONTRACT", str(int(enabled)))
    async def body(**kwargs):
        return SubagentRunResult(tokens_used=1234, cost_cny=1.25, cost_partial=True, stop_reason="budget_usd")
    monkeypatch.setattr("engine.subagent_runner.run_subagent", body)
    runtime = SimpleNamespace(model_client=object(), prompt_assembler=object(), date_iso="2026-10-15")
    tool = AgentTool(cwd=str(tmp_path), session_id="parent")
    out = await tool._run_child(AgentInput(task_id="t", desc="test"), agent_id="a", runtime=runtime,
                                tool_whitelist=[], abort=AbortController(), append_prompt="", on_text_delta=None,
                                workspace_root=tmp_path, write_store=None)
    assert out.tokens_used == (1234 if enabled else 0)
    assert out.cost_cny == (1.25 if enabled else None)
    assert out.cost_partial is enabled
    assert out.stop_reason == ("budget_usd" if enabled else "")


@pytest.mark.parametrize("enabled", [False, True])
def test_stale_interrupt_ab(monkeypatch, tmp_path, enabled):
    from engine.turn_runner import TurnRunner, _DetachedTurn
    from server.session_pool import SessionPool
    from server.inbox_registry import InboxRegistry
    from server.routers import control
    from fastapi import HTTPException
    monkeypatch.setenv("XEYO_TURN_BOUND_CONTROL", str(int(enabled)))
    pool = SessionPool(cwd=str(tmp_path))
    lease = pool.try_begin("s")
    stopped = []
    pool._engines["s"] = (None, SimpleNamespace(interrupt=lambda: stopped.append("B")))
    runner = TurnRunner(pool)
    runner._turns["s"] = _DetachedTurn("s", "B", lease, "fake", "", "")
    registry = InboxRegistry()
    monkeypatch.setattr(control, "_pool", pool)
    monkeypatch.setattr(control, "require_loopback", lambda r: None)
    monkeypatch.setattr("engine.turn_runner.get_turn_runner", lambda: runner)
    monkeypatch.setattr("server.inbox_registry.get_inbox_registry", lambda: registry)
    request = control.InterruptRequest(session_id="s", expected_turn_id="A")
    if enabled:
        with pytest.raises(HTTPException) as exc:
            control.interrupt(request, None)
        assert exc.value.status_code == 409
        assert not stopped and "s" not in registry._paused
        assert control.interrupt(control.InterruptRequest(session_id="s", expected_turn_id="B"), None)["ok"]
    else:
        assert control.interrupt(request, None)["ok"]
    assert stopped == ["B"]


def test_stale_steer_has_no_queue_side_effect(monkeypatch):
    from engine.turn_runner import TurnRunner, _DetachedTurn
    from server.inbox_registry import InboxRegistry
    from server.turn_control import submit_to_turn, TurnMismatch
    from engine import t_now_steer
    registry = InboxRegistry()
    runner = TurnRunner(None)
    runner._turns["steer"] = _DetachedTurn("steer", "B", 1, "fake", "", "")
    monkeypatch.setattr("engine.turn_runner.get_turn_runner", lambda: runner)
    with pytest.raises(TurnMismatch):
        submit_to_turn(registry, "steer", "for A", media_refs=[], message_id="m", expected_turn_id="A")
    assert not registry._inflight and t_now_steer.pending_count("steer") == 0
    item, admitted = submit_to_turn(registry, "steer", "for B", media_refs=[], message_id="m", expected_turn_id="B")
    assert admitted and item.message_id == "m"
    t_now_steer.clear("steer")


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_real_loop_stops_after_child_spending_ab(monkeypatch, tmp_path, enabled):
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from model.chunks import ModelChunk
    from msgtypes.message import user_message
    from msgtypes.events import StoppedEvent
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from permissions.policy import PolicyDecision
    from permissions.filesystem import PermissionDecision
    monkeypatch.setenv("XEYO_SHARED_AGENT_BUDGET", str(int(enabled)))
    monkeypatch.setattr(BudgetTracker, "_usage_cny", lambda *a, **k: None)
    monkeypatch.setattr("tools.tool_registry.evaluate_policy", lambda *a, **k: PolicyDecision(PermissionDecision.ALLOW, "test"))
    class Spend:
        name = "Spend"
        def schema(self): return {"name": self.name, "description": "test", "input_schema": {"type": "object"}}
        def is_read_only(self): return True
        def is_concurrency_safe(self): return True
        async def execute(self, data, abort):
            child = BudgetTracker()
            child.add_usage({"total_tokens": 100, "usd": .6})
            return ToolResult("child result")
    class Model:
        calls = 0
        last_usage = None
        async def stream(self, *args):
            self.calls += 1
            if self.calls == 1:
                yield ModelChunk(kind="tool_use", tool_use=ToolUse(id="spend", name="Spend", input={}))
            else:
                yield ModelChunk(kind="text_delta", text="done")
    model = Model()
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(Spend())
    budget = BudgetTracker(usd_limit=.5)
    store = MessageStore(initial=[user_message("test")])
    events = [ev async for ev in query_loop(store=store, model=model, tools=registry,
              prompt=PromptAssembler(), system_prompt="", abort=AbortController(), budget=budget)]
    assert model.calls == (1 if enabled else 2)
    if enabled:
        stopped = next(e for e in events if isinstance(e, StoppedEvent))
        assert stopped.reason == "budget_usd" and stopped.budget_used_usd == .6
        assert stopped.budget_limit_usd == .5
        from model._openai_common import normalize_messages_for_openai
        wire = normalize_messages_for_openai(store.as_api_messages(), provider="deepseek", model="test")
        calls = {c["id"] for m in wire for c in m.get("tool_calls", [])}
        results = {m["tool_call_id"] for m in wire if m.get("role") == "tool"}
        assert calls <= results


def test_mcp_abort_wakes_request_and_close_fails_pending(monkeypatch):
    from extension.mcp_client import McpProtocolError
    client, transport = client_for(monkeypatch, True, "delayed")
    abort = AbortController()
    try:
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(client.call_tool, "A", timeout=2, abort=abort)
            deadline = time.monotonic() + 1
            while transport.timer is None and time.monotonic() < deadline:
                time.sleep(.001)
            abort.abort()
            with pytest.raises(McpProtocolError):
                future.result(1)
            transport.timer.join(1)
            transport.timer = None
            future = executor.submit(client.call_tool, "B", timeout=2)
            deadline = time.monotonic() + 1
            while transport.timer is None and time.monotonic() < deadline:
                time.sleep(.001)
            client.stop()
            with pytest.raises(McpProtocolError):
                future.result(1)
            transport.timer.join(1)
    finally:
        client.stop()


def test_action_unknown_survives_reopen_but_completed_identical_is_repeatable(tmp_path):
    from engine.action_journal import ActionJournal
    def begin(journal, aid, key):
        return journal.begin(action_id=aid, idempotency_key=aid, turn_id="next", tool_use_id=aid,
                             tool_name="external", side_effect="external", operation_key=key)
    journal = ActionJournal("s", enabled=True, sessions_dir=tmp_path)
    assert begin(journal, "a", "op-a").action == "execute"
    journal.unknown("a", "disconnect")
    reopened = ActionJournal("s", enabled=True, sessions_dir=tmp_path)
    assert begin(reopened, "b", "op-a").action == "recovery_required"
    assert begin(reopened, "c", "op-b").action == "execute"
    reopened.complete("c", ToolResult("ok"))
    assert begin(reopened, "d", "op-b").action == "execute"


def test_cli_stream_identity_is_carried_into_interrupt():
    from cli.attach_cmd import iter_sse_objects
    from cli.http_api import interrupt_http
    state = {}
    list(iter_sse_objects(iter(['data: {"xy":{"type":"turn_started","turn_id":"A"}}\n\n']), end_state=state))
    posted = []
    class Client:
        def post(self, path, json):
            import httpx
            posted.append(json)
            return httpx.Response(200, json={"ok": True})
    interrupt_http(Client(), "s", expected_turn_id=state["turn_id"])
    assert posted == [{"session_id": "s", "expected_turn_id": "A"}]


@pytest.mark.asyncio
async def test_cooperative_abort_of_side_effect_keeps_unknown_receipt(monkeypatch):
    from engine.abort import Aborted
    from engine.action_journal import ActionJournal
    monkeypatch.setenv("XEYO_TOOL_OUTCOME_CONTRACT", "1")
    monkeypatch.setenv("XEYO_ACTION_JOURNAL", "1")
    class External:
        name = "external"
        def is_read_only(self): return False
        def schema(self): return {"name": self.name, "input_schema": {"type": "object"}}
        async def execute(self, data, abort):
            raise Aborted("connection interrupted")
    registry = PreapprovedRegistry()
    registry.register(External())
    result = await _run_one_tool(registry, ToolUse(id="abort", name="external", input={}), AbortController(), None)
    assert result.status == "unknown" and result.action_id
    assert result.side_effect == "external" and not result.retryable
    assert ActionJournal("repair").summary()["counts"]["unknown"] == 1
