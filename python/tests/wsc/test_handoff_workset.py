from copy import deepcopy

import pytest

from memory.wsc_handoff_workset import materialize, MAX_WORKSET_BYTES
from tests.wsc.test_handoff_bindings import prepared


@pytest.mark.asyncio
async def test_only_committed_bound_sources_enter_isolated_workset(tmp_path):
    store, tools, source, persist, path, state = await prepared(tmp_path)
    original, prefix = deepcopy(source()), path.read_bytes()
    workset = materialize(source())
    assert workset == {"sources": [{"message_id": "spec", "content": "RF-683917是退款验收标记", "text_complete": True}],
                       "deferred_message_ids": []}
    assert source() == original and path.read_bytes() == prefix
    assert "报告验收任务" not in str(workset)


def test_unbound_history_never_becomes_active_workset():
    assert materialize([{"id": "old", "role": "user", "content": "旧任务"}])["sources"] == []


@pytest.mark.asyncio
async def test_large_bound_source_is_deferred_without_partial_fact_substitution(tmp_path):
    store, tools, source, persist, path, state = await prepared(tmp_path)
    # This is a separate snapshot, not a mutation of the persisted source.
    rows = deepcopy(source())
    rows[0]["content"] = "规范" * MAX_WORKSET_BYTES
    assert materialize(rows) == {"sources": [], "deferred_message_ids": ["spec"]}


@pytest.mark.asyncio
async def test_request_capacity_can_admit_complete_source_above_fallback_byte_cap(tmp_path):
    store, tools, source, persist, path, state = await prepared(tmp_path)
    rows = deepcopy(source())
    rows[0]["content"] = "规范" * MAX_WORKSET_BYTES + "RF-683917"
    observed = []
    def admit(records, deferred):
        observed.append((deepcopy(records), list(deferred)))
        return True
    result = materialize(rows, admit=admit)
    assert result["sources"][0]["content"] == rows[0]["content"]
    assert result["sources"][0]["text_complete"] and not result["deferred_message_ids"]
    assert len(observed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity, complete", [(1_000_000, True), (10_000, False)])
async def test_generation_uses_actual_request_capacity_for_bound_source(tmp_path, capacity, complete):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate, OUTPUT_TOKENS
    from memory.wsc_timing import request_measure
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    import json
    store, tools, source, persist, path, state = await prepared(tmp_path)
    rows = deepcopy(source())
    rows[0]["content"] = "规范" * MAX_WORKSET_BYTES + "RF-683917"
    sent = []
    class Client:
        last_usage = None
        async def stream(self, messages, schemas, abort):
            sent.append(deepcopy(messages))
            value = json.loads(messages[-1]["content"].split("\n已绑定任务来源原文=", 1)[1])
            assert bool(value["sources"]) is complete
            if complete:
                assert value["sources"][0]["content"] == rows[0]["content"]
            else:
                assert value == {"sources": [], "deferred_message_ids": ["spec"]}
                assert "RF-683917" not in str(messages)
            assert request_measure(messages, schemas, context_limit=capacity).input_tokens + OUTPUT_TOKENS <= capacity
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 1}
            yield ModelChunk(kind="tool_use", tool_use=ToolUse("generated", "TodoWrite", state))
    class Model:
        context_limit = capacity
        def for_handoff(self, max_tokens): return Client()
    result = await generate(Model(), [{"role": "assistant", "content": "当前已提交任务"}], rows,
                            TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    assert result.id == "generated" and len(sent) == 1
    observation = result.presentation["sources"][0]
    assert observation["message_id"] == "spec"
    assert observation["complete"] is complete
    assert observation["presented_ranges"] == ([[0, len(rows[0]["content"])]] if complete else [])
