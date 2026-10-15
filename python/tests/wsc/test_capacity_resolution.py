from types import SimpleNamespace

import pytest

from engine.abort import AbortController, Aborted
from memory.wsc_request_timing import prepare_counted
from memory.wsc_counted_input import CountedInput
from memory.working import WorkingSnapshot
from model.context_capacity import ensure_capacity
from model.deepseek import DeepSeekModelClient
from model.openai_compat import OpenAICompatClient
from model.vendor_models import parse_vendor_models_payload


def client(monkeypatch, native=False):
    monkeypatch.delenv('XEYO_CONTEXT_LIMIT_TOKENS', raising=False)
    kw = dict(api_key='offline', base_url='https://api.deepseek.com', model='deepseek-flash')
    return DeepSeekModelClient(**kw) if native else OpenAICompatClient(**kw, provider='deepseek')


def vendor(monkeypatch, rows, ok=True):
    calls = []
    def fetch(**kwargs):
        calls.append({k: v for k, v in kwargs.items() if k != 'api_key'})
        return {'vendor_ok': ok, 'data': parse_vendor_models_payload({'data': rows}, provider=kwargs['provider'])}
    monkeypatch.setattr('model.vendor_models.fetch_vendor_models', fetch)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
async def test_exact_vendor_capacity_reaches_complete_request_admission(monkeypatch, native):
    model = client(monkeypatch, native)
    calls = vendor(monkeypatch, [{'id': 'deepseek-flash', 'context_length': 100000}])
    await ensure_capacity(model, AbortController())
    assert model.context_limit == 100000
    # Disable optional tokenizer to isolate full normalized request admission.
    monkeypatch.setattr(model, 'context_token_measure', lambda source: None)
    counted = CountedInput(model, AbortController())
    working = WorkingSnapshot()
    schemas = [{'name': 'large_schema', 'description': 'x' * 360000, 'input_schema': {'type': 'object'}}]
    folded = []
    prepared = await prepare_counted([], schemas, working,
        context_limit=model.context_limit,
        build=lambda rows: [{'role': 'user', 'content': 'current task'}],
        render=lambda rows, text: rows,
        compact=lambda: folded.append(True) or [], model=counted)
    assert prepared.facts['before']['timing_action'] == 'capacity'
    assert prepared.facts['before']['notify']
    assert prepared.facts['automatic_attempts'] == 1 and folded == [True]
    await ensure_capacity(model, AbortController())
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('rows,ok', [
    ([{'id': 'deepseek-flash-suffix', 'context_length': 1048576}], True),
    ([{'id': 'deepseek-flash'}], True),
    ([{'id': 'deepseek-flash', 'context_length': 1048576}] * 2, True),
    ([{'id': 'deepseek-flash', 'context_length': True}], True),
    ([{'id': 'deepseek-flash', 'context_length': 1048576.5}], True),
    ([{'id': 'deepseek-flash', 'context_length': 1048576}], False),
])
async def test_unknown_and_ambiguous_declarations_do_not_guess_or_retry(monkeypatch, rows, ok):
    model = client(monkeypatch)
    calls = vendor(monkeypatch, rows, ok)
    await ensure_capacity(model, AbortController())
    await ensure_capacity(model, AbortController())
    assert model.context_limit is None and len(calls) == (1 if ok else 2)


@pytest.mark.asyncio
async def test_explicit_declaration_wins_and_switch_does_not_reuse_vendor_window(monkeypatch):
    model = client(monkeypatch)
    calls = vendor(monkeypatch, [{'id': 'deepseek-flash', 'context_length': 1048576},
        {'id': 'other', 'metadata': {'context_window': 200000}}])
    await ensure_capacity(model, AbortController())
    model._model = 'other'
    await ensure_capacity(model, AbortController())
    assert model.context_limit == 200000 and len(calls) == 2
    model.declare_context_limit(150000)
    model._model = 'third'
    await ensure_capacity(model, AbortController())
    assert model.context_limit == 150000 and len(calls) == 2


@pytest.mark.asyncio
async def test_connection_change_during_fetch_cannot_publish_old_window(monkeypatch):
    model = client(monkeypatch)
    def fetch(**kwargs):
        model._base_url = 'https://new.example/v1'
        return {'vendor_ok': True, 'data': [{'id': 'deepseek-flash', 'context_length': 1048576}]}
    monkeypatch.setattr('model.vendor_models.fetch_vendor_models', fetch)
    await ensure_capacity(model, AbortController())
    assert model.context_limit is None
    assert getattr(model, '_wsc_capacity_connection', None) is None


@pytest.mark.asyncio
async def test_already_aborted_lookup_cannot_publish_or_mark_resolved(monkeypatch):
    model = client(monkeypatch)
    vendor(monkeypatch, [{'id': 'deepseek-flash', 'context_length': 1048576}])
    abort = AbortController()
    abort.abort('test')
    with pytest.raises(Aborted):
        await ensure_capacity(model, abort)
    assert model.context_limit is None
    assert getattr(model, '_wsc_capacity_connection', None) is None


