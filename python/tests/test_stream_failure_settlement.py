"""Actual query-loop failure cleanup, usage and interrupted transcript contracts."""
import asyncio

import pytest

from common.errors import NetworkError, ProviderError
from engine.abort import AbortController, Aborted
from engine.budget import BudgetTracker
from engine.model_events import ModelProtocolError
from engine.query_loop import query_loop
from model.chunks import ModelChunk
from msgtypes.events import FinalEvent, StoppedEvent, ToolResultEvent, UsageEvent
from msgtypes.message import ToolUse, user_message
from permissions.policy import set_permission_mode
from prompt.assembler import PromptAssembler
from session.message_store import MessageStore
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


USAGE = {"prompt_tokens": 100, "completion_tokens": 10,
         "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20, "cost_usd": 1.0}


class _Read:
    name = "echo"
    is_read_only = True
    is_concurrency_safe = True

    def __init__(self, complete):
        self.complete = complete
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.task = None

    def schema(self):
        return {"name": "echo", "description": "local read", "input_schema": {"type": "object"}}

    async def execute(self, input, abort):
        self.task = asyncio.current_task()
        self.started.set()
        if not self.complete:
            await asyncio.Event().wait()
        return ToolResult(content="actual read data")


class _Failure:
    last_usage = None

    def __init__(self, error, tool):
        self.error, self.tool, self.calls = error, tool, 0

    async def stream(self, messages, tools, abort):
        self.calls += 1
        yield ModelChunk(kind="reasoning_delta", text="observed reasoning")
        yield ModelChunk(kind="text_delta", text="Partial factual answer.")
        yield ModelChunk(kind="tool_use", tool_use=ToolUse(id="read", name="echo", input={"text": "read"}))
        await asyncio.wait_for(self.tool.started.wait(), 1)
        if self.tool.complete:
            await asyncio.wait_for(self.tool.finished.wait(), 1)
        await asyncio.sleep(0)
        self.last_usage = dict(USAGE)
        if self.error is Aborted:
            abort.abort()
            abort.raise_if_aborted()
        raise self.error("injected failure")


async def _run(model, registry, budget, store, events):
    set_permission_mode("never")
    async for event in query_loop(
        model=model, tools=registry, budget=budget, store=store,
        prompt=PromptAssembler(), system_prompt="test", abort=AbortController(),
    ):
        events.append(event)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [NetworkError, ModelProtocolError, Aborted])
@pytest.mark.parametrize("complete", [False, True])
async def test_failed_stream_recovers_output_usage_and_tools(error, complete, monkeypatch):
    monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "1")
    tool = _Read(complete)
    registry = ToolRegistry()
    registry.register(tool)
    original_run = registry.run

    async def tracked_run(*args, **kwargs):
        result = await original_run(*args, **kwargs)
        tool.finished.set()
        return result

    monkeypatch.setattr(registry, "run", tracked_run)
    model = _Failure(error, tool)
    budget, store, events = BudgetTracker(), MessageStore([user_message("read")]), []
    if error is Aborted:
        await _run(model, registry, budget, store, events)
        assert any(isinstance(e, StoppedEvent) and e.reason == "aborted" for e in events)
    else:
        with pytest.raises(error):
            await _run(model, registry, budget, store, events)
    assert model.calls == 1
    assert tool.task.done()
    assert budget.used_tokens == 110 and budget.used_usd == 1.0
    assert len([e for e in events if isinstance(e, UsageEvent)]) == 1
    anchors = [m for m in store.items if m.role == "assistant"]
    assert len(anchors) == 1 and anchors[0].interrupted
    assert "Partial factual answer." in str(anchors[0].content)
    assert {"type": "reasoning", "text": "observed reasoning"} in anchors[0].content
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(results) == 1 and not results[0].is_error
    if not complete:
        assert results[0].status == 'cancelled'
        stored = next(m for m in store.items if m.role == 'tool')
        assert stored.content[0]['is_error']  # cancelled observation is not success
    if complete:
        assert results[0].output == "actual read data"
    assert len([m for m in store.items if m.tool_call_id == "read"]) == 1
    assert not any(isinstance(e, FinalEvent) for e in events)


class _BilledRetry:
    last_usage = None

    def __init__(self): self.calls = 0

    async def stream(self, messages, tools, abort):
        self.calls += 1
        self.last_usage = dict(USAGE)
        if self.calls == 1:
            raise ProviderError("injected failure", status_code=503)
        yield ModelChunk(kind="text_delta", text="complete")


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,expected_calls,expected_tokens", [(None, 2, 220), (0.5, 1, 110)])
async def test_billed_empty_attempt_counted_once_and_budget_blocks_retry(monkeypatch, limit, expected_calls, expected_tokens):
    monkeypatch.setattr("engine.query_loop._llm_retry_delay_ms", lambda *args: 1)
    model = _BilledRetry()
    budget = BudgetTracker(usd_limit=limit)
    store, events = MessageStore([user_message("answer")]), []
    await _run(model, ToolRegistry(), budget, store, events)
    assert model.calls == expected_calls
    assert budget.used_tokens == expected_tokens
    assert len([e for e in events if isinstance(e, UsageEvent)]) == expected_calls
    assert len([m for m in store.items if m.role == "assistant"]) == (0 if limit else 1)
    if limit:
        assert any(isinstance(e, StoppedEvent) and e.reason == "budget_usd" for e in events)
