from copy import deepcopy
import pytest

from memory.wsc_handoff_facts import validate_facts
from synaptic.task_checkpoint import validate, from_result


def declaration(quote="文件存在不作为成功证据", source="spec"):
    return {"checkpoint": {"objective": "当前任务", "context_message_ids": [source],
        "decisions": [{"source_message_id": source, "quote": quote}], "constraints": []}}


def test_source_quote_survives_checkpoint_serialization_without_rewriting():
    import json
    sources = [{"role": "user", "message_id": "spec", "content": "决定：文件存在不作为成功证据。"}]
    raw = declaration()
    original = deepcopy(raw)
    validate_facts(raw, sources, require_citations=True)
    compiled = validate(raw["checkpoint"])
    assert from_result("<task_checkpoint>" + json.dumps(compiled, ensure_ascii=False) + "</task_checkpoint>") == compiled
    assert raw == original


@pytest.mark.parametrize("kind", ["protocol", "invented", "duplicate", "unbound", "note", "tool"])
def test_protocol_or_unverifiable_facts_are_rejected_by_source_not_words(kind):
    sources = [{"role": "user", "message_id": "spec", "content": "决定：文件存在不作为成功证据。"}]
    raw = declaration()
    if kind == "protocol": raw = declaration("本请求只生成交接，不执行原任务")
    if kind == "invented": raw = declaration(source="generation-request")
    if kind == "duplicate": sources.append(deepcopy(sources[0]))
    if kind == "unbound": raw["checkpoint"]["context_message_ids"] = []
    if kind == "note": sources[0]["note_key"] = "engine-protocol"
    if kind == "tool": sources[0]["role"] = "tool"
    with pytest.raises(ValueError): validate_facts(raw, sources, require_citations=True)


def test_same_literal_is_allowed_when_it_is_an_actual_task_source():
    phrase = "本请求只生成交接，不执行原任务"
    validate_facts(declaration(phrase), [{"role": "user", "message_id": "spec", "content": phrase}], require_citations=True)


def test_generated_strings_are_rejected_but_existing_declarations_stay_compatible():
    raw = {"checkpoint": {"decisions": ["原显式声明"], "constraints": []}}
    validate_facts(raw, [], require_citations=False)
    with pytest.raises(ValueError, match="citation_required"):
        validate_facts(raw, [], require_citations=True)


def test_default_tool_schema_is_not_mutated_by_citation_protocol():
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from memory.wsc_handoff_generation import source_schema
    original = TodoWriteTool().schema()
    constrained, _ = source_schema(original, [{"role": "user", "message_id": "spec", "content": "规范"}])
    field = constrained["input_schema"]["properties"]["checkpoint"]["properties"]["constraints"]
    assert field["items"]["type"] == "object"
    assert original == TodoWriteTool().schema()
