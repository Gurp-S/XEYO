"""Independent control state cannot be silently adopted as a summary baseline."""
from copy import deepcopy

import pytest

from engine.abort import AbortController
from memory import wsc_semantic_compaction as semantic
from memory.working import WorkingSnapshot, hydrate
from model.chunks import ModelChunk
from tests.wsc.test_semantic_production import isolated


class Summary:
    context_limit = 100000
    last_usage = None

    def __init__(self, action=lambda: None):
        self.action = action

    def for_handoff(self, max_tokens):
        return self

    async def stream(self, messages, tools, abort):
        self.action()
        yield ModelChunk(kind='text_delta', text='Original work remains pending.')


def rows():
    return [{'role': 'assistant', 'content': str(i)} for i in range(20)]


@pytest.mark.asyncio
@pytest.mark.parametrize('moment', ['during_generation', 'before_publication'])
async def test_control_only_change_rejects_candidate(isolated, monkeypatch, moment):
    monkeypatch.chdir(isolated)
    goal = {'goal_id': 'g', 'revision': 1, 'status': 'active', 'text': 'Original work'}
    monkeypatch.setattr('memory.wsc_goal_source.snapshot', lambda *args: deepcopy(goal))
    def change():
        goal.update(revision=2, status='paused')
    working, source = WorkingSnapshot(session_id='control'), rows()
    async def prepare():
        return await semantic.prepare(model=Summary(change if moment == 'during_generation' else lambda: None),
            messages=source, source=lambda: source, working=working,
            abort=AbortController(), account=lambda _: None, persist=lambda: None)
    with pytest.raises(ValueError, match='semantic_control_changed'):
        if moment == 'during_generation':
            await prepare()
        else:
            candidate = await prepare()
            change()
            semantic.publish(candidate, source, working, cwd=isolated)
    assert working.compact_cursor == 0
    from memory.wsc_head_store import path_for
    assert not path_for(working.session_id).exists()


@pytest.mark.asyncio
async def test_goal_baseline_is_actually_presented_and_survives_restart(isolated, monkeypatch):
    monkeypatch.chdir(isolated)
    goal = {'goal_id': 'g', 'revision': 1, 'status': 'active', 'text': 'CURRENT_BOUND_GOAL'}
    monkeypatch.setattr('memory.wsc_goal_source.snapshot', lambda *args: deepcopy(goal))
    source, working = rows(), WorkingSnapshot(session_id='presented')
    candidate = await semantic.prepare(model=Summary(), messages=source, source=lambda: source,
        working=working, abort=AbortController(), account=lambda _: None, persist=lambda: None)
    hot = semantic.publish(candidate, source, working, cwd=isolated)
    assert 'CURRENT_BOUND_GOAL' in str(hot)
    from memory import wsc_projection
    wsc_projection._STATE.clear()
    assert wsc_projection.project_c2_messages(source, hydrate('presented'), cwd=isolated) == hot


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['same_length_rewrite', 'late_result', 'cancel'])
async def test_post_generation_change_keeps_unretired_source(isolated, monkeypatch, change):
    monkeypatch.chdir(isolated)
    source, working, abort = rows(), WorkingSnapshot(session_id='changed'), AbortController()
    candidate = await semantic.prepare(model=Summary(), messages=source, source=lambda: source,
        working=working, abort=abort, account=lambda _: None, persist=lambda: None)
    if change == 'same_length_rewrite':
        source[0]['content'] = 'changed'
    elif change == 'late_result':
        source.append({'role': 'tool', 'content': [{'type': 'tool_result',
                       'tool_use_id': 'late', 'content': 'EXACT_LATE_RESULT'}]})
    else:
        abort.abort()
    before = deepcopy(source)
    from engine.abort import Aborted
    with pytest.raises((ValueError, Aborted)):
        semantic.publish(candidate, source, working, cwd=isolated, guard=abort.raise_if_aborted)
    assert source == before and working.compact_cursor == 0