@pytest.mark.asyncio
async def test_non_http_model_keeps_existing_capacity_without_discovery(monkeypatch):
    calls = vendor(monkeypatch, [])
    model = SimpleNamespace(context_limit=1048576)
    await ensure_capacity(model, AbortController())
    assert model.context_limit == 1048576 and not calls


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
async def test_env_capacity_prevents_vendor_request(monkeypatch, native):
    model = client(monkeypatch, native)
    monkeypatch.setenv('XEYO_CONTEXT_LIMIT_TOKENS', '123456')
    model = type(model)(api_key='offline', base_url='https://api.deepseek.com', model='deepseek-flash')
    calls = vendor(monkeypatch, [])
    await ensure_capacity(model, AbortController())
    assert model.context_limit == 123456 and model.context_limit_declared and not calls


def test_native_builder_uses_selected_model_and_connection(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    from engine.query_engine import build_default_engine
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'offline')
    monkeypatch.delenv('XEYO_CONTEXT_LIMIT', raising=False)
    monkeypatch.delenv('XEYO_CONTEXT_LIMIT_TOKENS', raising=False)
    monkeypatch.setattr('tools.catalog.build_default_registry', lambda **kw: MagicMock())
    monkeypatch.setattr('tools.catalog.apply_read_vision', lambda *args, **kw: None)
    monkeypatch.setattr('tools.catalog.inject_subagent_runtime', lambda *args: None)
    monkeypatch.setattr('extension.mcp_manager.attach_mcp_tools', lambda *args: None)
    monkeypatch.setattr('sidecar.upgrade.apply', lambda: None)
    monkeypatch.setattr('engine.query_engine.QueryEngine', lambda config: config)
    config = build_default_engine(cwd=str(tmp_path), model_backend='deepseek',
        model='selected-model', base_url='https://selected.example/v1')
    assert config['model_client']._model == config['model'] == 'selected-model'
    assert config['model_client']._base_url == 'https://selected.example/v1'


@pytest.mark.asyncio
async def test_unavailable_vendor_can_recover_on_next_submit(monkeypatch):
    model = client(monkeypatch)
    calls = []
    def fetch(**kwargs):
        calls.append(True)
        return {'vendor_ok': len(calls) > 1, 'data': [{'id': 'deepseek-flash', 'context_length': 1048576}]}
    monkeypatch.setattr('model.vendor_models.fetch_vendor_models', fetch)
    await ensure_capacity(model, AbortController())
    assert model.context_limit is None
    await ensure_capacity(model, AbortController())
    assert model.context_limit == 1048576 and len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('wsc', ['0', '1'])
async def test_shared_query_loop_resolves_before_main_and_keeps_20k_task(monkeypatch, tmp_path, native, wsc):
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from model.chunks import ModelChunk
    from msgtypes.message import Message
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.tool_registry import ToolRegistry
    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_USAGE_DIR', str(tmp_path / 'usage'))
    monkeypatch.setenv('XEYO_WSC', wsc)
    monkeypatch.setattr('memory.wsc_projection._STATE', {})
    monkeypatch.setattr('engine.first_sniff.maybe_first_sniff_text', lambda **kw: '')
    model = client(monkeypatch, native)
    calls = vendor(monkeypatch, [{'id': 'deepseek-flash', 'context_window': 1048576}])
    seen = []
    async def stream(messages, tools, abort):
        assert model.context_limit == 1048576
        assert 'long task' in str(messages) and 'x' * 80000 in str(messages)
        seen.append(True)
        yield ModelChunk(kind='text_delta', text='observed')
    monkeypatch.setattr(model, 'stream', stream)
    monkeypatch.setattr(model, 'context_token_measure', lambda source: None)
    store = MessageStore([Message(role='user', content='long task ' + 'x' * 80000)])
    working = WorkingSnapshot()
    events = [event async for event in query_loop(store=store, model=model,
        tools=ToolRegistry(cwd=str(tmp_path)), prompt=PromptAssembler(), system_prompt='fixture',
        abort=AbortController(), budget=BudgetTracker(max_turns=2), working=working,
        include_memory_index=False)]
    assert seen == [True] and len(calls) == 1 and working.compact_cursor == 0
    assert working.wsc_timing_state['last_request_admission']['automatic_attempts'] == 0
    assert events


@pytest.mark.asyncio
async def test_shared_loop_turns_capacity_lookup_abort_into_stop(monkeypatch, tmp_path):
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.tool_registry import ToolRegistry
    model = client(monkeypatch)
    vendor(monkeypatch, [])
    abort = AbortController()
    abort.abort('test')
    events = [event async for event in query_loop(store=MessageStore(), model=model,
        tools=ToolRegistry(cwd=str(tmp_path)), prompt=PromptAssembler(), system_prompt='fixture',
        abort=abort, budget=BudgetTracker(max_turns=2))]
    assert len(events) == 1 and events[0].reason == 'aborted'
