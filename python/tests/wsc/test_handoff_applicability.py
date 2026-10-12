from copy import deepcopy

import pytest

from tests.wsc.test_task_phase import declaration, sources
from tests.wsc.test_task_continuity import receipt


def prepared():
    raw = declaration()
    rows = sources() + receipt('base-call', raw['todos'], raw['checkpoint'])
    rows[-1]['id'] = 'base'
    return rows, deepcopy(raw)


@pytest.mark.parametrize('change', ['task', 'rebind', 'reactivate'])
def test_old_phase_quote_cannot_expand_applicability_without_subsequent_witness(change):
    from memory.wsc_handoff_validation import validate
    rows, raw = prepared()
    phase = raw['checkpoint']['phase_state']
    if change == 'task':
        phase['fact_scopes']['constraints'][0] = {'kind': 'task'}
    elif change == 'rebind':
        phase['fact_scopes']['constraints'][0]['phase_id'] = 'implementation'
    else:
        phase['current_phase_id'] = 'design'
    error = 'handoff_phase_transition_source_missing' if change == 'reactivate' else 'handoff_fact_applicability_event_missing'
    with pytest.raises(ValueError, match=error):
        validate(raw, rows)
    rows.append({'id': 'new-event', 'role': 'user', 'content': '重新审查该约束的适用范围。'})
    raw['checkpoint']['context_message_ids'].append('new-event')
    current = next(record for record in phase['phases'] if record['id'] == phase['current_phase_id'])
    current['source_message_ids'].append('new-event')
    assert validate(raw, rows).checkpoint['phase_state'] == phase


def test_phase_only_previous_state_cannot_be_stripped_to_bypass_applicability():
    from memory.wsc_handoff_validation import validate
    from memory.wsc_handoff_generation import source_schema
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows, raw = prepared()
    # No task-wide facts: this must not depend on fact_disposition's separate guard.
    raw['checkpoint']['phase_state']['fact_scopes']['constraints'][-1] = {'kind': 'phase', 'phase_id': 'implementation'}
    rows = sources() + receipt('base-call', raw['todos'], raw['checkpoint'])
    rows[-1]['id'] = 'base'
    generated, _ = source_schema(TodoWriteTool().schema(), rows)
    assert generated['input_schema']['allOf'][0]['then']['properties']['checkpoint']['required'] == ['phase_state']
    del raw['checkpoint']['phase_state']
    with pytest.raises(ValueError, match='handoff_phase_state_required'):
        validate(raw, rows)


@pytest.mark.parametrize('event', ['old', 'duplicate', 'machine', 'cancelled'])
def test_reactivation_witness_must_be_new_unique_observed_source(event):
    from memory.wsc_handoff_validation import validate
    rows, raw = prepared()
    phase = raw['checkpoint']['phase_state']
    phase['fact_scopes']['constraints'][0] = {'kind': 'task'}
    if event == 'old':
        uid = 'permit'
    else:
        uid = 'new-event'
        row = {'id': uid, 'role': 'user', 'content': '新事件'}
        if event == 'machine': row['note_key'] = 'context_fact'
        if event == 'cancelled':
            row = {'id': uid, 'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'unknown',
                    'content': 'cancelled', 'execution': {'status': 'cancelled'}}]}
        rows.append(row)
        if event == 'duplicate': rows.append(deepcopy(row))
        raw['checkpoint']['context_message_ids'].append(uid)
        phase['phases'][1]['source_message_ids'].append(uid)
    with pytest.raises(ValueError):
        validate(raw, rows)


def test_unchanged_scopes_and_explicit_terminal_state_remain_valid():
    from memory.wsc_handoff_validation import validate
    rows, raw = prepared()
    original = deepcopy(rows)
    assert validate(raw, rows).checkpoint == raw['checkpoint']
    raw['todos'] = []
    del raw['checkpoint']['phase_state']
    validate(raw, rows)
    assert rows == original
