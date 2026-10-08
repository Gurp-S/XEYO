"""Full request admission and failed notification delivery through the engine."""
from copy import deepcopy
import importlib

import pytest

from common.errors import ProviderError
from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from memory.working import WorkingSnapshot
from model.chunks import ModelChunk
from msgtypes.message import Message, user_message
from prompt.assembler import PromptAssembler
from session.message_store import MessageStore
from tools.tool_registry import ToolRegistry


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    monkeypatch.setenv("XEYO_WSC", "0")
    monkeypatch.setattr("engine.first_sniff.maybe_first_sniff_text", lambda *a, **k: "")
    monkeypatch.setattr("prompt.t_now_strategy.resolve_t_now_strategy", lambda *a, **k: "system_channel")
    # Controlled runtime facts; the actual engine notice renderer and
    # provider-error retry paths remain in use.
    monkeypatch.setattr(importlib.import_module("engine.query_loop"), "_attach_turn_context", lambda rows, **kw: rows)


async def drive(store, model, registry, working):
    return [event async for event in query_loop(store=store, model=model, tools=registry,
        prompt=PromptAssembler(), system_prompt="test", abort=AbortController(),
        budget=BudgetTracker(max_turns=3), working=working)]


@pytest.mark.asyncio
async def test_final_schema_pressure_compacts_before_first_send(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    rows = [user_message("current task " + "a" * 14_000)]
    for index in range(12):
        rows.extend([Message(role="assistant", content=f"observation {index}"), user_message(f"detail {index}")])
    working = WorkingSnapshot(session_id="full-capacity")
    registry = ToolRegistry()
    class LargeSchema:
        name = "FactProbe"
        def schema(self):
            return {"name": self.name, "description": "x" * 21_000,
                    "input_schema": {"type": "object", "properties": {}}}
    registry.register(LargeSchema())
    class Model:
        context_limit = 10_000
        last_usage = {}
        requests = []
        async def stream(self, messages, tools, abort):
            self.requests.append(deepcopy(messages))
            assert working.compact_cursor > 0
            admission = working.wsc_timing_state["last_request_admission"]
            assert admission["before"]["timing_action"] == "capacity"
            assert admission["after"]["timing_action"] == "keep"
            assert admission["automatic_attempts"] == 1
            assert working.last_projection_manifest["compact_cursor"] == working.compact_cursor
            yield ModelChunk(kind="text_delta", text="continued")
    model = Model()
    await drive(MessageStore(rows), model, registry, working)
    assert len(model.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 500])
async def test_failed_attempt_does_not_consume_capacity_notice_and_retry_is_remeasured(monkeypatch, tmp_path, status):
    setup(monkeypatch, tmp_path)
    from prompt.t_now_strategy import reset_system_unsupported_for_test
    reset_system_unsupported_for_test()
    working = WorkingSnapshot(session_id=f"notice-retry-{status}")
    class Model:
        context_limit = 10_000
        last_usage = {}
        _provider = "timing-test"
        _model = f"timing-retry-{status}"
        requests = []
        async def stream(self, messages, tools, abort):
            self.requests.append(deepcopy(messages))
            assert "上下文已达80%" in str(messages)
            assert "notification_delivered" not in working.wsc_timing_state
            assert working.last_projection_manifest["messages_kept"] == len(messages)
            if len(self.requests) == 1:
                raise ProviderError("test provider failure", status_code=status)
            yield ModelChunk(kind="text_delta", text="continued")
    model = Model()
    try:
        await drive(MessageStore([user_message("a" * 32_000)]), model, ToolRegistry(), working)
        assert len(model.requests) == 2
        assert working.wsc_timing_state["notification_delivered"] == [0, 10_000]
        if status == 400:
            assert any(row.get("role") == "system" and "上下文已达80%" in str(row) for row in model.requests[0])
            assert any(row.get("role") == "user" and "上下文已达80%" in str(row) for row in model.requests[1])
    finally:
        reset_system_unsupported_for_test()
