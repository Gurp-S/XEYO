"""New fallback generations preserve existing protected request/state pins."""
from copy import deepcopy

import pytest

from evals.wsc_recovered_result_behavior import fixture, actual
from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot, flush, hydrate


@pytest.mark.parametrize('native', [False, True])
def test_three_folds_keep_uncommitted_task_fact_and_late_result(monkeypatch, tmp_path, native):
    from memory import wsc_projection
    monkeypatch.setenv('XEYO_HOME', str(tmp_path/'home'))
    monkeypatch.setenv('XEYO_WSC', str(int(native)))
    wsc_projection._STATE.clear()
    source = fixture()
    original = deepcopy(source)
    working = WorkingSnapshot(session_id='fallback-continuity')
    first = force_compact(source, working, cwd=tmp_path)
    first_cursor = working.compact_cursor
    source += [{'id':f'new-{i}', 'role':'assistant', 'content':'sample_total=173 '+ 'archive '*200} for i in range(24)]
    second = force_compact(source, working, cwd=tmp_path)
    assert working.compact_cursor > first_cursor
    extended = source + [actual()]
    appended = project_for_model(extended, working, cwd=tmp_path, capacity_managed=True, context_limit=1048576)
    assert appended[0] == second[0]
    third = force_compact(extended, working, cwd=tmp_path)
    for field in ('reconciliation-125', 'task_id', 'ledger_total', 'delta', '基线100'):
        assert field in third[0]['content']
    assert 'ledger_total=137' in str(third)
    assert source[:len(original)] == original
    flush(working.session_id, working)
    wsc_projection._STATE.clear()
    restored = hydrate(working.session_id, source_layout=working.compression_source_layout)
    assert project_for_model(extended, restored, cwd=tmp_path, capacity_managed=True, context_limit=1048576) == third


def test_committed_task_state_does_not_add_last_historical_request(monkeypatch, tmp_path):
    from memory.wsc_fallback_handoff import render
    from tests.wsc.test_handoff_fact_disposition import prepared
    monkeypatch.setenv('XEYO_HOME', str(tmp_path/'home'))
    rows, _ = prepared()
    text = render(rows, WorkingSnapshot(session_id='committed'), len(rows), tmp_path)
    assert '任务交接快照' in text
    assert '折叠区末人类请求' not in text
