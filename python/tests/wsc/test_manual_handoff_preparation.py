"""Both manual compactors share configuration and request ownership boundaries."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from engine.abort import Aborted
from engine.budget import BudgetTracker
from engine.execution_context import ExecutionContext
from engine.manual_compaction import compact
from engine.workspace_context import get_execution_context
from evals.wsc_production_continuation import ProductionTask
from model.chunks import ModelChunk
from prompt.assembler import PromptAssembler
from tests.wsc.test_semantic_production import isolated


def engine_for(root, *, rows=None, context=None, config=None):
    task = ProductionTask(root, rows if rows is not None else [
        {'id': f'm{i}', 'role': 'assistant', 'content': str(i)} for i in range(15)], session='manual-common')
    events = []

    class Prompt(PromptAssembler):
        async def build_system(self, **kwargs):
            events.append(('system', get_execution_context(), kwargs))
            return 'fixture'

    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            events.append(('model', get_execution_context(), deepcopy((messages, tools))))
            self.last_usage = {'prompt_tokens': 10, 'completion_tokens': 1, 'usd': 0}
            if False: yield ModelChunk(kind='text_delta', text='unused')

    session = SimpleNamespace(working=task.working, messages=task.store, budget=BudgetTracker(),
        cwd=str(root), session_id='manual-common', transcript_persist_index=0,
        transcript_known_ids=set(), is_session_persistence_disabled=lambda: False)
    engine = SimpleNamespace(_session=session, _config={'cwd': str(root), 'tools': [], **(config or {})},
        _runtime_context=context, _permission_profile='workspace_write', _provider='deepseek',
        _model_name='fixture', _model=Model(), _prompt=Prompt(), _tools=task.registry,
        _date_iso='2026-10-15', budget_snapshot=lambda: {})
    return engine, task, events


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic', [False, True])
@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('config, expected', [
    ({'max_budget_usd': None, 'max_budget': .03}, .03),
    ({'max_budget_usd': .02, 'max_budget': .03}, .02),
    ({'max_budget_usd': 0, 'max_budget': .03}, 0),
    ({'max_budget': .03}, .03),
    ({'max_budget_usd': None, 'max_budget': None}, .17),
    ({}, .17),
])
async def test_modes_share_budget_precedence_and_context(isolated, monkeypatch, semantic, bound, config, expected):
    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', str(int(semantic)))
    monkeypatch.setenv('XEYO_MAX_BUDGET_USD', '.17')
    context = ExecutionContext(session_id='manual-common', cwd=str(isolated),
        permission_profile='workspace_write', runtime='test', trace_id='old',
        model_request_id='old-request', projection_id='old-projection') if bound else None
    engine, task, events = engine_for(isolated, config=config, context=context)
    original = deepcopy(task.source())
    previous_context = get_execution_context()
    if expected == 0 or not semantic:
        error = 'budget_usd' if expected == 0 else 'handoff_declaration_missing'
        with pytest.raises(ValueError, match=f'^{error}$'):
            await compact(engine)
    else:
        result = await compact(engine)
        assert result['reason'] == 'semantic_generation_empty' and result['source_retained']
    assert engine._session.budget.usd_limit == expected
    assert [event[0] for event in events] == ['system'] + ([] if expected == 0 else ['model'])
    for _, active, _ in events:
        assert active.session_id == 'manual-common' and active.cwd == str(isolated)
        assert active.trace_id.startswith('manual-compact-')
        assert active.model_request_id == active.projection_id == ''
        assert active.permission_profile == 'workspace_write'
        assert active.runtime == ('test' if bound else 'unknown')
    assert get_execution_context() == previous_context
    assert task.source() == original and task.working.compact_cursor == 0
    assert engine._session.budget.used_tokens == (0 if expected == 0 else 11)


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic', [False, True])
@pytest.mark.parametrize('boundary', ['short', 'pending_stop'])
async def test_early_exit_preserves_budget_and_does_not_build_request(isolated, monkeypatch, semantic, boundary):
    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', str(int(semantic)))
    rows = [{'id': 'one', 'role': 'user', 'content': 'small'}] if boundary == 'short' else None
    engine, task, events = engine_for(isolated, rows=rows)
    engine._session.budget.used_tokens = 42
    engine._session.budget.turn_count = 3
    original = deepcopy(task.source())
    if boundary == 'pending_stop':
        with pytest.raises(Aborted):
            await compact(engine, pending_stop=lambda: True)
    else:
        assert (await compact(engine))['reason'] == 'too_short'
    assert not events and engine._session.budget.used_tokens == 42
    assert engine._session.budget.turn_count == 3
    assert task.source() == original and task.working.compact_cursor == 0


@pytest.mark.asyncio
async def test_current_declaration_does_not_reinitialize_generation_budget(isolated, monkeypatch):
    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', '0')
    monkeypatch.setattr('memory.wsc_handoff_scope.needs_refresh', lambda *args: False)
    engine, task, events = engine_for(isolated)
    engine._session.budget.used_tokens = 42
    assert (await compact(engine))['ok']
    assert not events and engine._session.budget.used_tokens == 42
