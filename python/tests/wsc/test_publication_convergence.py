"""Production boundaries: generation failure, head ownership and durable commit."""
from copy import deepcopy
import json

import pytest

from tests.wsc.test_semantic_production import isolated


@pytest.mark.parametrize('kind', ['503', '429', '408', 'network', 'timeout', 'empty'])
def test_transient_generation_failure_is_resumable(kind):
    from common.errors import ProviderError, NetworkError, EmptyResponseError
    from memory.wsc_compaction_failure import recoverable, mark_generation_failure, GenerationUnavailable
    error = {'network': NetworkError('offline'), 'timeout': TimeoutError(),
             'empty': EmptyResponseError()}.get(kind)
    with pytest.raises(GenerationUnavailable) as observed:
        mark_generation_failure(error if error is not None else ProviderError('unavailable', status_code=int(kind)))
    assert recoverable(observed.value)


@pytest.mark.parametrize('error', [ValueError('semantic_source_changed'), OSError('disk failure'),
                                  ValueError('semantic_publication_failed'), PermissionError('denied'),
                                  TimeoutError('storage timeout')])
def test_commit_and_source_failures_are_not_resumable(error):
    from memory.wsc_compaction_failure import recoverable
    assert not recoverable(error)


@pytest.mark.parametrize('status', [400, 401, 402, 403, 404])
def test_permanent_provider_failure_does_not_enable_continuation(status):
    from common.errors import ProviderError
    from memory.wsc_compaction_failure import mark_generation_failure, recoverable
    exc = ProviderError('refused', status_code=status)
    mark_generation_failure(exc)
    assert not recoverable(exc)


def test_quoted_read_text_cannot_create_publication_dependency(isolated):
    from memory import wsc_head_store as hs
    rows = [{'role': 'user', 'content': 'source'}, {'role': 'assistant', 'content': 'result'}]
    text = "Quoted history: Read(file_path='missing.v-sha256-" + 'a'*64 + ".txt')"
    assert hs.save('quoted', text=text, cwd=str(isolated), cursor=2, region_end=2, messages=rows)
    assert hs.load('quoted', cwd=str(isolated), cursor=2, messages=rows).text == text


@pytest.mark.parametrize('fault', ['silent_flush', 'pin', 'goal', 'late_source'])
def test_d_second_fold_cannot_advance_without_valid_durable_generation(isolated, monkeypatch, fault):
    from memory import wsc_head_store as hs, working as snapshots, wsc_projection as wp
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from memory.wsc_committed_head import KEY
    rows = [{'id': str(i), 'role': 'assistant', 'content': 'original '+str(i)+' x'*400} for i in range(32)]
    state = WorkingSnapshot(session_id='shared-d')
    goal = {'goal_id': 'g', 'revision': 1, 'status': 'active', 'text': 'Task'}
    monkeypatch.setattr('memory.wsc_goal_source.snapshot', lambda *a: deepcopy(goal))
    force_compact(rows, state, cwd=isolated)
    old_cursor = state.compact_cursor
    rows += [{'id': 'new'+str(i), 'role': 'assistant', 'content': 'new '+str(i)} for i in range(20)]
    before = wp.project_c2_messages(rows, state, cwd=isolated)
    original_save = hs.save
    with monkeypatch.context() as patch:
        if fault == 'silent_flush':
            patch.setattr(snapshots, 'flush', lambda *a: None)
        elif fault == 'pin':
            def fail(*a): raise OSError('pin failed')
            patch.setattr('memory.wsc_committed_head.pin', fail)
        else:
            def change(*a, **kw):
                result = original_save(*a, **kw)
                if fault == 'goal': goal.update(revision=2, status='paused')
                else: rows.append({'role': 'tool', 'content': 'LATE_EXACT_RESULT'})
                return result
            patch.setattr(hs, 'save', change)
        with pytest.raises((ValueError, OSError)):
            force_compact(rows, state, cwd=isolated)
    assert state.compact_cursor == old_cursor
    wp._STATE.clear()
    restored = snapshots.hydrate(state.session_id)
    assert restored.compact_cursor == old_cursor and restored.wsc_timing_state.get(KEY)
    after = wp.project_c2_messages(rows, restored, cwd=isolated)
    assert after[0] == before[0]
    if fault == 'late_source': assert 'LATE_EXACT_RESULT' in str(after)


