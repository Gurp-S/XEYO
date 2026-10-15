"""Independent task facts across completion, task replacement and late results."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from memory.wsc_handoff_validation import validate
from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot, flush, hydrate
from synaptic.project import project
from synaptic.todo_snapshot import latest_todo_snapshot
from tests.wsc._fixtures import declared_report_phase, msg_asst_use, msg_tool
from tests.wsc.test_task_continuity import receipt, task


def declaration(source_id, objective, call_id, task_id):
    return {'todos': [task(task_id, 'in_progress', objective)], 'checkpoint': {
        'objective': objective, 'context_message_ids': [source_id],
        'decisions': [], 'constraints': [], 'verification_call_ids': [call_id],
        'phase_state': declared_report_phase(source_id)}}


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('late_before_completion', [False, True])
@pytest.mark.parametrize('seed', ['delivery-address', 'ledger-baseline', 'build-receipt'])
def test_terminal_barrier_new_task_and_old_late_receipt(monkeypatch, tmp_path, native, late_before_completion, seed):
    from memory import wsc_projection
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_WSC', str(int(native)))
    wsc_projection._STATE.clear()
    # Expected state is constructed from distinct task/event facts, not output.
    token = hashlib.sha256(seed.encode()).hexdigest()[:12]
    old_goal, new_goal = f'old-{token}', f'current-{token}'
    rows = [{'id': 'old-source', 'role': 'user', 'content': old_goal},
            msg_asst_use('old-verify', 'Bash', {'command': seed}),
            msg_tool('old-verify', 'Bash', f'old-evidence-{token}')]
    old = declaration('old-source', old_goal, 'old-verify', 'old-task')
    validate(old, rows, require_phase=True)
    rows += receipt('old-checkpoint', old['todos'], old['checkpoint'])
    rows += [{'id': f'old-work-{i}', 'role': 'assistant', 'content': seed * (130 + i)} for i in range(30)]
    original = deepcopy(rows)
    working = WorkingSnapshot(session_id=f'lifecycle-{token}')
    first = force_compact(rows, working, cwd=tmp_path)
    assert working.compact_cursor > 0
    first_cursor = working.compact_cursor
    cold = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tmp_path.rglob('*.txt')}
    rows.append(msg_asst_use('old-late', 'Bash', {'command': f'old-async-{token}'}))
    late = msg_tool('old-late', 'Bash', f'late-old-result-{token}')
    if late_before_completion:
        rows.append(late)
    rows.append({'id': 'close-event', 'role': 'user', 'content': f'Closed task: {old_goal}'})
    closed = deepcopy(old)
    closed['todos'][0]['status'] = 'completed'
    closed['checkpoint']['context_message_ids'].append('close-event')
    validate(closed, rows, require_phase=True)
    rows += receipt('close-checkpoint', closed['todos'], closed['checkpoint'])
    rows += [{'id': 'new-source', 'role': 'user', 'content': new_goal},
             msg_asst_use('new-verify', 'Bash', {'command': f'new-{seed}'}),
             msg_tool('new-verify', 'Bash', f'new-evidence-{token}')]
    current = declaration('new-source', new_goal, 'new-verify', 'new-task')
    # Both tasks deliberately use the same phase label. Terminal state, not
    # accidental phase-name uniqueness, separates their verification lifetime.
    validate(current, rows, require_phase=True)
    rows += receipt('new-checkpoint', current['todos'], current['checkpoint'])
    if not late_before_completion:
        rows.append(late)
    rows += [{'id': f'new-work-{i}', 'role': 'assistant', 'content': seed * (180 + i)} for i in range(30)]
    assert project_for_model(rows, working, cwd=tmp_path)[0] == first[0]
    second = force_compact(rows, working, cwd=tmp_path)
    assert working.compact_cursor > first_cursor
    state = latest_todo_snapshot(rows)
    assert state.checkpoint['objective'] == new_goal
    assert state.checkpoint['verification_call_ids'] == ['new-verify']
    assert [item['id'] for item in state.records] == ['new-task']
    from memory.wsc_projection import production_params
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / 'audit.txt')
    pin = next(pin for pin in output.result.hot.pins if pin.key == 'task_checkpoint')
    parsed = json.loads(pin.text)
    assert parsed['declared_objective'] == new_goal
    assert [row['call_id'] for row in parsed['verification_receipts']] == ['new-verify']
    assert old_goal not in pin.text
    # A result may remain visible as a subsequent execution; that observation
    # does not make it a declared verification of the current task.
    executions = parsed.get('subsequent_executions', {}).get('inline_or_indexed', [])
    late_observations = [item for item in executions if item.get('call_id') == 'old-late']
    if not late_before_completion:
        assert len(late_observations) == 1
    assert all(item['task_association'] == 'undeclared' for item in late_observations)
    from synaptic.coldstore import node_group_handle
    from evals.stale_goal_ab import tool_read
    late_index = rows.index(late)
    _, ranges = output.cold.render_text_view()
    handle = node_group_handle((late_index,))
    if handle in ranges:
        start, end = ranges[handle]
        recalled = tool_read({'file_path': output.view_path, 'offset': start,
                              'limit': end - start + 1}, tmp_path)
        assert not recalled['is_error'], recalled['content']
        assert f'late-old-result-{token}' in recalled['content']
    else:
        assert f'late-old-result-{token}' in output.text
    assert rows[:len(original)] == original
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
               for path, sha in cold.items())
    flush(working.session_id, working)
    wsc_projection._STATE.clear()
    restored = hydrate(working.session_id, source_layout=None)
    assert project_for_model(rows, restored, cwd=tmp_path) == second
