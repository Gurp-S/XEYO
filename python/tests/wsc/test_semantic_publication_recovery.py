"""A failed later fold must not erase the last committed projection."""
from copy import deepcopy
import pytest

from engine.abort import AbortController
from evals.wsc_production_continuation import ProductionTask
from memory import wsc_semantic_compaction as semantic
from msgtypes.message import Message
from tests.wsc.test_semantic_production import isolated
from tests.wsc.test_semantic_boundaries import Summary


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('moment', ['before_working', 'after_working', 'before_pin'])
async def test_second_fold_interruption_keeps_committed_head_and_complete_tail(isolated, monkeypatch, legacy, moment):
    from memory import working as snapshots
    from memory.wsc_committed_head import KEY
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'user' if i == 0 else 'assistant',
        'content': 'EXACT_ORIGINAL_'+str(i)} for i in range(24)], session='second-fold')
    async def prepare():
        return await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
            working=task.working, abort=AbortController(), account=lambda _:None,
            persist=task.persist, cwd=isolated)
    first = await prepare()
    semantic.publish(first, task.source(), task.working, cwd=isolated)
    old_cursor = task.working.compact_cursor
    if legacy:
        task.working.wsc_timing_state.pop(KEY)
        snapshots.flush(task.working.session_id, task.working)
    for i in range(20):
        task.store.append(Message(role='assistant', content='NEW_TAIL_'+str(i)))
    task.persist()
    before, source = deepcopy(task.project()), deepcopy(task.source())
    candidate = await prepare()
    assert candidate['cut'] > old_cursor
    original_flush, original_pin = snapshots.flush, __import__('memory.wsc_committed_head', fromlist=['pin']).pin
    def interrupted_flush(session, staged):
        if staged.compact_cursor > old_cursor and moment == 'before_working':
            raise OSError('injected_interruption')
        original_flush(session, staged)
        if staged.compact_cursor > old_cursor and moment == 'after_working':
            raise OSError('injected_interruption')
    def interrupted_pin(working, *args):
        if working.compact_cursor > old_cursor and moment == 'before_pin':
            raise OSError('injected_interruption')
        return original_pin(working, *args)
    with monkeypatch.context() as patch:
        patch.setattr('memory.working.flush', interrupted_flush)
        patch.setattr('memory.wsc_committed_head.pin', interrupted_pin)
        with pytest.raises(OSError, match='injected_interruption'):
            semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    restarted = task.restart()
    assert restarted.source() == source
    if moment == 'after_working':
        assert restarted.working.compact_cursor == candidate['cut']
        assert restarted.project()[0]['content'] == restarted.working.c2_summary_text
        assert restarted.project() == restarted.restart().project()
    else:
        assert restarted.working.compact_cursor == old_cursor
        assert restarted.project() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('corruption', ['head', 'source', 'cold', 'foreign_path'])
async def test_pinned_recovery_retains_all_existing_validation(isolated, corruption):
    import json
    from pathlib import Path
    from memory import wsc_head_store as hs, wsc_projection as wp
    from memory.wsc_committed_head import KEY
    from synaptic.contracts import publish
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'assistant', 'content': 'ORIGINAL_'+str(i)}
                                    for i in range(24)], session='validated-pin')
    candidate = await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
        working=task.working, abort=AbortController(), account=lambda _:None, persist=task.persist, cwd=isolated)
    hot = semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    reference = task.working.wsc_timing_state[KEY]
    pin = Path(reference['path'])
    record = json.loads(pin.read_text(encoding='utf-8'))
    hs.path_for(task.working.session_id).unlink()
    task = task.restart()
    assert task.project() == hot  # Valid pin alone recovers the exact emission.
    if corruption == 'head':
        pin.write_bytes(pin.read_bytes() + b'corrupt')
    elif corruption == 'source':
        task.store.items[0].content = 'REPLACED_SOURCE'
        task.store.replace(list(task.store.items))
    elif corruption == 'cold':
        path = Path(record['view_path'])
        path.write_bytes(path.read_bytes() + b'corrupt')
    else:
        other = publish(hs.path_for('different-session'), pin.read_bytes())
        task.working.wsc_timing_state[KEY] = dict(reference, path=str(other))
    wp._STATE.clear()
    assert task.project() == task.source()


@pytest.mark.asyncio
async def test_failed_legacy_reference_commit_preserves_old_head_file(isolated, monkeypatch):
    from memory import wsc_head_store as hs
    from memory.working import flush
    from memory.wsc_committed_head import KEY
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'assistant', 'content': str(i)} for i in range(24)])
    async def prepare():
        return await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
            working=task.working, abort=AbortController(), account=lambda _:None, persist=task.persist, cwd=isolated)
    semantic.publish(await prepare(), task.source(), task.working, cwd=isolated)
    task.working.wsc_timing_state.pop(KEY)
    flush(task.working.session_id, task.working)
    for i in range(20): task.store.append(Message(role='assistant', content='tail_'+str(i)))
    task.persist()
    candidate, before = await prepare(), task.project()
    head_bytes = hs.path_for(task.working.session_id).read_bytes()
    monkeypatch.setattr('memory.working.flush', lambda *args: None)
    with pytest.raises(ValueError, match='committed_head_reference_not_durable'):
        semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    assert hs.path_for(task.working.session_id).read_bytes() == head_bytes
    assert task.restart().project() == before
