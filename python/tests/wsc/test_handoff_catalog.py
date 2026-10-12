from copy import deepcopy
import json

import pytest

from memory.wsc_handoff_catalog import Catalog, INITIAL_BYTES, INITIAL_RECORDS


def transcript(count=500):
    return [{"message_id": f"source-{i}", "role": "user" if i == 0 else "assistant",
             "content": "当前验收规范：金额按分计算" if i == 0 else f"执行记录{i}"}
            for i in range(count)]


def test_large_directory_keeps_old_user_identity_and_exact_filtered_cursor():
    rows = transcript(5000)
    original = deepcopy(rows)
    catalog = Catalog(rows)
    initial = catalog.initial()
    assert len(initial) <= INITIAL_RECORDS
    assert sum(len(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode()) for r in initial) <= INITIAL_BYTES
    assert any(r["message_id"] == "source-0" for r in initial)
    page = catalog.read({"start": 0, "limit": 1, "role": "assistant", "query": "执行记录499"})
    assert page["records"][0]["source"] == 499
    assert page["next_source"] == 500
    assert catalog.read({"start": 500, "limit": 16, "query": "执行记录499"})["records"][0]["source"] == 4990
    assert rows == original


@pytest.mark.parametrize("args", [
    {"start": True, "limit": 1}, {"start": 0, "limit": 17},
    {"start": 0, "limit": 1, "role": []},
    {"start": 0, "limit": 1, "query": ""},
    {"start": 0, "limit": 1, "path": "secret"},
])
def test_invalid_catalog_arguments_are_neutral_validation_failures(args):
    with pytest.raises(ValueError, match="handoff_catalog_invalid_arguments"):
        Catalog(transcript()).read(args)


@pytest.mark.asyncio
async def test_generation_can_find_old_identity_then_read_exact_rule_without_full_enum():
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    rows = transcript()
    # The current binding lives outside both the last-user and last-32 entries.
    rows[40] = {"message_id": "binding", "role": "assistant", "content": "当前验收规范：金额按分计算"}
    seen, usage = [], []
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            attempt = len(seen)
            seen.append(deepcopy(messages))
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 1}
            if attempt == 0:
                assert '"message_id": "binding"' not in messages[-1]["content"]
                item = tools[0]["input_schema"]["properties"]["checkpoint"]["properties"]["context_message_ids"]["items"]
                assert "enum" not in item
                use = ToolUse("catalog-read", "HandoffCatalog", {"start": 0, "limit": 16, "role": "assistant", "query": "当前验收规范"})
            elif attempt == 1:
                page = json.loads(messages[-1]["content"][0]["content"])
                assert page["records"][0]["message_id"] == "binding"
                use = ToolUse("source-read", "HandoffSource", {"message_id": "binding", "offset": 0, "limit": 4096})
            else:
                page = json.loads(messages[-1]["content"][0]["content"])
                assert page["content"] == rows[40]["content"]
                use = ToolUse("declaration", "TodoWrite", {"todos": [], "checkpoint": {
                    "objective": "验收金额", "context_message_ids": ["binding"],
                    "constraints": [{"source_message_id": "binding", "quote": page["content"]}]}})
            yield ModelChunk(kind="tool_use", tool_use=use)
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    result = await generate(Model(), [{"role": "user", "content": "验收金额"}], rows,
                            TodoWriteTool().schema(), AbortController(), account=usage.append)
    assert result.name == "TodoWrite" and len(usage) == 3
    assert len(seen[-1]) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reads", "mixed", "duplicate", "read_limit"])
async def test_parallel_read_frames_are_bounded_and_declaration_is_exclusive(mode):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    seen, usage, reads = [], [], []
    declaration = {"todos": [], "checkpoint": {"objective": "当前验收", "context_message_ids": ["source-0"]}}
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            attempt = len(seen)
            seen.append(deepcopy(messages))
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 1}
            if attempt == 0 or mode == "read_limit":
                uses = [ToolUse(f"read-{attempt}", "HandoffSource", {"message_id": "source-0", "offset": 0, "limit": 4096}),
                        ToolUse(f"catalog-{attempt}", "HandoffCatalog", {"start": 0, "limit": 1})]
                if mode == "mixed": uses[1] = ToolUse("declaration", "TodoWrite", declaration)
                if mode == "duplicate": uses[1].id = uses[0].id
            else:
                assert len(messages[-3]["content"]) == 2
                assert messages[-2]["tool_call_id"] == "read-0"
                assert messages[-1]["tool_call_id"] == "catalog-0"
                uses = [ToolUse("declaration", "TodoWrite", declaration)]
            for use in uses: yield ModelChunk(kind="tool_use", tool_use=use)
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    async def invoke():
        return await generate(Model(), [{"role": "user", "content": "当前验收"}], transcript(),
            TodoWriteTool().schema(), AbortController(), account=usage.append, admit_read=lambda: reads.append(True))
    if mode == "reads":
        assert (await invoke()).name == "TodoWrite"
        assert len(usage) == 2 and len(reads) == 2
    else:
        error = {"mixed": "handoff_mixed_declaration", "duplicate": "handoff_call_identity_conflict", "read_limit": "handoff_recall_request_limit"}[mode]
        with pytest.raises(ValueError, match=error): await invoke()
        from memory.wsc_handoff_generation import MAX_REQUESTS
        assert len(reads) == ((MAX_REQUESTS - 1) * 2 if mode == "read_limit" else 0)
