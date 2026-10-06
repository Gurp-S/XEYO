"""Finalization must execute admitted tools before terminating, without another model round."""
import pytest

from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import FinalEvent, StoppedEvent, ToolCallEvent, ToolResultEvent
from msgtypes.message import ToolUse
from permissions.policy import set_permission_mode
from session.hydrate import load_session_messages
from tools.echo import EchoTool
from tools.file_edit_tool.file_edit_tool import FileEditTool
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.file_write_tool.file_write_tool import FileWriteTool
from tools.fileio.read_state import ReadFileState
from tools.tool_registry import ToolRegistry


class _Model:
    last_usage = None

    def __init__(self, final_tools, read_path=None, final_text="finished"):
        self.calls = 0
        self.final_tools = final_tools
        self.read_path = read_path
        self.final_text = final_text

    async def stream(self, messages, tools, abort):
        self.calls += 1
        if self.calls == 5:
            if self.final_text:
                yield ModelChunk(kind="text_delta", text=self.final_text)
            for tool in self.final_tools:
                yield ModelChunk(kind="tool_use", tool_use=tool)
        elif self.calls > 5:
            yield ModelChunk(kind="text_delta", text="finished")
        else:
            name, data = "echo", {"text": f"step-{self.calls}"}
            if self.calls == 1 and self.read_path:
                name, data = "Read", {"file_path": str(self.read_path)}
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(
                id=f"step-{self.calls}", name=name, input=data,
            ))