@pytest.mark.asyncio
async def test_original_envelopes_are_exact_separate_and_readable(isolated):
    import json
    from pathlib import Path
    from evals.wsc_production_continuation import ProductionTask, PublishedRead
    from memory.wsc_semantic_originals import from_store
    from memory.wsc_head_store import path_for
    from msgtypes.message import ToolUse
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'user' if i == 0 else 'assistant',
        'content': 'original evidence' if i == 0 else str(i)} for i in range(20)])
    task.store.items[0].interrupted = True
    task.store.items[0].narration = 'ORIGINAL_METADATA'
    task.persist()
    original = from_store(task.store)
    candidate = await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
        working=task.working, abort=AbortController(), account=lambda _: None, persist=task.persist,
        cwd=isolated, original_source=lambda: from_store(task.store))
    hot = semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    head = json.loads(path_for(task.working.session_id).read_text(encoding='utf-8'))
    path = next(Path(name) for name in head['publication']['objects'] if '-original.' in name)
    assert [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] == original
    assert 'ORIGINAL_METADATA' not in str(hot)
    result = await PublishedRead(task, head).execute(ToolUse('recall', 'Read',
        {'file_path': str(path), 'offset': 1, 'limit': 1}), AbortController())
    assert not result.is_error and 'ORIGINAL_METADATA' in str(result.content)
    assert task.restart().project() == hot


@pytest.mark.asyncio
async def test_interrupted_head_publication_recovers_complete_source(isolated, monkeypatch):
    from evals.wsc_production_continuation import ProductionTask
    from memory.working import flush
    from memory import wsc_projection
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'user' if i == 0 else 'assistant',
                                    'content': f'ORIGINAL_{i}'} for i in range(20)])
    task.persist()
    flush(task.working.session_id, task.working)
    original = deepcopy(task.source())
    candidate = await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
        working=task.working, abort=AbortController(), account=lambda _: None, persist=task.persist, cwd=isolated)
    def interrupted(*args, **kwargs):
        raise OSError('injected persistence interruption')
    with monkeypatch.context() as patch:
        patch.setattr('memory.working.flush', interrupted)
        with pytest.raises(OSError):
            semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    wsc_projection._STATE.clear()
    restarted = task.restart()
    assert restarted.working.compact_cursor == 0
    assert restarted.source() == original
    hot = str(restarted.project())
    assert all(f'ORIGINAL_{i}' in hot for i in range(20))


@pytest.mark.asyncio
async def test_interruption_after_working_flush_recovers_new_generation(isolated, monkeypatch):
    from evals.wsc_production_continuation import ProductionTask
    from memory import wsc_projection
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'assistant', 'content': str(i)} for i in range(20)])
    candidate = await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
        working=task.working, abort=AbortController(), account=lambda _:None, persist=task.persist, cwd=isolated)
    def interrupted(*args, **kwargs):
        raise OSError('interrupted after working persisted')
    with monkeypatch.context() as patch:
        patch.setattr('memory.working.hydrate', interrupted)
        with pytest.raises(OSError):
            semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    assert task.working.compact_cursor == candidate['cut']
    wsc_projection._STATE.clear()
    restarted = task.restart()
    assert restarted.working.compact_cursor == candidate['cut']
    assert restarted.project()[0]['content'].startswith(candidate['text'])
    assert restarted.source() == task.source()


@pytest.mark.asyncio
async def test_post_fold_goal_delta_appends_without_rewriting_head(isolated, monkeypatch):
    from memory import wsc_projection, wsc_head_store
    monkeypatch.chdir(isolated)
    goal = {'goal_id':'g','revision':1,'status':'active','text':'BOUND_WORK'}
    monkeypatch.setattr('memory.wsc_goal_source.snapshot', lambda *args:deepcopy(goal))
    source, working = rows(), WorkingSnapshot(session_id='goal-delta')
    candidate = await semantic.prepare(model=Summary(), messages=source, source=lambda:source,
        working=working, abort=AbortController(), account=lambda _:None, persist=lambda:None)
    before = semantic.publish(candidate, source, working, cwd=isolated)
    head_bytes = wsc_head_store.path_for(working.session_id).read_bytes()
    goal.update(revision=2, status='paused')
    after = wsc_projection.project_c2_messages(source, working, cwd=isolated)
    assert after[:len(before)] == before
    assert 'paused' in str(after[len(before):])
    assert wsc_head_store.path_for(working.session_id).read_bytes() == head_bytes
    wsc_projection._STATE.clear()
    assert wsc_projection.project_c2_messages(source, hydrate(working.session_id), cwd=isolated) == after
