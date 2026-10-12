"""A node's graph kind cannot erase its explicitly bound message text."""
from copy import deepcopy

import pytest

from synaptic.graph import build_graph
from synaptic.task_checkpoint import project_state
from synaptic.task_fact_sources import source_text
from tests.wsc.test_task_continuity import receipt, task


def state_for(row):
    rows = [row] + receipt("checkpoint", [task()], {
        "objective": "continue the declared task", "context_message_ids": ["bound"]})
    before = deepcopy(rows)
    graph = build_graph(rows)
    state, nodes = project_state(rows, graph)
    assert rows == before
    return state, nodes, graph


def test_mixed_assistant_text_uses_the_same_source_contract_as_citations():
    row = {"id": "bound", "role": "assistant", "content": [
        {"type": "reasoning", "text": "private analysis"},
        {"type": "text", "text": "work completed\nverification pending"},
        {"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": "x" * 40000}},
        {"type": "text", "text": "the next step is declared separately"}]}
    state, nodes, graph = state_for(row)
    assert graph.node(0).kind == "tool_use"
    assert state["unknown_sources"] == []
    assert state["deferred_sources"] == []
    assert state["context_sources"] == [{"message_id": "bound", "source": 0, "text": source_text(row)}]
    assert "private analysis" not in state["context_sources"][0]["text"]
    assert "x" * 100 not in state["context_sources"][0]["text"]
    assert 0 in nodes  # The full original node is still bound for cold recall.


@pytest.mark.parametrize("row", [
    {"id": "bound", "role": "assistant", "content": [
        {"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": "spec"}}]},
    {"id": "bound", "role": "assistant", "content": [{"type": "reasoning", "text": "not task text"}]},
    {"id": "bound", "role": "user", "note_key": "engine_state", "content": "not human task text"},
])
def test_call_reasoning_and_engine_notes_do_not_become_text_sources(row):
    state, _, _ = state_for(row)
    assert state["context_sources"] == []
    assert state["unknown_sources"] == [{"message_id": "bound", "reason": "not_text"}]
