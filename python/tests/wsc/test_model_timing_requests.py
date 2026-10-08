"""Actual accepted tool receipts, response boundaries and delivery persistence."""
import json
from copy import deepcopy

import pytest

from engine.abort import AbortController
from engine.execution_facts import tool_receipt
from memory.working import WorkingSnapshot, flush, hydrate, reset_rollback_state
from memory.wsc_timing import accepted_request, notification, delivered
from tools.compact_tool import CompactTool


def invocation(identity):
    return {"role": "assistant", "content": [{"type": "tool_use", "id": identity,
            "name": "Compact", "input": {}}]}


def response(identity, execution):
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": identity,
            "content": "compaction_request=accepted; execution=pending", "execution": execution}]}


@pytest.mark.asyncio
async def test_only_actual_successful_paired_receipt_requests_compaction(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    tool = CompactTool()
    result = await tool.execute({}, AbortController())
    assert result.content.endswith("execution=pending")
    receipt = tool_receipt(result)
    working = WorkingSnapshot()
    assert accepted_request([invocation("r")], working) is None
    assert accepted_request([response("r", receipt)], working) is None
    rows = [invocation("r"), response("r", receipt)]
    original = deepcopy(rows)
    assert accepted_request(rows, working) == "r"
    working.wsc_timing_state = {"handled_request": "r"}
    assert accepted_request(rows, working) is None
    # Coalesced requests must not revive earlier calls after the last is handled.
    working.wsc_timing_state = {"handled_request": "s"}
    assert accepted_request(rows + [invocation("s"), response("s", receipt)], working) is None
    assert rows == original
    failed = await tool.execute({"extra": True}, AbortController())
    assert failed.is_error
    assert accepted_request([invocation("r"), response("r", tool_receipt(failed))], WorkingSnapshot()) is None
    assert accepted_request([invocation("r"), response("r", "invalid")], WorkingSnapshot()) is None
    abort = AbortController()
    abort.abort()
    assert (await tool.execute({}, abort)).is_error
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "0")
    assert not (await tool.execute({}, AbortController())).is_error


def test_notification_full_input_dedup_restart_and_rollback(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    working = WorkingSnapshot(session_id="timing-notice")
    rows = [{"role": "system", "content": "s" * 100}, {"role": "user", "content": "a" * 1_000}]
    schemas = [{"name": "tool", "description": "t" * 2_000}]
    original = deepcopy(rows)
    text, key, result = notification(rows, schemas, working, context_limit=1_000)
    assert text.startswith("上下文已达80%")
    assert result.basis == "complete_request_utf8_quarters_estimate"
    assert notification(rows, [], working, context_limit=1_000)[0] == ""
    # Merely constructing or failing to send the request does not consume it.
    assert notification(rows, schemas, working, context_limit=1_000)[1] == key
    delivered(working, key)
    flush(working.session_id, working)
    recovered = hydrate(working.session_id)
    assert notification(rows, schemas, recovered, context_limit=1_000)[0] == ""
    recovered.compact_cursor += 1
    assert notification(rows, schemas, recovered, context_limit=1_000)[0]
    reset_rollback_state(recovered)
    assert recovered.wsc_timing_state == {}
    assert rows == original


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_real_query_loop_handoff_before_model_request_fold_or_keep_pending(monkeypatch, tmp_path, valid):
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse, user_message, Message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from session.record_transcript import record_transcript_sync

    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    # This test exercises the fallback, independently of task continuity/WSC.
    monkeypatch.setenv("XEYO_WSC", "0")
    rows = [user_message("current task" + "a" * 80_000)]
    for index in range(12):
        rows.extend([Message(role="assistant", content=f"observation {index}"), user_message(f"detail {index}")])
    store = MessageStore(rows)
    working = WorkingSnapshot(session_id="timing-request")

    class Model:
        context_limit = 1_000_000
        last_usage = {}
        requests = []
        def for_handoff(self, max_tokens):
            assert max_tokens == 2048
            class Handoff:
                last_usage = {}
                async def stream(inner, messages, tools, abort):
                    assert tools[0]["name"] == "TodoWrite"
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse("handoff-r", "TodoWrite", {
                        "todos": [{"id": "continue", "content": "current task", "activeForm": "continue", "status": "pending"}],
                        "checkpoint": {"objective": "current task", "context_message_ids": [rows[0].id if valid else "invented"]}}))
            return Handoff()

        async def stream(self, messages, tools, abort):
            self.requests.append(deepcopy(messages))
            assert any(schema["name"] == "Compact" for schema in tools)
            if len(self.requests) == 1:
                assert working.compact_cursor == 0
                yield ModelChunk(kind="tool_use", tool_use=ToolUse(id="compact-r", name="Compact", input={}))
            else:
                assert working.compact_cursor > 0
                assert "compaction_request=accepted; execution=pending" in json.dumps(messages)
                yield ModelChunk(kind="text_delta", text="continued")

    model = Model()
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    known = set()
    async for _ in query_loop(store=store, model=model, tools=registry, prompt=PromptAssembler(),
                              system_prompt="test", abort=AbortController(), budget=BudgetTracker(max_turns=3), working=working,
                              persist_handoff=lambda: record_transcript_sync(store.items, session_id=working.session_id,
                                  path=tmp_path / "transcript.jsonl", known_ids=known)):
        pass
    if valid:
        assert len(model.requests) == 2
        assert working.wsc_timing_state["handled_request"] == "compact-r"
        assert working.wsc_timing_state["request_outcome"] == "compacted"
    else:
        from session.compression_source import compression_messages
        assert len(model.requests) == 1 and working.compact_cursor == 0
        assert accepted_request(compression_messages(store, working), working) == "compact-r"
        assert "handled_request" not in working.wsc_timing_state
    flush(working.session_id, working)
    assert hydrate(working.session_id).wsc_timing_state == working.wsc_timing_state
