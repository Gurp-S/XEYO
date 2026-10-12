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


async def drive(store, model, registry, working, persist=None):
    return [event async for event in query_loop(store=store, model=model, tools=registry,
        prompt=PromptAssembler(), system_prompt="test", abort=AbortController(),
        budget=BudgetTracker(max_turns=3), working=working, persist_handoff=persist)]


@pytest.mark.asyncio
async def test_final_schema_pressure_compacts_before_first_send(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    rows = [user_message("current task " + "a" * 14_000)]
    rows.append(Message(role="user", id="spec", content="Current task: continue the recorded observations."))
    for index in range(12):
        rows.extend([Message(role="assistant", content=f"observation {index}"), user_message(f"detail {index}")])
    working = WorkingSnapshot(session_id="full-capacity")
    registry = ToolRegistry()
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from msgtypes.message import ToolUse
    from session.record_transcript import record_transcript_sync
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
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
        def for_handoff(self, max_tokens):
            class Handoff:
                last_usage = {}
                async def stream(self, messages, tools, abort):
                    from tests.wsc._fixtures import declared_report_phase
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("schema-handoff", "TodoWrite", {
                        "todos": [{"id": "continue", "content": "continue observations", "status": "pending", "activeForm": "continuing"}],
                        "checkpoint": {"objective": "continue observations", "context_message_ids": ["spec"],
                                       "phase_state": declared_report_phase("spec")}}))
            return Handoff()
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
    store = MessageStore(rows)
    known = set()
    events = await drive(store, model, registry, working, persist=lambda: record_transcript_sync(store.items,
        session_id=working.session_id, path=tmp_path / "transcript.jsonl", known_ids=known))
    assert len(model.requests) == 1, [getattr(event, "reason", "") for event in events]


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


@pytest.mark.asyncio
@pytest.mark.parametrize('strategy', ['system_channel', 'env_channel'])
async def test_rebuilt_retry_handoff_failure_stops_without_second_send(monkeypatch, tmp_path, strategy):
    setup(monkeypatch, tmp_path)
    status = 400
    monkeypatch.setattr('prompt.t_now_strategy.resolve_t_now_strategy', lambda *a, **k: strategy)
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    from evals.wsc_task_continuity_ab import task_event
    from session.hydrate import messages_from_rows
    from prompt.t_now_strategy import reset_system_unsupported_for_test
    reset_system_unsupported_for_test()
    rows = [{'role': 'user', 'id': 'spec', 'content': 'Current specification ' + 'a' * 62000}]
    rows += task_event('committed', [{'id': 'report', 'content': 'write report', 'status': 'pending', 'activeForm': 'writing'}],
                       {'objective': 'write report', 'context_message_ids': ['spec']})
    # An actual post-checkpoint task update requires a fresh handoff on retry;
    # a correctly restored complete checkpoint alone does not.
    rows.append({'role': 'user', 'id': 'new-detail', 'content': 'Include the latest observation in the report.'})
    store = MessageStore(messages_from_rows(rows))
    original = deepcopy(store.items)
    working = WorkingSnapshot(session_id=f'retry-hard-cap-{strategy}')
    class Model:
        context_limit = 20000
        last_usage = {}
        _provider = 'timing-test'
        _model = f'hard-cap-{strategy}'
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            self.context_limit = 1000
            raise ProviderError('test provider failure', status_code=status)
            yield
    model = Model()
    try:
        events = await drive(store, model, ToolRegistry(), working)
        assert model.calls == 1
        assert any(getattr(event, 'reason', '') == 'handoff_commit_unavailable' for event in events), [getattr(e, 'reason', '') for e in events]
        assert store.items[:len(original)] == original
        assert 'notification_delivered' not in working.wsc_timing_state
    finally:
        reset_system_unsupported_for_test()
