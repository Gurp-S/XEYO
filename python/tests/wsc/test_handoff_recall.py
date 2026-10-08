from copy import deepcopy
import json
from pathlib import Path

import pytest

from memory.wsc_handoff_recall import read


@pytest.mark.parametrize("bad", [{"message_id": "missing", "offset": 0, "limit": 1},
    {"message_id": "spec", "offset": -1, "limit": 1},
    {"message_id": "spec", "offset": True, "limit": 1},
    {"message_id": "spec", "offset": 0, "limit": 4097},
    {"message_id": "spec", "offset": 0, "limit": 1, "file_path": "secret"}])
def test_source_read_is_bounded_and_has_no_filesystem_arguments(bad):
    with pytest.raises(ValueError): read(bad, [{"message_id": "spec", "role": "user", "content": "规范"}])


def test_duplicate_identity_cannot_read_arbitrary_source():
    row = {"message_id": "spec", "role": "user", "content": "规范"}
    with pytest.raises(ValueError): read({"message_id": "spec", "offset": 0, "limit": 2}, [row, row])


@pytest.mark.asyncio
async def test_real_cold_long_spec_is_paged_before_generated_commit(tmp_path):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.wsc_projection import production_params
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse
    from session.compression_source import compression_messages
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from synaptic.project import project
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from tools.tool_registry import ToolRegistry
    rule = "报告绑定最近实际成功回执；文件存在不作为成功证据"
    text = "当前报告规范\n" + "归档字段abcdefghij\n" * 3000 + rule
    rows = [{"message_id": "spec", "role": "user", "content": text}]
    projection = project(rows, region_end=1, params=production_params(), view_path=tmp_path / "cold.txt")
    # Force a source too large for hot checkpoint inlining; the model starts
    # with only a factual archive index, never the complete original text.
    initial = [{"role": "assistant", "content": projection.text}]
    original = deepcopy(rows)
    captured = []
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            attempt = len(captured)
            captured.append(deepcopy(messages))
            self.last_usage = {"prompt_tokens": 10 + attempt, "completion_tokens": 2}
            if attempt == 0:
                assert rule not in str(messages)
                use = ToolUse("source-first", "HandoffSource", {"message_id": "spec", "offset": 0, "limit": 10})
            elif attempt == 1:
                page = json.loads(messages[-1]["content"][0]["content"])
                assert page["content"] == text[:10] and rule not in page["content"]
                use = ToolUse("source-last", "HandoffSource", {"message_id": "spec", "offset": page["total_characters"] - len(rule), "limit": 4096})
            else:
                page = json.loads(messages[-1]["content"][0]["content"])
                assert page["content"] == rule and page["next_offset"] is None
                use = ToolUse("declaration", "TodoWrite", {
                    "todos": [{"id": "report", "content": "写报告", "status": "pending", "activeForm": "写报告"}],
                    "checkpoint": {"objective": "完成当前报告", "context_message_ids": ["spec"],
                        "constraints": [{"source_message_id": "spec", "quote": rule}]}})
            yield ModelChunk(kind="tool_use", tool_use=use)
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(TodoWriteTool(cwd=str(tmp_path)))
    store = MessageStore([Message(role="user", id="spec", content=text)])
    working = WorkingSnapshot()
    path = tmp_path / "transcript.jsonl"
    known = set()
    usages, admissions, reads = [], [], []
    async def generated(source):
        return await generate(Model(), initial, source, TodoWriteTool().schema(), AbortController(),
            account=usages.append, admit_next=lambda: admissions.append(True), admit_read=lambda: reads.append(True))
    await commit(source=lambda: compression_messages(store, working), generate=generated, store=store,
        tools=registry, abort=AbortController(), persist=lambda: record_transcript_sync(store.items,
            session_id="recall", path=path, known_ids=known))
    assert len(usages) == 3 and len(admissions) == 2 and len(reads) == 2
    assert len(store.items) == 3  # Isolated retrieval frames do not enter main history.
    assert rows == original and Path(projection.view_path).read_text(encoding="utf-8")
    assert rule in store.items[-1].content[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["budget", "requests", "capacity"])
async def test_recall_limits_stop_without_declaration_or_unaccounted_retry(stop):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate, MAX_REQUESTS, OUTPUT_TOKENS, source_schema, REQUEST
    from memory.wsc_handoff_recall import schema as read_schema
    from memory.wsc_handoff_catalog import schema as catalog_schema
    from memory.wsc_timing import request_measure
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    sources = [{"message_id": "spec", "role": "user", "content": "规范" * 5000}]
    initial = [{"role": "assistant", "content": "归档来源 spec"}]
    schema, identities = source_schema(TodoWriteTool().schema(), sources)
    initial_cost = request_measure(initial + [{"role": "user", "content": REQUEST + "\n来源身份=" + json.dumps(identities, ensure_ascii=False) + "\n来源总数=" + str(len(sources))}],
        [schema, read_schema(), catalog_schema()], context_limit=100000).input_tokens
    count, usage = [], []
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            count.append(True)
            self.last_usage = {"prompt_tokens": 11, "completion_tokens": 2}
            yield ModelChunk(kind="tool_use", tool_use=ToolUse("read-" + str(len(count)), "HandoffSource",
                {"message_id": "spec", "offset": 0, "limit": 4096}))
    class Model:
        context_limit = initial_cost + OUTPUT_TOKENS + 128 if stop == "capacity" else 100000
        def for_handoff(self, max_tokens): return Client()
    def admission():
        if stop == "budget": raise ValueError("fixture_budget_exhausted")
    expected = {"budget": "fixture_budget_exhausted", "requests": "handoff_recall_request_limit",
                "capacity": "handoff_request_exceeds_capacity"}[stop]
    with pytest.raises(ValueError, match=expected):
        await generate(Model(), initial, sources, TodoWriteTool().schema(), AbortController(),
                       account=usage.append, admit_next=admission)
    assert len(count) == (MAX_REQUESTS if stop == "requests" else 1)
    assert len(usage) == len(count)
