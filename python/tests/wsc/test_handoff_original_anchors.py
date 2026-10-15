from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_anchors import ancestry, materialize
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_validation import validate
from memory.wsc_handoff_workset import materialize as workset
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from tests.wsc.test_task_continuity import receipt, task
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


MARKER = "\n已提交事实的原始来源="
QUOTE = "不发布、不修改git；金额使用整数分。"
ORIGINAL = QUOTE + "\n该限制来自支付接入验收，失败回执编号ANCHOR-917。"


def chained(generations=3):
    rows = [{"id": "original", "role": "user", "content": ORIGINAL}]
    raw = None
    for number in range(generations):
        prior = "original" if number == 0 else f"cp{number - 1}"
        raw = {"todos": [{"id": "verify", "content": "核对支付接入验收并引用原始依据", "status": "pending",
                          "activeForm": "核对支付接入验收", "output": "result.json"}], "checkpoint": {
            "objective": "核对支付接入验收", "context_message_ids": [prior],
            "decisions": [{"source_message_id": prior, "quote": QUOTE}],
            "constraints": [{"source_message_id": prior, "quote": QUOTE}],
            "phase_state": {"current_phase_id": "verify", "phases": [
                {"id": "verify", "name": "验收", "source_message_ids": [prior]}],
                "active_context_message_ids": [prior],
                "fact_scopes": {"decisions": [{"kind": "task"}], "constraints": [{"kind": "task"}]}}}}
        validate(raw, rows, require_phase=True)
        addition = receipt(f"declare{number}", raw["todos"], raw["checkpoint"])
        addition[-1]["id"] = f"cp{number}"
        rows += addition
    candidate = deepcopy(raw)
    candidate["checkpoint"]["context_message_ids"].append("original")
    for field in ("decisions", "constraints"):
        candidate["checkpoint"][field][0]["source_message_id"] = "original"
    return rows, candidate


@pytest.mark.parametrize("generations", [1, 3, 5, 10])
def test_real_committed_quote_chain_reaches_original_without_changing_state(generations):
    rows, _ = chained(generations)
    before = deepcopy(rows)
    records, unknown = ancestry(rows)
    assert [r["message_id"] for r in records] == ["original"] and not unknown
    assert records[0]["content"] == ORIGINAL and records[0]["source"] == 0
    assert rows == before
    if generations > 1:
        assert "ANCHOR-917" not in json.dumps(workset(rows), ensure_ascii=False)
        assert "ANCHOR-917" in json.dumps(materialize(rows), ensure_ascii=False)


@pytest.mark.parametrize("change", ["legacy", "wrong_field", "duplicate", "note", "retracted", "terminal"])
def test_invalid_or_nonoriginal_or_inactive_facts_cannot_reheat_as_original(change):
    rows, _ = chained(1)
    if change == "legacy":
        rows = receipt("legacy", [task()], {"decisions": [QUOTE]})
        rows[-1]["id"] = "legacy-result"
    elif change in {"note", "retracted"}:
        rows[0]["note_key" if change == "note" else "note_retracted"] = True
    elif change == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif change == "terminal":
        rows += receipt("closed", [task("verify", "completed")])
    else:
        cp = {"objective": "核对", "context_message_ids": ["cp0"],
              "constraints": [{"source_message_id": "cp0", "quote": "not a whole same-field value"}]}
        rows += receipt("wrong", [task()], cp)
    records, unknown = ancestry(rows)
    assert records == []
    assert materialize(rows) is None
    if change != "terminal":
        assert unknown


def test_byte_and_capacity_limits_preserve_deferred_identities_and_never_partial_text():
    rows, _ = chained()
    value = materialize(rows, max_bytes=10)
    assert value["sources"] == [] and value["deferred_message_ids"] == ["original"]
    assert materialize(rows, admit=lambda value: False) is None
    assert materialize(rows, presented_ids=["original"]) is None


