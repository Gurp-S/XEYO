"""Default dispatch and sealed-head migration use the production boundaries."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from tests.wsc.test_semantic_production import (
    isolated,
    test_real_query_boundary as query_boundary,
    test_real_manual_compaction_entry as manual_boundary,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [False, True])
async def test_query_semantics_has_no_declaration_dependency(isolated, monkeypatch, explicit):
    if not explicit:
        monkeypatch.delenv('XEYO_WSC_SEMANTIC_HANDOFF')

    def unexpected(*args, **kwargs):
        raise AssertionError('semantic compaction consulted legacy declaration coverage')

    monkeypatch.setattr('memory.wsc_handoff_scope.needs_refresh', unexpected)
    await query_boundary(isolated, 'ok', False, monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize('empty', [False, True])
async def test_manual_default_retains_native_success_and_failure(isolated, monkeypatch, empty):
    monkeypatch.delenv('XEYO_WSC_SEMANTIC_HANDOFF')
    await manual_boundary(isolated, empty)


@pytest.mark.asyncio
async def test_legacy_head_migrates_only_at_next_fold(isolated, monkeypatch):
    from evals.wsc_production_continuation import ProductionTask
    from engine.abort import AbortController
    from memory import wsc_semantic_compaction as semantic, wsc_head_store as heads
    from model.chunks import ModelChunk
    from msgtypes.message import Message

    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', '0')
    task = ProductionTask(isolated, [{'id': f'old-{i}', 'role': 'user' if i == 0 else 'assistant',
        'content': 'Review the report; do not publish.' if i == 0 else f'Observation {i}'}
        for i in range(20)], session='legacy-migration')
    task.persist()
    old = task.fold()
    assert not old['head'].get('lifecycle', {}).get('semantic_checkpoint')
    reference = heads.path_for(task.working.session_id).read_bytes()
    objects = {name: Path(name).read_bytes() for name in old['head']['publication']['objects']}
    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', '1')
    assert task.project() == old['hot']
    assert heads.path_for(task.working.session_id).read_bytes() == reference
    task = task.restart()
    assert task.project() == old['hot']
    for i in range(12):
        task.store.append(Message(role='assistant', content=f'New observation {i}'))
    task.persist()
    original = deepcopy(task.source())

    class Summary:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            assert 'TodoWrite' not in {tool['name'] for tool in tools}
            yield ModelChunk(kind='text_delta', text='Report review remains pending. Publication is excluded.')

    candidate = await semantic.prepare(model=Summary(), messages=task.project(), source=task.source,
        working=task.working, abort=AbortController(), account=lambda _: None,
        persist=task.persist, cwd=isolated)
    new = semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    assert task.source() == original
    assert new[0] != old['hot'][0]
    task = task.restart()
    assert task.project() == new
    record = json.loads(heads.path_for(task.working.session_id).read_bytes())
    assert record['lifecycle']['semantic_checkpoint']['semantic_status'] == 'SEMANTIC_UNVERIFIED'
    task.store.append(Message(role='user', content='The review is still in progress.'))
    assert task.project()[0] == new[0]
    for name, raw in objects.items():
        assert Path(name).read_bytes() == raw
