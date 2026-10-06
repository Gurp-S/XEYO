from memory.wsc2.audit import score
from memory.wsc2.events import build_events
from memory.wsc2.reducer import reduce_events
from memory.wsc2.state import Observation, WorkingState
from tests.wsc.test_receipt_truth import use, result


def test_orphan_error_is_retained_without_crashing():
    state, _ = reduce_events(build_events([result('missing', 'Permission denied', True)]))
    assert len(state.active_facts(('failure',))) == 1


def test_active_duplicates_are_detected_by_audit():
    state = WorkingState()
    for i in range(2):
        state.add('file', 'app.py', {}, event_id=f'E{i}', event_index=i, evidence='receipt')
    assert score([], 0, state)['active_duplicate_keys'] == 1


def test_zero_observation_indices_survive_restoration():
    value = Observation('app.py', last_read_index=0, stale_at=0)
    assert Observation.from_dict(value.to_dict()) == value


def test_failed_reads_and_writes_do_not_change_observations():
    rows = [use('r', 'Read', file_path='app.py'), result('r', 'x=1'),
            use('w', 'Write', file_path='app.py', content='x=2'),
            result('w', 'Permission denied', True)]
    state, _ = reduce_events(build_events(rows))
    assert not state.observation('app.py').stale
    rows = [use('r', 'Read', file_path='app.py'), result('r', 'Permission denied', True)]
    state, _ = reduce_events(build_events(rows))
    assert not state.obs
    assert not state.active_facts(('file',))


def test_write_attempt_commits_a_file_fact_only_after_success():
    attempted = [use('w', 'Write', file_path='app.py', content='x=1')]
    state, _ = reduce_events(build_events(attempted))
    assert not state.active_facts(('file',))
    state, _ = reduce_events(build_events(attempted + [result('w')]))
    assert state.latest('file', 'app.py').created_index == 1
    state, _ = reduce_events(build_events(attempted + [result('w', 'Permission denied', True)]))
    assert not state.active_facts(('file',))
