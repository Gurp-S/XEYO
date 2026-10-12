from copy import deepcopy
import json

import pytest

from synaptic.task_checkpoint import validate
from synaptic.task_observations import normalize, resolve, validate_sources, ENV
from tests.wsc._fixtures import declared_report_phase, msg_asst_use, msg_tool
from tests.wsc.test_task_continuity import receipt, task


def source():
    return [{'id': 'spec', 'role': 'user', 'content': '核对当前报告'}] + [
        msg_asst_use('evidence', 'Read', {'file_path': 'report.txt'}),
        msg_tool('evidence', 'Read', 'unrelated ' * 400 + '\nobserved_total=137\n' + 'background ' * 400)]


def checkpoint():
    return {'objective': '核对报告', 'context_message_ids': ['spec'],
        'phase_state': declared_report_phase(), 'verification_call_ids': ['evidence'],
        'observations': [{'call_id': 'evidence', 'phase_id': 'report', 'quote': 'observed_total=137'}]}


def test_exact_quote_is_small_and_bound_without_heating_entire_result(monkeypatch, tmp_path):
    from synaptic.project import project
    from memory.wsc_projection import production_params
    monkeypatch.setenv(ENV, '1')
    rows = source()
    original = deepcopy(rows)
    c = validate(checkpoint())
    facts, unknown, nodes = resolve(rows, c, len(rows))
    assert not unknown and facts[0]['quote'] == 'observed_total=137' and nodes == (1, 2)
    validate_sources({'checkpoint': c, 'todos': [{'status': 'pending'}]}, rows)
    rows += receipt('checkpoint', [task()], c)
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / 'cold.txt')
    state = json.loads(next(pin.text for pin in output.result.hot.pins if pin.key == 'task_checkpoint'))
    assert state['execution_observations'][0]['call_id'] == 'evidence'
    assert not state['verification_receipts'][0]['result_inline']
    assert '执行观察（原文片段）' in output.text and 'observed_total=137' in output.text
    assert source() == original


@pytest.mark.parametrize('damage', ['quote', 'duplicate', 'before_call', 'incomplete', 'cancelled'])
def test_uncertified_result_cannot_supply_observation(damage):
    rows, c = source(), validate(checkpoint())
    if damage == 'quote':
        c['observations'][0]['quote'] = 'invented'
    elif damage == 'duplicate':
        rows.append(deepcopy(rows[-1]))
    elif damage == 'before_call':
        rows[1], rows[2] = rows[2], rows[1]
    else:
        rows[-1]['content'][0]['execution'] = {'complete': False} if damage == 'incomplete' else {'status': 'cancelled'}
    with pytest.raises(ValueError, match='handoff_observation_source_not_verified'):
        validate_sources({'checkpoint': c}, rows)


def test_phase_scoping_and_same_phase_omission_barrier():
    rows, c = source(), validate(checkpoint())
    rows += receipt('checkpoint', [task()], c)
    omitted = deepcopy(c)
    omitted.pop('observations')
    with pytest.raises(ValueError, match='observation_omitted'):
        validate_sources({'checkpoint': omitted, 'todos': [{'status': 'pending'}]}, rows)
    changed = deepcopy(c)
    changed['phase_state']['phases'].append({'id': 'next', 'name': 'next', 'source_message_ids': ['spec']})
    changed['phase_state']['current_phase_id'] = 'next'
    facts, unknown, _ = resolve(rows, changed, len(source()))
    assert not facts and not unknown


@pytest.mark.parametrize('damage', ['phase', 'unbound', 'duplicate', 'size'])
def test_observation_structure_has_bounded_explicit_identity(damage):
    c = checkpoint()
    if damage == 'phase': c['observations'][0]['phase_id'] = 'missing'
    elif damage == 'unbound': c['verification_call_ids'] = []
    elif damage == 'duplicate': c['observations'] *= 2
    else: c['observations'][0]['quote'] = 'x' * 8192
    with pytest.raises(ValueError):
        validate(c)


def test_tool_schema_is_candidate_only(monkeypatch):
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    monkeypatch.delenv(ENV, raising=False)
    assert 'observations' not in TodoWriteTool().schema()['input_schema']['properties']['checkpoint']['properties']
    monkeypatch.setenv(ENV, '1')
    schema = TodoWriteTool().schema()['input_schema']['properties']['checkpoint']['properties']
    assert schema['observations']['maxItems'] == 16 and 'phase_state' in schema
