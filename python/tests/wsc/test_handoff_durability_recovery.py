"""A successful in-memory handoff is not a durable compaction checkpoint."""
import importlib
import json
import subprocess
import sys

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("ordinary", [False, True])
@pytest.mark.parametrize("stage", ["invocation", "receipt"])
async def test_failed_publication_retries_durability_before_any_fold(monkeypatch, tmp_path, native, ordinary, stage):
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    transcript = importlib.import_module("session.record_transcript")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    monkeypatch.setattr("engine.first_sniff.maybe_first_sniff_text", lambda **kwargs: "")
    store = MessageStore([Message(role="user", id="spec", content="当前任务：写报告并引用实际验收")])
    for i in range(35): store.append(Message(role="assistant", content="背景 " + "x" * 2000))
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    if ordinary:
        from tools.compact_tool import CompactTool
        registry.register(CompactTool())
        request = ToolUse("ordinary-request", "Compact", {})
        store.append(assistant_text_message("", [request]))
        result = await registry.run(request, AbortController())
        assert result.status == "ok" and result.metadata.get("compaction_request")
        from engine.execution_facts import tool_receipt
        store.append(tool_result_message(request.id, request.name, result.content, execution=tool_receipt(result)))
    class Heavy:
        name = "Heavy"
        @staticmethod
        def is_read_only(): return True
        @staticmethod
        def is_concurrency_safe(): return True
        def schema(self): return {"name": self.name, "description": "x" * 300000, "input_schema": {"type": "object"}}
    registry.register(Heavy())
    calls = []
    handoff_ids = []
    class Handoff:
        last_usage = None
        async def stream(self, messages, tools, abort):
            calls.append("handoff")
            handoff_ids.append("durable-handoff-" + str(len(handoff_ids) + 1))
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(handoff_ids[-1], "TodoWrite", {
                "todos": [{"id": "report", "content": "写报告", "activeForm": "写报告", "status": "pending"}],
                "checkpoint": {"objective": "完成当前报告", "context_message_ids": ["spec"]}}))
    class Model:
        context_limit = 1000000 if ordinary else 100000
        last_usage = None
        def for_handoff(self, max_tokens): return Handoff()
        async def stream(self, messages, tools, abort):
            calls.append("main")
            assert handoff_ids, str(working.wsc_timing_state)
            disk = transcript.load_transcript(path)
            assert any(row.get("tool_call_id") == handoff_ids[-1] for row in disk)
            assert "完成当前报告" in str(messages)
            yield ModelChunk(kind="text_delta", text="已观察任务")
    path = tmp_path / "transcript.jsonl"
    known = set()
    def persist(): transcript.record_transcript_sync(store.items, session_id="durability", path=path, known_ids=known)
    persist()
    original = path.read_bytes()
    write_batch = transcript._write_batch
    failure = [True]
    def faulty_write(batch):
        def targets(line):
            row = json.loads(line)
            if stage == "receipt": return row.get("name") == "TodoWrite" and row.get("role") == "tool"
            return row.get("role") == "assistant" and any(block.get("name") == "TodoWrite"
                for block in row.get("content", []) if isinstance(block, dict))
        if failure[0] and any(targets(line) for _, _, line in batch):
            raise OSError("fixture_receipt_disk_failure")
        return write_batch(batch)
    monkeypatch.setattr(transcript, "_write_batch", faulty_write)
    working = WorkingSnapshot(session_id="durability")
    if ordinary:
        from memory.wsc_timing import accepted_request
        from session.compression_source import compression_messages
        assert accepted_request(compression_messages(store, working), working) == "ordinary-request"
    async def submit():
        return [event async for event in query_loop(store=store, model=Model(), tools=registry,
            prompt=PromptAssembler(), system_prompt="fixture", abort=AbortController(),
            budget=BudgetTracker(max_turns=4), working=working, persist_handoff=persist)]
    try:
        first = await submit()
        assert working.compact_cursor == 0 and calls == ["handoff"]
        assert any("transcript" in getattr(event, "reason", "") for event in first)
        assert not any(row.get("tool_call_id") in handoff_ids for row in transcript.load_transcript(path))
        # Known IDs reserve the failed row, not a durability certificate.
        # At the receipt stage the actual tool has already succeeded.
        reserved_id = store.items[-1].id
        assert reserved_id in known
        second = await submit()
        assert working.compact_cursor == 0 and calls == ["handoff"]
        assert any("transcript" in getattr(event, "reason", "") for event in second)
        failure[0] = False
        await submit()
        assert working.compact_cursor > 0
        assert calls == (["handoff", "main"] if stage == "receipt" else ["handoff", "handoff", "main"])
        disk = transcript.load_transcript(path)
        assert sum(row["id"] == reserved_id for row in disk) == 1
        assert sum(row.get("role") == "tool" and row.get("name") == "TodoWrite"
                   and not row["content"][0].get("is_error") for row in disk) == 1
        assert path.read_bytes().startswith(original)
        # Read the actual stored declaration in a separate process. Parent
        # queue/cache/known IDs and the in-memory successful receipt are absent.
        probe = subprocess.run([sys.executable, "-c", "\n".join([
            "import json, sys",
            "from pathlib import Path",
            "from dataclasses import fields",
            "from session.record_transcript import load_transcript",
            "from session.message_store import MessageStore",
            "from session.compression_source import compression_messages",
            "from msgtypes.message import Message",
            "from memory.working import WorkingSnapshot",
            "from synaptic.todo_snapshot import latest_todo_snapshot",
            "names = {field.name for field in fields(Message)}",
            "store = MessageStore([Message(**{k:v for k,v in row.items() if k in names}) for row in load_transcript(Path(sys.argv[1]))])",
            "state = latest_todo_snapshot(compression_messages(store, WorkingSnapshot()))",
            "print(json.dumps({'observed':state.observed, 'checkpoint':state.checkpoint, 'records':state.records}))",
        ]), str(path)], capture_output=True, text=True, check=True, timeout=20)
        recovered = json.loads(probe.stdout)
        assert recovered["observed"] and recovered["checkpoint"]["objective"] == "完成当前报告"
        assert recovered["records"][0]["id"] == "report"
    finally:
        failure[0] = False
        assert transcript.flush_pending_sync()
