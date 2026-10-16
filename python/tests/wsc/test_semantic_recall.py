"""Native read-only generation: exact sources, budgets, failures and ownership."""
from copy import deepcopy
import json

import pytest

from engine.abort import AbortController
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from memory.wsc_semantic_generation import generate


class Model:
    context_limit = 100000
    last_usage = None
    def __init__(self, frames): self.frames, self.requests = iter(frames), []
    def for_handoff(self, max_tokens): return self
    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy((messages, tools)))
        self.last_usage = {'prompt_tokens': 10, 'completion_tokens': 2}
        for chunk in next(self.frames):
            if isinstance(chunk, Exception): raise chunk
            yield chunk


def call(uid, name, data):
    return ModelChunk(kind='tool_use', tool_use=ToolUse(uid, name, data))


@pytest.mark.asyncio
async def test_read_only_discovery_and_exact_recall_preserve_source_and_prefix():
    sources = [{'id': 'hidden-spec', 'role': 'user', 'content': '账户 Ω=731; 不发布'}]
    visible = [{'role': 'assistant', 'content': '任务未完成；账户在历史来源中。'}]
    before = deepcopy((sources, visible))
    model = Model([[call('q', 'HandoffCatalog', {'start': 0, 'limit': 2, 'query': '账户'})],
        [call('r', 'HandoffSource', {'message_id': 'hidden-spec', 'offset': 0, 'limit': 100})],
        [ModelChunk(kind='text_delta', text='账户 Ω=731; 不发布；任务未完成。')]])
    accounted, more, reads = [], [], []
    result = await generate(model, visible, AbortController(), sources=sources, account=accounted.append,
        admit_next=lambda: more.append(1), admit_read=lambda: reads.append(1))
    assert result == '账户 Ω=731; 不发布；任务未完成。'
    assert len(model.requests) == len(accounted) == 3 and len(more) == len(reads) == 2
    assert (sources, visible) == before
    for messages, tools in model.requests:
        assert messages[:len(visible)] == visible
        assert {t['name'] for t in tools} == {'HandoffCatalog', 'HandoffSource'}
    raw = model.requests[-1][0][-1]['content'][0]['content']
    assert json.loads(raw)['content'] == sources[0]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['forbidden', 'duplicate', 'truncated', 'read_limit', 'budget', 'capacity', 'changed'])
async def test_failed_recall_never_returns_partial_summary(kind, monkeypatch):
    from model.output_exhaustion import OutputLimitError
    from memory import wsc_semantic_recall as loop
    use = call('q', 'HandoffCatalog', {'start': 0, 'limit': 1})
    frames = [[ModelChunk(kind='text_delta', text='not a final summary'), use],
              [ModelChunk(kind='text_delta', text='final')]]
    expected = {'forbidden': 'unexpected_tool', 'duplicate': 'identity_conflict',
        'truncated': 'length', 'read_limit': 'recall_limit', 'budget': 'budget',
        'capacity': 'capacity_exceeded', 'changed': 'source_changed'}[kind]
    if kind == 'forbidden': frames[0][-1] = call('q', 'TodoWrite', {})
    if kind == 'duplicate': frames[0].append(use)
    if kind == 'truncated': frames[0].append(OutputLimitError('length'))
    if kind == 'read_limit': monkeypatch.setattr(loop, 'MAX_REQUESTS', 1)
    model = Model(frames); counted = []
    def admit():
        if kind == 'budget': raise ValueError('budget')
    def check():
        if model.requests and kind == 'changed': raise ValueError('source_changed')
    if kind == 'capacity':
        from types import SimpleNamespace
        monkeypatch.setattr('memory.wsc_timing.request_measure', lambda *a, **k:
            SimpleNamespace(capacity=100000, input_tokens=100000 if model.requests else 100))
    with pytest.raises((ValueError, OutputLimitError), match=expected):
        await generate(model, [], AbortController(), sources=[{'id': 'u', 'role': 'user', 'content': 'hidden'}],
            account=counted.append, admit_next=admit, guard=check)
    assert len(model.requests) == len(counted) == 1


@pytest.mark.asyncio
async def test_source_absent_retains_single_call_summary_contract():
    model = Model([[ModelChunk(kind='text_delta', text='handoff')]])
    assert await generate(model, [], AbortController(), account=lambda _: None) == 'handoff'
    assert model.requests[0][1] == []


@pytest.mark.asyncio
async def test_source_change_during_precount_prevents_model_request():
    changed = False
    model = Model([[ModelChunk(kind='text_delta', text='unreachable')]])
    def check():
        if changed: raise ValueError('semantic_source_changed')
    async def predict(messages, tools, abort):
        nonlocal changed
        changed = True
        return 100
    model.predict_context_tokens = predict
    model.context_input = lambda messages, tools: {'messages': messages, 'tools': tools}
    with pytest.raises(ValueError, match='semantic_source_changed'):
        await generate(model, [], AbortController(), sources=[], account=lambda _: None, guard=check)
    assert model.requests == []


@pytest.mark.asyncio
async def test_native_prepare_counts_extra_requests_and_reads(tmp_path, monkeypatch):
    from memory.wsc_semantic_compaction import prepare
    from memory.working import WorkingSnapshot
    from engine.budget import BudgetTracker
    monkeypatch.setenv('XEYO_HOME', str(tmp_path))
    sources = [{'id': f'u{i}', 'role': 'user', 'content': str(i)} for i in range(20)]
    model = Model([[call('q', 'HandoffCatalog', {'start': 0, 'limit': 1})],
                   [ModelChunk(kind='text_delta', text='current work')]])
    budget = BudgetTracker(); budget.begin_turn()
    state = WorkingSnapshot(session_id='recall-budget')
    candidate = await prepare(model=model, messages=[], source=lambda: sources, working=state,
        abort=AbortController(), account=budget.add_usage, budget=budget, persist=lambda: None, cwd=tmp_path)
    assert candidate['text'] == 'current work' and budget.turn_count == 2 and budget.used_tokens == 24
    assert state.compact_cursor == 0