def test_historical_phase_fact_does_not_reheat_its_original_text():
    rows = [{"id": "old", "role": "user", "content": "过去设计阶段不改代码。"},
            {"id": "now", "role": "user", "content": "当前验收引用实际回执。"}]
    cp = {"objective": "当前验收", "context_message_ids": ["old", "now"],
          "constraints": [{"source_message_id": r["id"], "quote": r["content"]} for r in rows],
          "phase_state": {"current_phase_id": "verify", "phases": [
              {"id": "design", "name": "设计", "source_message_ids": ["old"]},
              {"id": "verify", "name": "验收", "source_message_ids": ["now"]}],
              "active_context_message_ids": ["now"], "fact_scopes": {
                  "decisions": [], "constraints": [{"kind": "phase", "phase_id": "design"}, {"kind": "task"}]}}}
    rows += receipt("phase", [task()], cp)
    rows[-1]["id"] = "phase-result"
    records, unknown = ancestry(rows)
    assert [r["message_id"] for r in records] == ["now"] and not unknown


class Model:
    context_limit = 100000
    last_usage = None

    def __init__(self, candidate, *, defer=False, abort_before=False):
        self.candidate, self.defer, self.abort_before = candidate, defer, abort_before
        self.requests, self.counted = [], []

    def for_handoff(self, max_tokens):
        return self

    def context_input(self, messages, tools):
        self.counted.append(deepcopy(messages))
        return {"messages": messages, "tools": tools}

    def context_token_measure(self, value):
        text = value["messages"][-1].get("content", "")
        if self.defer and MARKER in text:
            payload = json.JSONDecoder().raw_decode(text.split(MARKER)[1])[0]
            if payload["sources"]:
                return self.context_limit, "fixture_normalized_count"
        return 100, "fixture_normalized_count"

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy(messages))
        yield ModelChunk(kind="tool_use", tool_use=ToolUse("next", "TodoWrite", self.candidate))


async def invoke(model, rows, messages=None, abort=None):
    messages = messages or [{"role": "assistant", "content": "上一代工作状态"}]
    before = deepcopy((rows, messages))
    result = await generate(model, messages, rows, TodoWriteTool().schema(), abort or AbortController(),
                            account=lambda value: None, scope_protocol=True)
    assert (rows, messages) == before
    return result


@pytest.mark.asyncio
async def test_production_generate_ab_really_sends_original_and_measures_same_request():
    rows, candidate = chained(3)
    old = Model(candidate)
    with patch("memory.wsc_handoff_anchors.materialize", return_value=None):
        before = await invoke(old, rows)
    assert "ANCHOR-917" not in old.requests[0][-1]["content"]
    assert not next(r for r in before.presentation["sources"] if r["message_id"] == "original")["complete"]
    current = Model(candidate)
    result = await invoke(current, rows)
    payload = json.loads(current.requests[0][-1]["content"].split(MARKER)[1])
    assert payload["sources"][0]["content"] == ORIGINAL
    assert current.requests[0] in current.counted
    assert next(r for r in result.presentation["sources"] if r["message_id"] == "original")["complete"]


@pytest.mark.asyncio
async def test_deferred_anchor_is_not_counted_as_presented():
    rows, candidate = chained()
    current = Model(candidate, defer=True)
    result = await invoke(current, rows)
    payload = json.loads(current.requests[0][-1]["content"].split(MARKER)[1])
    assert payload["deferred_message_ids"] == ["original"] and not payload["sources"]
    assert not next(r for r in result.presentation["sources"] if r["message_id"] == "original")["complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize('defer', [False, True])
async def test_original_exposure_is_recorded_when_model_keeps_parent_citation(defer):
    rows, candidate = chained()
    candidate['checkpoint']['context_message_ids'] = ['cp1', 'cp2']
    for field in ('decisions', 'constraints'):
        candidate['checkpoint'][field][0]['source_message_id'] = 'cp2'
    current = Model(candidate, defer=defer)
    result = await invoke(current, rows)
    assert 'original' not in result.input['checkpoint']['context_message_ids']
    observed = next(r for r in result.presentation['sources'] if r['message_id'] == 'original')
    assert observed['complete'] is not defer


@pytest.mark.asyncio
async def test_original_already_in_main_request_is_not_duplicated():
    rows, candidate = chained()
    current = Model(candidate)
    result = await invoke(current, rows, messages=[deepcopy(rows[0])])
    assert MARKER not in current.requests[0][-1]["content"]
    assert next(r for r in result.presentation["sources"] if r["message_id"] == "original")["complete"]


@pytest.mark.asyncio
async def test_cancelled_request_never_sends_anchor():
    rows, candidate = chained()
    model, abort = Model(candidate), AbortController()
    abort.abort("fixture")
    with pytest.raises(ValueError, match="handoff_cancelled"):
        await invoke(model, rows, abort=abort)
    assert not model.requests
