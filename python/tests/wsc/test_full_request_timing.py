"""Complete assembled input, notification-induced crossings, encoding identity."""
from copy import deepcopy

import pytest

from memory.working import WorkingSnapshot
from memory.wsc_request_timing import prepare
from memory.wsc_timing import request_measure, delivered


def render(rows, text):
    return rows + [{"role": "system", "content": text}]


def test_tool_schema_alone_can_cross_85_and_noop_does_not_spin():
    working = WorkingSnapshot()
    rows = [{"role": "user", "content": "task"}]
    schemas = [{"name": "tool", "description": "x" * 3_500}]
    original = deepcopy(rows)
    calls = []
    def compact():
        calls.append(True)
        return rows
    result = prepare(rows, schemas, working, context_limit=1_000,
                     build=lambda value: value, render=render, compact=compact)
    assert result.facts["automatic_attempts"] == 1
    assert result.facts["before"]["timing_action"] == "capacity"
    assert result.facts["outcome"] == "no_eligible_history"
    assert result.facts["after"]["timing_action"] == "capacity"
    assert calls == [True]
    assert rows == original


def test_current_injection_and_notice_are_counted_and_new_cursor_is_remeasured():
    working = WorkingSnapshot()
    rows = [{"role": "user", "content": "x" * 3_210}]
    schema = [{"name": "tool"}]
    # Below85 before the notice; the notice itself crosses85.
    assert request_measure(rows, schema, context_limit=1_000).action == "keep"
    def compact():
        working.compact_cursor = 2
        return [{"role": "user", "content": "current task and verification"}]
    result = prepare(rows, schema, working, context_limit=1_000,
                     build=lambda value: value, render=lambda value, text: render(value, text + "y" * 300), compact=compact)
    assert result.facts["before"]["timing_action"] == "capacity"
    assert result.facts["outcome"] == "compacted"
    assert result.facts["after"]["timing_action"] == "keep"
    assert result.delivery_key is None
    assert "上下文已达80%" not in str(result.messages)


def test_successful_notification_only_consumed_after_actual_delivery():
    working = WorkingSnapshot()
    rows = [{"role": "user", "content": "x" * 3_150}]
    schemas = [{"name": "tool"}]
    def no_compact():
        pytest.fail("request below85 was compacted")
    first = prepare(rows, schemas, working, context_limit=1_000, build=lambda value: value,
                    render=render, compact=no_compact)
    assert first.delivery_key == [0, 1_000]
    retried = prepare(rows, schemas, working, context_limit=1_000, build=lambda value: value,
                      render=render, compact=no_compact)
    assert retried.delivery_key == first.delivery_key
    delivered(working, retried.delivery_key)
    skipped = prepare(rows, schemas, working, context_limit=1_000, build=lambda value: value,
                      render=lambda value, text: value, compact=no_compact)
    assert skipped.delivery_key is None


def test_new_tool_result_crossing_85_is_processed_at_next_request():
    working = WorkingSnapshot()
    rows = [{"role": "user", "content": "a" * 2000}]
    first = prepare(rows, [], working, context_limit=1000, build=lambda value: value,
                    render=lambda value, text: value + [{"role": "system", "content": text}],
                    compact=lambda: pytest.fail("premature compaction"))
    assert first.facts["automatic_attempts"] == 0
    rows += [{"role": "assistant", "content": [{"type": "tool_use", "id": "large", "name": "Read", "input": {}}]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "large", "content": "z" * 1800}]}]
    before = deepcopy(rows)
    def compact():
        working.compact_cursor = 1
        return [{"role": "assistant", "content": "archived earlier history"}] + rows[1:]
    following = prepare(rows, [], working, context_limit=1000, build=lambda value: value,
                        render=lambda value, text: value + [{"role": "system", "content": text}], compact=compact)
    assert following.facts["before"]["timing_action"] == "capacity"
    assert following.facts["automatic_attempts"] == 1
    assert following.facts["after"]["timing_action"] == "keep"
    assert rows[-1] in following.messages and rows == before


def test_openai_input_normalization_is_same_as_actual_request_encoder():
    from model.openai_compat import OpenAICompatClient
    # Constructing the pure encoder needs no network or credentials.
    client = OpenAICompatClient.__new__(OpenAICompatClient)
    client._model, client._provider = "test", "openai"
    client._reasoning_effort, client._temperature, client._max_tokens = "", None, 999_999
    rows = [{"role": "user", "content": "task"}]
    schemas = [{"name": "tool", "description": "fact", "input_schema": {"type": "object"}}]
    body = client._build_body(rows, schemas, stream=True)
    assert client.context_input(rows, schemas) == {"messages": body["messages"], "tools": body["tools"]}
    measured = request_measure(rows, schemas, context_limit=1_000_000, model=client)
    assert measured.basis == "provider_normalized_input_utf8_quarters_estimate"
    # Output reserve/settings never appear in input occupancy.
    client._max_tokens = 1
    assert request_measure(rows, schemas, context_limit=1_000_000, model=client).input_tokens == measured.input_tokens
