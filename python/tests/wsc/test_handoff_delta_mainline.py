from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_delta import materialize
from memory.wsc_handoff_generation import generate
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_fact_disposition import prepared
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


MARKER = "\n提交后的来源增量="


def test_unbounded_event_count_whole_records_and_sources_unchanged():
    rows, _ = prepared()
    rows += [{"id": f"u{i}", "role": "user", "content": f"新阶段{i}，值={i}"} for i in range(12)]
    rows += [{"id": f"tool{i}", "role": "tool", "content": "回执"} for i in range(100)]
    before = deepcopy(rows)
    actual = materialize(rows)
    assert [r["message_id"] for r in actual["sources"]] == ["next", *[f"u{i}" for i in range(12)]]
    assert all(r["content"] == rows[r["source"]]["content"] and r["text_complete"] for r in actual["sources"])
    assert actual["base_checkpoint_message_id"] == "base" and rows == before


def test_no_checkpoint_does_not_reintroduce_historical_text():
    assert materialize([{"id": "old", "role": "user", "content": "历史原文"}]) is None


def test_no_new_text_does_not_add_empty_context_metadata():
    rows, _ = prepared()
    assert materialize(rows[:-1]) is None


def test_evidence_envelope_itself_cannot_consume_reserved_capacity():
    rows, _ = prepared()
    assert materialize(rows, admit=lambda value: False) is None


def test_notes_retractions_and_tools_are_not_semantic_delta():
    rows, _ = prepared()
    rows += [{"id": "note", "role": "user", "content": "注入", "note_key": "runtime"},
             {"id": "gone", "role": "assistant", "content": "撤回", "note_retracted": True},
             {"id": "result", "role": "tool", "content": "工具内容"}]
    assert [r["message_id"] for r in materialize(rows)["sources"]] == ["next"]


def test_duplicate_source_identity_cannot_be_presented_as_unique():
    rows, _ = prepared()
    rows.append({"id": "next", "role": "user", "content": "另一原文"})
    with pytest.raises(ValueError, match="handoff_delta_source_ambiguous"):
        materialize(rows)


def test_byte_and_capacity_limits_defer_whole_records_with_complete_identity_list():
    rows, _ = prepared()
    rows += [{"id": "huge", "role": "user", "content": "原文" * 16000},
             {"id": "latest", "role": "assistant", "content": "目前计划"}]
    actual = materialize(rows, admit=lambda value: len(value["sources"]) <= 1)
    assert [r["message_id"] for r in actual["sources"]] == ["latest"]
    assert actual["deferred_message_ids"] == ["next", "huge"]


class Model:
    context_limit = 100000
    last_usage = None

    def __init__(self, capacity_records=None, reject_envelope=False):
        self.requests, self.counted = [], []
        self.capacity_records = capacity_records
        self.reject_envelope = reject_envelope

    def for_handoff(self, max_tokens):
        self.reserve = max_tokens
        return self

    def context_input(self, messages, tools):
        self.counted.append(deepcopy(messages))
        return {"messages": messages, "tools": tools}

    def context_token_measure(self, value):
        marker = value["messages"][-1].get("content", "")
        delta = json.loads(marker.split(MARKER)[1]) if MARKER in marker else None
        if delta and self.reject_envelope:
            return self.context_limit, "fixture_full_request_count"
        if self.capacity_records is not None and delta and len(delta["sources"]) > self.capacity_records:
            return self.context_limit, "fixture_full_request_count"
        return 100, "fixture_full_request_count"

    async def stream(self, request, tools, abort):
        self.requests.append(deepcopy(request))
        yield ModelChunk(kind="tool_use", tool_use=ToolUse("declare", "TodoWrite",
            {"todos": [], "checkpoint": {"objective": "", "context_message_ids": ["next"]}}))


async def call(model, rows):
    messages = [{"role": "user", "content": "被压缩的旧工作状态"}]
    before = deepcopy((messages, rows))
    result = await generate(model, messages, rows, TodoWriteTool().schema(), AbortController(),
                            account=lambda value: None, scope_protocol=True)
    assert (messages, rows) == before
    return result


@pytest.mark.asyncio
async def test_default_real_generator_ab_presents_and_counts_delta_before_send():
    rows, _ = prepared()
    old = Model()
    with patch("memory.wsc_handoff_delta.materialize", return_value=None):
        before = await call(old, rows)
    assert MARKER not in old.requests[0][-1]["content"]
    assert not before.presentation["sources"][0]["complete"]
    model = Model()
    result = await call(model, rows)
    actual = json.loads(model.requests[0][-1]["content"].split(MARKER)[1])
    assert actual == materialize(rows)
    assert actual["sources"][0]["content"] == rows[-1]["content"]
    assert model.requests[0] in model.counted
    assert result.presentation["sources"][0]["complete"]


@pytest.mark.asyncio
async def test_final_request_and_coverage_exclude_capacity_deferred_text():
    rows, _ = prepared()
    model = Model(capacity_records=0)
    result = await call(model, rows)
    actual = json.loads(model.requests[0][-1]["content"].split(MARKER)[1])
    assert actual["sources"] == [] and actual["deferred_message_ids"] == ["next"]
    assert model.requests[0] in model.counted
    assert not result.presentation["sources"][0]["complete"]


@pytest.mark.asyncio
async def test_ambiguous_delta_stops_before_model_without_mutating_source():
    rows, _ = prepared()
    rows.append(deepcopy(rows[-1]))
    model = Model()
    with pytest.raises(ValueError, match="handoff_delta_source_ambiguous"):
        await call(model, rows)
    assert not model.requests


@pytest.mark.asyncio
async def test_metadata_capacity_refusal_preserves_existing_send_and_does_not_claim_exposure():
    rows, _ = prepared()
    model = Model(reject_envelope=True)
    result = await call(model, rows)
    assert len(model.requests) == 1 and MARKER not in model.requests[0][-1]["content"]
    assert not result.presentation["sources"][0]["complete"]
