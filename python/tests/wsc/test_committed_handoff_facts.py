import pytest

from memory.wsc_handoff_facts import committed_facts, validate_facts
from tests.wsc.test_task_continuity import receipt, task
from tests.wsc._fixtures import msg_asst_use, msg_tool


def checkpoint(identity="cp", decision="decimal_half_even", status="pending"):
    rows = receipt(identity, [task("verify", status)], {"objective": "当前精度验收",
        "decisions": [decision], "constraints": ["report references actual success"]})
    rows[-1]["message_id"] = identity + "-result"
    return rows


def cite(identity="cp-result", quote="decimal_half_even", field="decisions"):
    return {"checkpoint": {"context_message_ids": [identity], field: [{"source_message_id": identity, "quote": quote}]}}


def test_latest_committed_slot_is_source_without_admitting_whole_tool_output():
    rows = checkpoint()
    assert committed_facts(rows)["cp-result"]["decisions"] == ["decimal_half_even"]
    validate_facts(cite(), rows, require_citations=True)
    for quote in ("decimal", "Todo list stored", "当前精度验收"):
        with pytest.raises(ValueError): validate_facts(cite(quote=quote), rows, require_citations=True)
    with pytest.raises(ValueError): validate_facts(cite(field="constraints"), rows, require_citations=True)


@pytest.mark.parametrize("terminal", ["completed", "clear", "superseded"])
def test_terminal_or_superseded_declarations_cannot_resupply_current_facts(terminal):
    rows = checkpoint()
    if terminal == "completed": rows += receipt("close", [task("verify", "completed")])
    if terminal == "clear": rows += receipt("clear", [])
    if terminal == "superseded": rows += checkpoint("new", "decimal_half_up")
    with pytest.raises(ValueError): validate_facts(cite(), rows, require_citations=True)


def test_failed_declaration_does_not_replace_previous_source():
    rows = checkpoint()
    failed = checkpoint("failed", "invented")
    failed[-1]["content"][0]["is_error"] = True
    rows += failed
    validate_facts(cite(), rows, require_citations=True)
    with pytest.raises(ValueError): validate_facts(cite("failed-result", "invented"), rows, require_citations=True)


def test_tool_text_that_looks_like_checkpoint_is_not_a_state_authority():
    payload = checkpoint()[-1]["content"][0]["content"]
    rows = [msg_asst_use("read", "Read", {}), dict(msg_tool("read", "Read", payload), message_id="fake-result")]
    assert committed_facts(rows) == {}
    with pytest.raises(ValueError): validate_facts(cite("fake-result"), rows, require_citations=True)


def test_repeated_handoff_keeps_original_slot_provenance_in_projection():
    from synaptic.task_fact_sources import resolve
    from synaptic.task_checkpoint import project_state
    from synaptic.graph import build_graph
    rows = checkpoint()
    original = list(rows)
    for number in range(1, 17):
        prior = "cp-result" if number == 1 else f"next-{number - 1}-result"
        raw = cite(prior)
        validate_facts(raw, rows, require_citations=True)
        declaration = receipt(f"next-{number}", [task("verify", "pending")],
                              {"objective": "当前精度验收", **raw["checkpoint"]})
        declaration[-1]["message_id"] = f"next-{number}-result"
        rows += declaration
    assert rows[:2] == original
    assert len(resolve(rows, "next-16-result", "decisions", "decimal_half_even")) == 17
    state, nodes = project_state(rows, build_graph(rows))
    assert state["unknown_sources"] == []
    assert state["committed_fact_sources"][0]["facts"][0]["sources"][-1] == 1
    assert 1 in nodes


def test_invalid_inherited_quote_cannot_become_committed_authority():
    rows = checkpoint()
    inherited = cite(quote="decimal")
    declaration = receipt("next", [task("verify", "pending")],
                          {"objective": "当前精度验收", **inherited["checkpoint"]})
    declaration[-1]["message_id"] = "next-result"
    rows += declaration
    assert committed_facts(rows) == {}
    with pytest.raises(ValueError): validate_facts(cite("next-result", "decimal"), rows, require_citations=True)
