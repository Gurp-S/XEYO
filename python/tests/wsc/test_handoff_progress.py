from copy import deepcopy

import pytest

from memory.wsc_handoff_progress import validate, ProgressError
from tests.wsc.test_handoff_fact_disposition import prepared
from tests.wsc._fixtures import msg_asst_use, msg_tool


def changed():
    rows, raw = prepared()
    raw["todos"][0]["status"] = "completed"
    return rows, raw


def test_old_context_cannot_ground_new_completion():
    rows, raw = changed()
    with pytest.raises(ProgressError, match="progress_source_missing"):
        validate(raw, rows)


def test_rejection_identifies_actual_new_events_without_declaring_completion():
    rows, raw = changed()
    with pytest.raises(ProgressError) as caught:
        validate(raw, rows)
    assert caught.value.detail["observed_events_after_checkpoint"] == [
        {"source": len(rows)-1, "message_id": "next", "role": "user"}]
    assert "completed" not in str(caught.value.detail["observed_events_after_checkpoint"])


def test_catalog_first_page_contains_newest_delta_despite_tool_flood():
    from memory.wsc_handoff_catalog import Catalog
    rows, raw = prepared()
    rows += [msg_asst_use(f"read-{i}", "Read", {"file_path": "log.txt"}) for i in range(100)]
    rows.append({"id": "fresh-report", "role": "assistant", "content": "实际汇报正文"})
    before = deepcopy(rows)
    page = Catalog(rows).initial()
    assert page[0]["message_id"] == "base" and page[1]["message_id"] == "fresh-report"
    assert len(page) <= 32 and rows == before


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_new_unique_bound_text_grounds_declaration_and_preserves_source(role):
    rows, raw = changed()
    rows[-1]["role"] = role
    before = deepcopy(rows)
    raw["checkpoint"]["context_message_ids"].append("next")
    validate(raw, rows)
    assert rows == before


@pytest.mark.parametrize("broken", [None, "duplicate", "cancelled", "old"])
def test_observed_verification_grounds_progress_but_old_or_invalid_receipts_do_not(broken):
    rows, raw = changed()
    if broken != "old":
        rows += [msg_asst_use("fresh", "Bash", {"command": "verify"}),
                 msg_tool("fresh", "Bash", "verification failed", is_error=True)]
        raw["checkpoint"]["verification_call_ids"].append("fresh")
    if broken == "duplicate": rows.append(msg_tool("fresh", "Bash", "duplicate"))
    if broken == "cancelled": rows[-1]["content"][0]["execution"] = {"status": "cancelled"}
    if broken:
        with pytest.raises(ProgressError): validate(raw, rows)
    else: validate(raw, rows)


def test_duplicate_and_machine_text_are_not_progress_sources():
    for machine in (False, True):
        rows, raw = changed()
        raw["checkpoint"]["context_message_ids"].append("next")
        if machine: rows[-1]["note_key"] = "world_state"
        else: rows.append(deepcopy(rows[-1]))
        with pytest.raises(ProgressError): validate(raw, rows)


def test_unchanged_state_and_legacy_do_not_invent_progress_events():
    rows, raw = prepared()
    validate(raw, rows)
    rows, raw = changed()
    # The historical fixture uses a committed explicitly scoped receipt.
    # No prior task state means the contract has no lifecycle to compare.
    validate(raw, rows[:5])


@pytest.mark.parametrize("origin_before_checkpoint", [False, True])
@pytest.mark.parametrize("broken", [None, "wrong_binding", "untyped", "duplicate", "cancelled", "incomplete"])
def test_recovered_actual_result_grounds_progress_and_phase_with_same_identity(broken, origin_before_checkpoint):
    from session.recovery_result_chain import observation
    from memory.wsc_handoff_phase import observed_source, validate as validate_phase
    rows, raw = changed()
    origin = dict(msg_asst_use("fresh", "Bash", {"command": "verify"}), id="fresh-origin")
    unknown = dict(msg_tool("fresh", "Bash", "outcome unavailable", is_error=True), id="unknown")
    unknown['content'][0]['execution'] = {'complete': False, 'recovery_observation': observation(origin, 'fresh')}
    actual = dict(msg_tool("fresh", "Bash", "verification failed", is_error=True), id="actual")
    actual['content'][0]['execution'] = {'complete': True, 'status': 'error'}
    if broken == "wrong_binding": unknown['content'][0]['execution']['recovery_observation']['invocation_sha256'] = 'wrong'
    elif broken == "untyped": unknown['content'][0]['execution'].pop('recovery_observation')
    elif broken == "cancelled": actual['content'][0]['execution']['status'] = 'cancelled'
    elif broken == "incomplete": actual['content'][0]['execution']['complete'] = False
    if origin_before_checkpoint:
        rows[5:5] = [origin, unknown]
        rows.append(actual)
    else:
        rows += [origin, unknown, actual]
    if broken == "duplicate": rows.append(deepcopy(actual))
    before = deepcopy(rows)
    index = len(rows)-1
    raw['checkpoint']['verification_call_ids'].append('fresh')
    phase_raw = deepcopy(raw)
    phase_raw['checkpoint']['context_message_ids'].append('actual')
    phase = phase_raw['checkpoint']['phase_state']
    phase['current_phase_id'] = 'verification'
    phase['phases'].append({'id':'verification','name':'验收','source_message_ids':['actual']})
    if broken:
        assert observed_source(rows, index) is False
        with pytest.raises(ProgressError): validate(raw, rows)
        with pytest.raises(ValueError, match='handoff_phase_source_invalid'): validate_phase(phase_raw, rows)
    else:
        assert observed_source(rows, index) is True
        validate(raw, rows)
        validate_phase(phase_raw, rows)
    assert rows == before


@pytest.mark.asyncio
async def test_generation_can_bind_new_report_without_reverting_its_status():
    import json
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows, raw = changed()
    rows[-1]["role"] = "assistant"
    rows[-1]["content"] = "完整验收报告已经生成，等待用户决定是否并入。"
    before, requests = deepcopy(rows), []
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, schemas, abort):
            candidate = deepcopy(raw)
            if requests:
                error = json.loads(messages[-1]["content"][0]["content"])
                assert error["error"] == "handoff_progress_source_missing"
                candidate["checkpoint"]["context_message_ids"].append("next")
            requests.append(deepcopy(messages))
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"declare-{len(requests)}", "TodoWrite", candidate))
    result = await generate(Model(), [{"role": "assistant", "content": rows[-1]["content"]}], rows,
                            TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    assert result.input["todos"][0]["status"] == "completed"
    assert "next" in result.input["checkpoint"]["context_message_ids"]
    assert len(requests) == 2 and rows == before
