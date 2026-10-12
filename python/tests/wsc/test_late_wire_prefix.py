"""Completed native calls and already-displaced calls keep their sent prefix."""
from copy import deepcopy
import json

import pytest

from tests.wsc.test_late_media_identity import IMAGE


def invocation(uid):
    return {"role": "assistant", "id": "invoke-" + uid, "content": [
        {"type": "tool_use", "id": uid, "name": "Read", "input": {"file_path": uid + ".txt"}}]}


def result(uid, body):
    return {"role": "tool", "id": "result-" + uid, "tool_call_id": uid, "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": body}]}


def assert_wire_prefix(old, new):
    assert new[:len(old) - 1] == old[:-1]
    tail = new[len(old) - 1]
    # Anthropic joins adjacent user carriers; existing content remains the
    # beginning of the last carrier, rather than falsely counting a new role.
    assert {key: value for key, value in tail.items() if key != "content"} == {
        key: value for key, value in old[-1].items() if key != "content"}
    previous = old[-1]["content"]
    if isinstance(previous, list):
        assert tail["content"][:len(previous)] == previous
    else:
        assert tail["content"].startswith(previous)


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
@pytest.mark.parametrize("boundary_role", ["assistant", "user"])
@pytest.mark.parametrize("media", [False, True])
def test_actual_encoder_prefix_survives_late_arrival(monkeypatch, provider, boundary_role, media):
    from model.deepseek import DeepSeekModelClient
    from model.anthropic import AnthropicModelClient
    from prompt.assembler import PromptAssembler
    from session.late_result_guard import request_conflict
    from session.late_result_projection import ENV
    monkeypatch.setenv(ENV, "1")
    rows = [{"role": "user", "id": "goal", "content": "current task"}, invocation("completed"),
            result("completed", "observed completed receipt"), invocation("late"),
            {"role": boundary_role, "id": "boundary", "content": "actual event"},
            invocation("normal"), result("normal", "normal result=74")]
    original = deepcopy(rows)
    prompt = PromptAssembler()
    prior = prompt.build("fixture", rows)
    assert request_conflict(rows) is None
    client = (DeepSeekModelClient(api_key="not-sent", model="deepseek-flash") if provider == "deepseek"
              else AnthropicModelClient(api_key="not-sent", model="claude-test"))
    build = client._build_body
    prior_wire = build(prior, [], stream=False)["messages"]
    late_body = ([{"type": "text", "text": "late result=137"}, deepcopy(IMAGE)] if media else "late result=137")
    extended = rows + [result("late", late_body)]
    current = prompt.build("fixture", extended)
    assert request_conflict(extended) is None
    assert current[:len(prior)] == prior
    wire = build(current, [], stream=False)["messages"]
    assert_wire_prefix(prior_wire, wire)
    assert "late result=137" in json.dumps(wire)
    assert "normal result=74" in json.dumps(wire)
    assert rows == original


def test_a_native_pending_call_before_displacement_is_not_a_supported_sent_generation(monkeypatch):
    from session.hydrate import message_from_row
    from session.late_result_projection import ENV, supported, project
    monkeypatch.setenv(ENV, "1")
    rows = [{"role": "user", "content": "task"}, invocation("pending")]
    assert not supported([message_from_row(row) for row in rows])
    assert project(rows) == rows
