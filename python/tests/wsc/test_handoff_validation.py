from copy import deepcopy
import pytest

from memory.wsc_handoff_validation import validate
from tests.wsc._fixtures import msg_asst_use, msg_tool


def fixture():
    rows = [{"role": "user", "id": "spec", "content": "当前规范"},
            msg_asst_use("verify", "Bash", {}), msg_tool("verify", "Bash", "failed", is_error=True)]
    state = {"todos": [{"id": "report", "content": "写验收报告", "activeForm": "写报告", "status": "pending"}],
             "checkpoint": {"objective": "完成当前规范", "context_message_ids": ["spec"],
                            "verification_call_ids": ["verify"]}}
    return rows, state


def test_model_handoff_validates_sources_without_inventing_verification_success():
    rows, state = fixture()
    original = deepcopy((rows, state))
    parsed = validate(state, rows)
    assert parsed.checkpoint["verification_call_ids"] == ["verify"]
    assert parsed.todos[0].status == "pending"
    assert (rows, state) == original


@pytest.mark.parametrize("kind", ["missing_context", "duplicate_context", "missing_receipt", "duplicate_call", "incomplete"])
def test_invalid_or_incomplete_provenance_cannot_publish_handoff(kind):
    rows, state = fixture()
    if kind == "missing_context": rows[0]["id"] = "different"
    if kind == "duplicate_context": rows.append(deepcopy(rows[0]))
    if kind == "missing_receipt": rows.pop()
    if kind == "duplicate_call": rows.insert(1, deepcopy(rows[1]))
    if kind == "incomplete": rows[-1]["content"][0]["execution"] = {"complete": False}
    with pytest.raises(ValueError): validate(state, rows)


@pytest.mark.parametrize("kind", ["merge", "duplicate_steps", "missing_step_id", "missing_checkpoint", "active_without_context"])
def test_only_full_explicit_state_can_enter_handoff_protocol(kind):
    rows, state = fixture()
    if kind == "merge": state["merge"] = True
    if kind == "duplicate_steps": state["todos"].append(deepcopy(state["todos"][0]))
    if kind == "missing_step_id": state["todos"][0].pop("id")
    if kind == "missing_checkpoint": state.pop("checkpoint")
    if kind == "active_without_context": state["checkpoint"]["context_message_ids"] = []
    with pytest.raises(ValueError): validate(state, rows)