def _engine(tmp_path, model, extra_tools=(), limited=True):
    state = ReadFileState()
    registry = ToolRegistry()
    for tool in (
        EchoTool(), FileReadTool(cwd=str(tmp_path), read_state=state),
        FileWriteTool(cwd=str(tmp_path), read_state=state),
        FileEditTool(cwd=str(tmp_path), read_state=state), *extra_tools,
    ):
        registry.register(tool)
    set_permission_mode("never")
    return QueryEngine({
        "cwd": str(tmp_path), "tools": registry, "model_client": model,
        "provider": "deepseek", "model": "deepseek-v4-flash",
        "max_turns": 1 if limited else 10,
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["Write", "Edit"])
@pytest.mark.parametrize("limited,quota", [(False, 3), (True, 3), (True, 0)])
async def test_file_side_effect_and_result_before_terminal(tmp_path, monkeypatch, operation, limited, quota):
    monkeypatch.setenv("XEYO_WRAP_QUOTA", str(quota))
    path = tmp_path / "output.txt"
    if operation == "Edit":
        path.write_text("original\n", encoding="utf-8")
    data = {"file_path": str(path), "content": "updated\n"} if operation == "Write" else {
        "file_path": str(path), "old_string": "original", "new_string": "updated",
    }
    model = _Model([ToolUse(id="final-file", name=operation, input=data)],
                   read_path=path if operation == "Edit" else None)
    tool_class = FileWriteTool if operation == "Write" else FileEditTool
    original_execute = tool_class.execute
    executions = []

    async def tracked_execute(self, input, abort):
        executions.append(input)
        return await original_execute(self, input, abort)

    monkeypatch.setattr(tool_class, "execute", tracked_execute)
    engine = _engine(tmp_path, model, limited=limited)
    events = [event async for event in engine.submit("Perform the file operation.")]
    accepted = not limited or quota > 0
    assert model.calls == (5 if limited else 6)
    calls = [e for e in events if isinstance(e, ToolCallEvent) and e.tool_use_id == "final-file"]
    results = [e for e in events if isinstance(e, ToolResultEvent) and e.tool_use_id == "final-file"]
    assert len(calls) == int(accepted)
    assert len(executions) == int(accepted)
    assert len(results) == 1
    assert results[0].is_error is not accepted
    if accepted:
        assert path.read_text(encoding="utf-8") == "updated\n"
    elif operation == "Edit":
        assert path.read_text(encoding="utf-8") == "original\n"
    else:
        assert not path.exists()
    terminal_index = next(i for i, e in enumerate(events) if isinstance(e, (FinalEvent, StoppedEvent)))
    assert events.index(results[0]) < terminal_index
    stored = [message for message in load_session_messages(engine.session_id) if message.tool_call_id == "final-file"]
    assert len(stored) == 1
    if accepted:
        assert "wrap_up]" not in str(stored[0].content)


@pytest.mark.asyncio
async def test_wrap_batch_quota_and_agent_restriction(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_WRAP_QUOTA", "2")
    uses = [ToolUse(id="agent", name="Agent", input={})] + [
        ToolUse(id=f"write-{i}", name="Write", input={
            "file_path": str(tmp_path / f"{i}.txt"), "content": str(i),
        }) for i in range(3)
    ]
    model = _Model(uses)
    events = [event async for event in _engine(tmp_path, model).submit("Write files.")]
    assert model.calls == 5
    assert [p.exists() for p in [tmp_path / f"{i}.txt" for i in range(3)]] == [True, True, False]
    final_results = [e for e in events if isinstance(e, ToolResultEvent) and e.tool_use_id in {u.id for u in uses}]
    assert len(final_results) == 4
    assert {e.tool_use_id for e in final_results if e.is_error} == {"agent", "write-2"}
    assert "not started during finalization" in next(e.output for e in final_results if e.tool_use_id == "agent")
    assert "quota exhausted" in next(e.output for e in final_results if e.tool_use_id == "write-2")


@pytest.mark.asyncio
@pytest.mark.parametrize("final_text", ["", "finished"])
async def test_actual_tool_failure_is_reported(tmp_path, monkeypatch, final_text):
    monkeypatch.setenv("XEYO_WRAP_QUOTA", "3")
    path = tmp_path / "missing.txt"
    model = _Model([ToolUse(id="failed-edit", name="Edit", input={
        "file_path": str(path), "old_string": "missing", "new_string": "updated",
    })], final_text=final_text)
    events = [event async for event in _engine(tmp_path, model).submit("Edit file.")]
    results = [e for e in events if isinstance(e, ToolResultEvent) and e.tool_use_id == "failed-edit"]
    assert model.calls == 5
    assert len(results) == 1 and results[0].is_error
    assert not path.exists()
    terminal = [e for e in events if isinstance(e, (FinalEvent, StoppedEvent))]
    assert len(terminal) == 1
    assert isinstance(terminal[0], FinalEvent if final_text else StoppedEvent)


@pytest.mark.asyncio
async def test_cancel_after_wrap_admission_prevents_write(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_WRAP_QUOTA", "3")
    path = tmp_path / "cancelled.txt"
    model = _Model([ToolUse(id="cancelled-write", name="Write", input={
        "file_path": str(path), "content": "updated",
    })])
    engine = _engine(tmp_path, model)
    events = []
    async for event in engine.submit("Write file."):
        events.append(event)
        if isinstance(event, ToolCallEvent) and event.tool_use_id == "cancelled-write":
            engine.abort_controller.abort()
    assert model.calls == 5
    assert not path.exists()
    assert not any(isinstance(e, FinalEvent) for e in events)
    assert any(isinstance(e, StoppedEvent) and e.reason == "aborted" for e in events)
    assert len([m for m in load_session_messages(engine.session_id) if m.tool_call_id == "cancelled-write"]) == 1


@pytest.mark.asyncio
async def test_wrap_write_respects_before_snapshot_gate(tmp_path, monkeypatch):
    import engine.query_engine as engine_module

    monkeypatch.setenv("XEYO_WRAP_QUOTA", "3")
    original_loop = engine_module.query_loop
    gate_calls = []

    async def failed_snapshot():
        gate_calls.append(True)
        raise RuntimeError("snapshot unavailable")

    async def gated_loop(**kwargs):
        kwargs["ensure_before"] = failed_snapshot
        async for event in original_loop(**kwargs):
            yield event

    monkeypatch.setattr(engine_module, "query_loop", gated_loop)
    path = tmp_path / "blocked.txt"
    model = _Model([ToolUse(id="blocked-write", name="Write", input={
        "file_path": str(path), "content": "updated",
    })])
    events = [event async for event in _engine(tmp_path, model).submit("Write file.")]
    assert gate_calls == [True]
    assert model.calls == 5 and not path.exists()
    result = next(e for e in events if isinstance(e, ToolResultEvent) and e.tool_use_id == "blocked-write")
    assert result.is_error and "snapshot unavailable" in result.output


@pytest.mark.asyncio
async def test_wrap_write_respects_readonly_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_WRAP_QUOTA", "3")
    path = tmp_path / "denied.txt"
    model = _Model([ToolUse(id="denied-write", name="Write", input={
        "file_path": str(path), "content": "updated",
    })])
    engine = _engine(tmp_path, model)
    engine.set_permission_profile("readonly")
    events = [event async for event in engine.submit("Write file.")]
    assert model.calls == 5 and not path.exists()
    result = next(e for e in events if isinstance(e, ToolResultEvent) and e.tool_use_id == "denied-write")
    assert result.is_error
