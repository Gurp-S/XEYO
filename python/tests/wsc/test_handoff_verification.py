from copy import deepcopy

import pytest

from memory.wsc_handoff_verification import validate, VerificationError
from tests.wsc.test_handoff_fact_disposition import prepared
from tests.wsc._fixtures import msg_asst_use, msg_tool


@pytest.mark.parametrize('replacement', [[], ['checkpoint']])
def test_no_new_verification_cannot_erase_binding(replacement):
    rows, raw = prepared()
    raw['checkpoint']['verification_call_ids'] = replacement
    before = deepcopy(rows)
    with pytest.raises(VerificationError) as caught:
        validate(raw, rows)
    assert caught.value.detail['omitted_verification_call_ids'] == ['verify']
    assert rows == before


def test_preserving_binding_and_order_does_not_require_a_new_result():
    rows, raw = prepared()
    validate(raw, rows)
    raw['checkpoint']['verification_call_ids'].append('checkpoint')
    validate(raw, rows)


@pytest.mark.parametrize('broken', [None, 'duplicate', 'cancelled', 'incomplete', 'handoff', 'unselected', 'malformed'])
def test_new_receipt_does_not_retire_prior_active_phase_verification(broken):
    rows, raw = prepared()
    rows += [msg_asst_use('fresh', 'Bash', {'command': 'verify'}), msg_tool('fresh', 'Bash', 'failed', is_error=True)]
    raw['checkpoint']['verification_call_ids'] = ['fresh'] if broken != 'unselected' else []
    if broken == 'duplicate': rows.append(deepcopy(rows[-1]))
    if broken == 'malformed': rows[-1]['content'][0]['execution'] = 'invalid execution metadata'
    if broken in {'cancelled', 'incomplete', 'handoff'}:
        rows[-1]['content'][0]['execution'] = {
            'cancelled': {'status': 'cancelled'}, 'incomplete': {'complete': False},
            'handoff': {'compaction_handoff': True}}[broken]
    with pytest.raises(VerificationError): validate(raw, rows)


def test_late_result_does_not_implicitly_replace_another_verification():
    rows, raw = prepared()
    rows.insert(0, msg_asst_use('late', 'Bash', {'command': 'verify'}))
    rows.append(msg_tool('late', 'Bash', 'actual failed', is_error=True))
    raw['checkpoint']['verification_call_ids'] = ['late']
    with pytest.raises(VerificationError): validate(raw, rows)
    raw['checkpoint']['verification_call_ids'].append('verify')
    validate(raw, rows)


def test_additional_successful_receipt_can_extend_active_verification_bindings():
    rows, raw = prepared()
    rows += [msg_asst_use('fresh', 'Write', {'content': 'new report'}),
             msg_tool('fresh', 'Write', 'written')]
    raw['checkpoint']['verification_call_ids'].append('fresh')
    validate(raw, rows)


@pytest.mark.asyncio
async def test_generation_rejects_unrelated_new_receipt_then_preserves_bindings():
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows, raw = prepared()
    rows += [msg_asst_use('fresh', 'Write', {'content': 'new report'}),
             msg_tool('fresh', 'Write', 'written')]
    calls = []
    before = deepcopy(rows)
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, schemas, abort):
            candidate = deepcopy(raw)
            candidate['checkpoint']['verification_call_ids'] = ['fresh'] if not calls else ['verify', 'fresh']
            if calls:
                assert 'handoff_active_phase_verification_bindings_omitted' in str(messages[-1])
                assert 'omitted_verification_call_ids' in str(messages[-1])
            calls.append(True)
            yield ModelChunk(kind='tool_use', tool_use=ToolUse(f'declare-{len(calls)}', 'TodoWrite', candidate))
    result = await generate(Model(), [{'role': 'user', 'content': 'fixture'}], rows,
        TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    assert result.input['checkpoint']['verification_call_ids'] == ['verify', 'fresh']
    assert len(calls) == 2 and rows == before


def test_explicit_phase_and_terminal_transitions_use_existing_contracts():
    rows, raw = prepared()
    raw['checkpoint']['verification_call_ids'] = []
    raw['checkpoint']['phase_state']['current_phase_id'] = 'different'
    validate(raw, rows)  # Full validation separately rejects an invalid phase.
    rows, raw = prepared()
    raw['checkpoint']['verification_call_ids'] = []
    for item in raw['todos']: item['status'] = 'completed'
    validate(raw, rows)  # Full validation separately requires a progress witness.


def test_legacy_and_unobserved_state_remain_compatible():
    rows, raw = prepared()
    validate(raw, rows[:5])
    rows, raw = prepared()
    # No existing explicitly phased base checkpoint.
    from tests.wsc.test_task_continuity import receipt, task
    legacy = {'objective': 'old', 'context_message_ids': ['permit'], 'verification_call_ids': ['verify']}
    rows = rows[:5] + receipt('legacy', [task('report', 'pending')], legacy)
    raw['checkpoint']['verification_call_ids'] = []
    validate(raw, rows)


@pytest.mark.parametrize('witness', [False, True])
@pytest.mark.parametrize('transition', ['phase', 'terminal'])
def test_full_validation_keeps_transition_witnesses_required(transition, witness):
    from memory.wsc_handoff_validation import validate as validate_full
    rows, raw = prepared()
    raw['checkpoint']['verification_call_ids'] = []
    if transition == 'phase':
        phase = raw['checkpoint']['phase_state']
        phase['phases'].append({'id': 'next-phase', 'name': 'next phase',
                               'source_message_ids': ['next' if witness else 'permit']})
        phase['current_phase_id'] = 'next-phase'
        if witness:
            raw['checkpoint']['context_message_ids'].append('next')
    else:
        for item in raw['todos']: item['status'] = 'completed'
        if witness:
            raw['checkpoint']['context_message_ids'].append('next')
    if witness:
        validate_full(raw, rows, require_phase=True)
    else:
        with pytest.raises(ValueError, match='transition_source_missing|progress_source_missing'):
            validate_full(raw, rows, require_phase=True)