@pytest.mark.parametrize('legacy', [False, True])
def test_explicit_evidence_and_legacy_record_restore(isolated, legacy):
    from memory import wsc_head_store as hs
    from synaptic.contracts import publish
    source = [{'role': 'user', 'content': 'SPEC'}, {'role': 'assistant', 'content': 'observation'}]
    obj = publish(isolated/'archive.txt', b'EXACT_EVIDENCE')
    text = f'Read(file_path={obj.as_posix()!r})' if legacy else 'Human-readable handoff without path syntax.'
    assert hs.save('manifest', text=text, cwd=str(isolated), cursor=2, region_end=2,
                   messages=source, evidence_paths=(str(obj),))
    path = hs.path_for('manifest')
    if legacy:
        rec = json.loads(path.read_text(encoding='utf-8'))
        rec['publication'].pop('version')
        path.write_text(json.dumps(rec), encoding='utf-8')
    old = path.read_bytes()
    head = hs.load('manifest', cwd=str(isolated), cursor=2, messages=source)
    assert head.text == text and str(obj) in head.evidence_paths
    assert path.read_bytes() == old
    obj.write_bytes(b'TAMPERED')
    assert hs.load('manifest', cwd=str(isolated), cursor=2, messages=source) is None


def test_committed_record_wins_over_same_cursor_cache(isolated):
    from memory import wsc_head_store as hs, wsc_projection as wp
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    rows = [{'role': 'assistant', 'content': 'original '+str(i)+' x'*400} for i in range(32)]
    state = WorkingSnapshot(session_id='committed-authority')
    before = force_compact(rows, state, cwd=isolated)
    rec = json.loads(hs.path_for(state.session_id).read_text(encoding='utf-8'))
    assert hs.save(state.session_id, text='UNCOMMITTED', cwd=str(isolated),
                   cursor=state.compact_cursor, region_end=rec['region_end'], messages=rows)
    wp._STATE.clear()
    assert wp.project_c2_messages(rows, state, cwd=isolated) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['D', 'semantic'])
async def test_post_commit_interruption_cannot_be_rolled_back_by_caller_finally(isolated, monkeypatch, mode):
    from memory import working as snapshots, wsc_projection as wp
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from memory import wsc_semantic_compaction as semantic
    from engine.abort import AbortController
    from tests.wsc.test_semantic_boundaries import Summary
    rows = [{'role': 'assistant', 'content': str(i)+' x'*400} for i in range(32)]
    state = WorkingSnapshot(session_id='post-commit-'+mode)
    flush = snapshots.flush
    def interrupt(session, staged):
        flush(session, staged)
        raise OSError('after committed write')
    with monkeypatch.context() as patch:
        patch.setattr(snapshots, 'flush', interrupt)
        with pytest.raises(OSError, match='after committed write'):
            if mode == 'D':
                force_compact(rows, state, cwd=isolated)
            else:
                candidate = await semantic.prepare(model=Summary(), messages=rows, source=lambda: rows,
                    working=state, abort=AbortController(), account=lambda _: None, persist=lambda: None, cwd=isolated)
                semantic.publish(candidate, rows, state, cwd=isolated)
    assert state.compact_cursor > 0
    flush(state.session_id, state)  # Real caller-finally persistence.
    wp._STATE.clear()
    restored = snapshots.hydrate(state.session_id)
    assert restored.compact_cursor == state.compact_cursor
    assert wp.project_c2_messages(rows, restored, cwd=isolated) == wp.project_c2_messages(rows, state, cwd=isolated)


def test_media_coverage_can_span_older_catalog(isolated, monkeypatch):
    from memory import wsc_media_fold_commit as media
    from memory.working import WorkingSnapshot
    from memory.wsc_media_directory import pin
    from memory.wsc_head_store import save
    monkeypatch.setenv('XEYO_WSC_MEDIA_ARCHIVE', '1')
    rows = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://invalid.example/image.png'}}]}]
    rows += [{'role': 'assistant', 'content': str(i)} for i in range(8)]
    state = WorkingSnapshot(session_id='older-media')
    catalog = pin(rows, 3, cwd=isolated, session=state.session_id, source_layout=state.compression_source_layout)
    def build(source, staged, **kwargs):
        staged.compact_cursor = 6
        assert save(staged.session_id, text='media retained', cwd=str(isolated), cursor=6,
                    region_end=6, messages=source, evidence_paths=catalog.evidence_paths)
        return [{'role': 'assistant', 'content': 'media retained'}] + source[6:]
    result = media.fold(build, rows, state, cwd=isolated)
    assert state.compact_cursor == 6 and result[0]['content'] == 'media retained'
