"""Generation consumes the committed semantic body, not rendered directory copies."""
from copy import deepcopy
import json

import pytest

from engine.abort import AbortController
from evals.wsc_production_continuation import ProductionTask
from memory import wsc_semantic_compaction as semantic, wsc_head_store as hs
from model.chunks import ModelChunk
from msgtypes.message import Message
from prompt.assembler import PromptAssembler
from tests.wsc.test_semantic_production import isolated


def make_task(root):
    return ProductionTask(root, [{'id': str(i), 'role': 'assistant', 'content': 'source '+str(i)}
                                 for i in range(24)], session='semantic-input')


async def prepare(task, model):
    return await semantic.prepare(model=model, messages=PromptAssembler().build('SYSTEM', task.project()),
        source=task.source, working=task.working, abort=AbortController(), account=lambda _: None,
        persist=task.persist, cwd=task.root)


class CopyBody:
    context_limit = 1000000
    last_usage = None

    def __init__(self, expected, output=None):
        self.expected = expected
        self.output = expected if output is None else output
        self.seen = None

    def for_handoff(self, max_tokens): return self

    async def stream(self, messages, tools, abort):
        self.seen = deepcopy(messages)
        summaries = [m for m in messages if m.get('name') == 'session_summary']
        if summaries:
            assert summaries[0]['content'] == self.expected
        yield ModelChunk(kind='text_delta', text=self.output)


@pytest.mark.asyncio
async def test_ten_folds_never_feed_runtime_directory_back_to_generator(isolated, monkeypatch):
    task = make_task(isolated)
    goal = {'goal_id': 'g', 'revision': 1, 'status': 'active', 'text': 'CURRENT_CONTROL'}
    monkeypatch.setattr('memory.wsc_goal_source.snapshot', lambda *args: deepcopy(goal))
    body = 'Pending report. User-authored reference: 证据定位目录: Read(file_path="my-source.txt", offset=4, limit=2)'
    sealed = {}
    for generation in range(10):
        before = deepcopy(task.project())
        model = CopyBody(body)
        candidate = await prepare(task, model)
        assert 'CURRENT_CONTROL' in str(model.seen)
        assert task.project() == before  # generation cannot rewrite the frozen consumer prefix
        hot = semantic.publish(candidate, task.source(), task.working, cwd=isolated)
        assert hot[0]['content'].startswith(body)
        assert hot[0]['content'].count('span=1-') == 1
        record = json.loads(hs.path_for(task.working.session_id).read_text(encoding='utf-8'))
        for name in record['publication']['objects']:
            from pathlib import Path
            sealed.setdefault(name, Path(name).read_bytes())
        task = task.restart()
        assert task.project() == hot
        for i in range(12):
            task.store.append(Message(role='assistant', content=f'new {generation}/{i}'))
        task.persist()
        assert task.project()[0] == hot[0]
    for name, raw in sealed.items():
        assert Path(name).read_bytes() == raw


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['legacy', 'bad_pin', 'source_changed', 'different_head', 'user_quote'])
async def test_unknown_or_unowned_text_is_not_trimmed(isolated, monkeypatch, boundary):
    task = make_task(isolated)
    original_save = hs.save
    def legacy_save(*args, **kwargs):
        kwargs['lifecycle']['semantic_checkpoint'].pop('body_chars', None)
        return original_save(*args, **kwargs)
    with monkeypatch.context() as patch:
        if boundary == 'legacy': patch.setattr(hs, 'save', legacy_save)
        semantic.publish(await prepare(task, CopyBody('Pending work.')), task.source(), task.working, cwd=isolated)
    messages = PromptAssembler().build('SYSTEM', task.project())
    if boundary == 'bad_pin':
        from pathlib import Path
        Path(task.working.wsc_timing_state['committed_head_ref']['path']).write_bytes(b'bad')
    if boundary == 'source_changed':
        task.store.items[0].content = 'different evidence'
        task.store.replace(list(task.store.items))
    if boundary == 'different_head': messages[1]['content'] += ' changed'
    if boundary == 'user_quote': messages[1]['role'] = 'user'
    before = deepcopy(messages)
    from memory.wsc_semantic_input import for_generation
    assert for_generation(messages, task.working, task.source(), cwd=isolated) == before
    assert messages == before


@pytest.mark.asyncio
@pytest.mark.parametrize('after_write', [False, True])
async def test_body_boundary_recovers_at_same_commit_point_as_head(isolated, monkeypatch, after_write):
    from memory import working as snapshots
    from memory.wsc_semantic_input import for_generation
    task = make_task(isolated)
    first = await prepare(task, CopyBody('Previous semantic body.'))
    semantic.publish(first, task.source(), task.working, cwd=isolated)
    old_cursor = task.working.compact_cursor
    for i in range(12): task.store.append(Message(role='assistant', content='new '+str(i)))
    task.persist()
    second = await prepare(task, CopyBody(first['text'], 'Different new body with updated scope.'))
    flush = snapshots.flush
    def interrupted(session, staged):
        if staged.compact_cursor > old_cursor:
            if after_write: flush(session, staged)
            raise OSError('injected commit interruption')
        return flush(session, staged)
    with monkeypatch.context() as patch:
        patch.setattr(snapshots, 'flush', interrupted)
        with pytest.raises(OSError, match='injected commit interruption'):
            semantic.publish(second, task.source(), task.working, cwd=isolated)
    restored = task.restart()
    output = for_generation(PromptAssembler().build('SYSTEM', restored.project()),
        restored.working, restored.source(), cwd=isolated)
    assert output[1]['content'] == (second['text'] if after_write else first['text'])


@pytest.mark.asyncio
async def test_only_owned_head_is_replaced_tail_and_media_survive(isolated):
    task = make_task(isolated)
    body = 'Current work and meaningful source path.'
    hot = semantic.publish(await prepare(task, CopyBody(body)), task.source(), task.working, cwd=isolated)
    messages = PromptAssembler().build('SYSTEM', hot)
    tail = [dict(role='user', content=hot[0]['content']),
            dict(role='user', content=[{'type': 'image', 'source': {'type': 'url', 'url': 'fixture'}}]),
            dict(role='assistant', content=[{'type': 'tool_use', 'id': 'pending', 'name': 'Read', 'input': {}}]),
            dict(role='tool', content=[{'type': 'tool_result', 'tool_use_id': 'pending', 'content': 'NEW_RESULT'}])]
    messages.extend(tail)
    before = deepcopy(messages)
    from memory.wsc_semantic_input import for_generation
    output = for_generation(messages, task.working, task.source(), cwd=isolated)
    assert output[1] == {**messages[1], 'content': body}
    assert output[2:] == messages[2:] and output[-4:] == tail
    assert messages == before
