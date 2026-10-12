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


def recovered_fixture():
    from session.recovery_result_chain import observation
    rows, state = fixture()
    rows[1]['id'] = 'origin'
    actual = deepcopy(rows[-1])
    actual['id'] = 'actual-result'
    actual['content'][0]['execution'] = {'complete': True, 'status': 'error'}
    rows[-1]['id'] = 'recovery-observation'
    rows[-1]['content'][0].update(content='outcome unavailable', execution={
        'complete': False, 'recovery_observation': observation(rows[1], 'verify')})
    return rows + [actual], state


def test_typed_recovery_actual_result_has_same_identity_in_catalog_and_handoff():
    from memory.wsc_handoff_catalog import Catalog
    rows, state = recovered_fixture()
    original = deepcopy((rows, state))
    catalog = Catalog(rows)
    assert catalog.verification_ids == ['verify']
    assert 'verification_call_ids' not in catalog.records[2]
    assert catalog.records[3]['verification_call_ids'] == ['verify']
    assert validate(state, rows).checkpoint['verification_call_ids'] == ['verify']
    assert (rows, state) == original


@pytest.mark.asyncio
async def test_recovered_result_can_commit_after_fold_without_changing_frozen_head(tmp_path):
    from engine.abort import AbortController
    from evals.wsc_unfolded_source_ab import environment
    from evals.wsc_flash_compact_chain import native_store
    from memory import wsc_projection
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory.wsc_handoff_transaction import commit
    from msgtypes.message import ToolUse
    from session.compression_source import compression_messages
    from session.record_transcript import record_transcript_sync
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from tests.wsc._fixtures import declared_report_phase
    rows, state = recovered_fixture()
    state['checkpoint']['phase_state'] = declared_report_phase()
    rows += [{'id': f'consumed-{index}', 'role': 'assistant', 'content': '执行回执已观察'} for index in range(20)]
    with environment(tmp_path):
        import os
        os.environ['XEYO_WSC'] = '1'
        store = native_store(rows)
        source = lambda: compression_messages(store, WorkingSnapshot())
        prior = deepcopy(source())
        working = WorkingSnapshot(session_id='recovered-handoff-contract')
        wsc_projection._STATE.pop(working.session_id, None)
        first = force_compact(prior, working, cwd=tmp_path)
        first_cursor = working.compact_cursor
        assert first_cursor > 3  # Both recovery observation and actual result are cold.
        registry = ToolRegistry(cwd=str(tmp_path))
        registry.register(TodoWriteTool(cwd=str(tmp_path)))
        known = set()
        def persist():
            record_transcript_sync(store.items, session_id=working.session_id,
                path=tmp_path/'transcript.jsonl', known_ids=known)
        persist()
        prefix = (tmp_path/'transcript.jsonl').read_bytes()
        async def declaration(captured): return ToolUse('valid-handoff', 'TodoWrite', deepcopy(state))
        await commit(source=source, generate=declaration, store=store, tools=registry,
            abort=AbortController(), persist=persist, require_phase=True)
        extended = source()
        assert extended[:len(prior)] == prior
        assert (tmp_path/'transcript.jsonl').read_bytes().startswith(prefix)
        assert project_for_model(extended, working, cwd=tmp_path, capacity_managed=True)[0] == first[0]
        final = force_compact(extended, working, cwd=tmp_path)
        assert working.compact_cursor > first_cursor
        flush(working.session_id, working)
        wsc_projection._STATE.pop(working.session_id, None)
        restored = hydrate(working.session_id, source_layout=working.compression_source_layout)
        assert project_for_model(extended, restored, cwd=tmp_path, capacity_managed=True) == final


@pytest.mark.parametrize('damage', ['untyped', 'wrong_hash', 'duplicate_actual', 'incomplete_actual', 'reversed_results'])
def test_recovered_handoff_keeps_ambiguous_and_incomplete_results_rejected(damage):
    from memory.wsc_handoff_catalog import Catalog
    rows, state = recovered_fixture()
    if damage == 'untyped': rows[2]['content'][0]['execution'].pop('recovery_observation')
    elif damage == 'wrong_hash': rows[2]['content'][0]['execution']['recovery_observation']['invocation_sha256'] = 'wrong'
    elif damage == 'duplicate_actual': rows.append(deepcopy(rows[-1]))
    elif damage == 'incomplete_actual': rows[-1]['content'][0]['execution']['complete'] = False
    else: rows[2], rows[3] = rows[3], rows[2]
    assert 'verify' not in Catalog(rows).verification_ids
    with pytest.raises(ValueError): validate(state, rows)


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
