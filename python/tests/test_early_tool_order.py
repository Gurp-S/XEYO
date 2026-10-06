"""Early reads may overlap model streaming, not overtake ordered mutations."""
import asyncio

import pytest

from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import ToolResultEvent
from msgtypes.message import ToolUse
from permissions.policy import set_permission_mode
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("order, expected", [
    (["Write", "Read"], ["after"]),
    (["Read", "Write"], ["before"]),
    (["Read", "Write", "Read"], ["before", "after"]),
])
async def test_engine_preserves_read_write_order(tmp_path, monkeypatch, order, expected):
    monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "1")
    path = tmp_path / "state.txt"
    path.write_text("before", encoding="utf-8")
    class Read:
        name = "Read"
        is_read_only = staticmethod(lambda: True)
        is_concurrency_safe = staticmethod(lambda: True)
        def schema(self):
            return {"name": self.name, "description": "File observation.", "input_schema": {"type": "object", "properties": {}}}
        async def execute(self, input, abort):
            await asyncio.sleep(.8 if order[0] == "Read" else .08)
            return ToolResult(path.read_text(encoding="utf-8"))
    class Write(Read):
        name = "Write"
        is_read_only = staticmethod(lambda: False)
        is_concurrency_safe = staticmethod(lambda: False)
        async def execute(self, input, abort):
            path.write_text("after", encoding="utf-8")
            return ToolResult("written")
    class Model:
        last_usage = None
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            if self.calls == 1:
                for index, name in enumerate(order):
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"tool-{index}", name, {"file_path": str(path)}))
                await asyncio.sleep(.02)
            else:
                yield ModelChunk(kind="text_delta", text="finished")
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(Read())
    registry.register(Write())
    set_permission_mode("never")
    model = Model()
    engine = QueryEngine({"cwd": str(tmp_path), "tools": registry, "model_client": model,
                          "provider": "deepseek", "model": "deepseek-v4-flash", "max_turns": 10})
    events = [event async for event in engine.submit("Perform the operations in the given order.")]
    observations = [event.output for event in events if isinstance(event, ToolResultEvent) and event.name == "Read"]
    assert observations == expected
    assert path.read_text() == "after"
    assert model.calls == 2


@pytest.mark.asyncio
async def test_early_read_pool_honors_existing_concurrency_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "1")
    monkeypatch.setenv("XEYO_MAX_TOOL_USE_CONCURRENCY", "2")
    path = tmp_path / "state.txt"
    path.write_text("payload", encoding="utf-8")
    active = 0
    peak = 0
    class Read:
        name = "Read"
        is_read_only = staticmethod(lambda: True)
        is_concurrency_safe = staticmethod(lambda: True)
        def schema(self):
            return {"name": self.name, "description": "File observation.", "input_schema": {"type": "object", "properties": {}}}
        async def execute(self, input, abort):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.04)
                return ToolResult(path.read_text(encoding="utf-8"))
            finally:
                active -= 1
    class Model:
        last_usage = None
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            if self.calls == 1:
                for index in range(4):
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"read-{index}", "Read", {"file_path": str(path)}))
                await asyncio.sleep(.06)
            else:
                yield ModelChunk(kind="text_delta", text="finished")
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(Read())
    set_permission_mode("never")
    model = Model()
    engine = QueryEngine({"cwd": str(tmp_path), "tools": registry, "model_client": model,
                          "provider": "deepseek", "model": "deepseek-v4-flash", "max_turns": 10})
    events = [event async for event in engine.submit("Read the observations.")]
    assert peak == 2
    assert len([event for event in events if isinstance(event, ToolResultEvent) and not event.is_error]) == 4
    assert model.calls == 2


@pytest.mark.asyncio
async def test_stream_failure_cancels_active_and_queued_reads(monkeypatch):
    from common.errors import NetworkError
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from msgtypes.message import user_message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    monkeypatch.setenv("XEYO_EARLY_READONLY_TOOLS", "1")
    monkeypatch.setenv("XEYO_MAX_TOOL_USE_CONCURRENCY", "1")
    started = asyncio.Event()
    finished = asyncio.Event()
    executions = []
    class Read:
        name = "echo"
        is_read_only = True
        is_concurrency_safe = True
        def schema(self):
            return {"name": self.name, "description": "Read observation.", "input_schema": {"type": "object"}}
        async def execute(self, input, abort):
            executions.append(input["text"])
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
    class Model:
        last_usage = None
        async def stream(self, messages, tools, abort):
            for index in range(4):
                yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"read-{index}", "echo", {"text": str(index)}))
            await asyncio.wait_for(started.wait(), 1)
            raise NetworkError("injected stream failure")
    registry = ToolRegistry()
    registry.register(Read())
    store = MessageStore([user_message("Read observations.")])
    events = []
    set_permission_mode("never")
    with pytest.raises(NetworkError):
        async for event in query_loop(model=Model(), tools=registry, budget=BudgetTracker(max_turns=4),
                                      store=store, prompt=PromptAssembler(), system_prompt="test", abort=AbortController()):
            events.append(event)
    assert executions == ["0"] and finished.is_set()
    assert len([event for event in events if isinstance(event, ToolResultEvent)]) == 4
    assert len([message for message in store.items if message.role == "tool"]) == 4
