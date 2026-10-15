"""Representation contracts exercised through the real generator and Guard."""
from copy import deepcopy
import json

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate, source_schema
from memory.wsc_handoff_scope_encoding import schema, to_native
from memory.wsc_handoff_validation import validate
from model.chunks import ModelChunk
from model.deepseek import _normalize_messages_for_openai
from msgtypes.message import ToolUse
from tests.wsc.test_task_phase import declaration, sources
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


def inline(native):
    value = deepcopy(native)
    cp = value['checkpoint']
    scopes = cp['phase_state'].pop('fact_scopes')
    for field in ('decisions', 'constraints'):
        cp[field] = [{**fact, 'scope': scope} for fact, scope in zip(cp[field], scopes[field])]
    return value


def test_atomic_reordering_preserves_fact_applicability_and_durable_format():
    raw = declaration()
    wire = inline(raw)
    assert to_native(wire) == raw
    wire['checkpoint']['constraints'].reverse()
    native = to_native(wire)
    parsed = validate(native, sources(), require_phase=True)
    from synaptic.task_phase import applicable
    assert applicable(parsed.checkpoint, 'constraints') == [raw['checkpoint']['constraints'][1]]
    assert native['checkpoint']['phase_state']['fact_scopes']['constraints'] == [
        {'kind': 'task'}, {'kind': 'phase', 'phase_id': 'design'}]
    assert raw == declaration()
    assert 'fact_scopes' not in wire['checkpoint']['phase_state']


@pytest.mark.parametrize('broken', ['partial', 'mixed', 'no_phase', 'extra', 'wrong_type'])
def test_encoding_never_fills_or_selects_missing_scope(broken):
    wire = inline(declaration())
    if broken == 'partial': del wire['checkpoint']['constraints'][0]['scope']
    if broken == 'mixed': wire['checkpoint']['phase_state']['fact_scopes'] = declaration()['checkpoint']['phase_state']['fact_scopes']
    if broken == 'no_phase': del wire['checkpoint']['phase_state']
    if broken == 'extra': wire['checkpoint']['constraints'][0]['certainty'] = 'truth'
    if broken == 'wrong_type': wire['checkpoint']['constraints'] = 'bad'
    before = deepcopy(wire)
    with pytest.raises(ValueError, match='handoff_invalid_state'):
        to_native(wire)
    assert wire == before


@pytest.mark.parametrize('broken', ['phase', 'quote', 'source', 'scope'])
def test_inline_encoding_does_not_weaken_native_guard(broken):
    wire = inline(declaration())
    fact = wire['checkpoint']['constraints'][0]
    if broken == 'phase': fact['scope']['phase_id'] = 'missing'
    if broken == 'quote': fact['quote'] = 'invented constraint'
    if broken == 'source': fact['source_message_id'] = 'missing'
    if broken == 'scope': fact['scope'] = {'kind': 'unknown'}
    with pytest.raises(ValueError):
        validate(to_native(wire), sources(), require_phase=True)


def test_legacy_empty_and_nonphase_calls_do_not_require_migration():
    raw = declaration()
    assert to_native(raw) == raw
    bad = deepcopy(raw)
    bad['checkpoint']['phase_state']['fact_scopes']['constraints'].pop()
    with pytest.raises(ValueError): validate(to_native(bad), sources(), require_phase=True)
    terminal = {'todos': [], 'checkpoint': {'objective': '', 'context_message_ids': []}}
    assert validate(to_native(terminal), sources()).todos == []
    value, _ = source_schema(TodoWriteTool().schema(), sources())
    assert 'scope' not in value['input_schema']['properties']['checkpoint']['properties']['constraints']['items']['properties']


def test_schema_removes_parallel_authority_without_changing_input_schema():
    value, _ = source_schema(TodoWriteTool().schema(), sources(), scope_protocol=True)
    before = deepcopy(value)
    cp = value['input_schema']['properties']['checkpoint']['properties']
    assert 'fact_scopes' not in cp['phase_state']['properties']
    for field in ('decisions', 'constraints'):
        assert set(cp[field]['items']['required']) == {'source_message_id', 'quote', 'scope'}
    # Schemas without phase continue to have their original representation.
    plain = TodoWriteTool().schema()
    assert schema(plain) == plain
    assert value == before


class Model:
    context_limit = 100000
    last_usage = None

    def __init__(self):
        self.requests, self.counted = [], []

    def for_handoff(self, *, max_tokens): return self

    def context_input(self, messages, tools):
        self.counted.append(deepcopy({'messages': messages, 'tools': tools}))
        return {'messages': messages, 'tools': tools}

    def context_token_measure(self, value): return len(json.dumps(value)), 'test_char_count'

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy({'messages': messages, 'tools': tools}))
        self.last_usage = {'prompt_tokens': 9, 'completion_tokens': 11}
        raw = inline(declaration())
        if len(self.requests) == 1:
            raw['checkpoint']['constraints'][0]['scope']['phase_id'] = 'missing'
            yield ModelChunk(kind='text_delta', text='original body')
            yield ModelChunk(kind='reasoning_delta', text='original reasoning')
        yield ModelChunk(kind='tool_use', tool_use=ToolUse('attempt-' + str(len(self.requests)), 'TodoWrite', raw))


@pytest.mark.asyncio
async def test_rejected_wire_frame_is_replayed_and_counted_but_return_is_native():
    model, usage = Model(), []
    rows = sources()
    before = deepcopy(rows)
    result = await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
                            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert result.input == declaration()
    assert len(model.requests) == 2 and len(usage) == 2
    replay = next(row for row in model.requests[1]['messages'] if row['role'] == 'assistant')
    wire = _normalize_messages_for_openai([replay])[0]
    raw = json.loads(wire['tool_calls'][0]['function']['arguments'])
    assert 'scope' in raw['checkpoint']['constraints'][0]
    assert 'fact_scopes' not in raw['checkpoint']['phase_state']
    assert raw['checkpoint']['constraints'][0]['scope']['phase_id'] == 'missing'
    assert wire['content'] == 'original body' and wire['reasoning_content'] == 'original reasoning'
    assert model.requests[1] in model.counted
    assert rows == before


@pytest.mark.asyncio
async def test_inline_declaration_commits_restores_and_keeps_published_head(tmp_path, monkeypatch):
    from evals.wsc_flash_compact_chain import native_store
    from memory.wsc_handoff_transaction import commit
    from memory.working import WorkingSnapshot
    from session.compression_source import compression_messages
    from session.record_transcript import record_transcript_sync, load_transcript
    from session.transcript_blobs import resolve_transcript_rows
    from synaptic.todo_snapshot import latest_todo_snapshot
    from tools.tool_registry import ToolRegistry
    from tests.wsc.test_task_phase import DURABLE, DESIGN

    monkeypatch.setenv('XEYO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XEYO_WSC', '1')
    store = native_store(sources())
    source = lambda: compression_messages(store, WorkingSnapshot())
    tools = ToolRegistry(cwd=str(tmp_path))
    tools.register(TodoWriteTool(cwd=str(tmp_path)))
    path, known = tmp_path / 'scope.jsonl', set()
    def persist():
        record_transcript_sync(store.items, session_id='scope', path=path, known_ids=known)
    persist()
    prefix = path.read_bytes()
    model = Model()
    async def declare(captured):
        return await generate(model, [{'role': 'user', 'content': 'fixture'}], captured,
                              TodoWriteTool().schema(), AbortController(), account=lambda usage: None, scope_protocol=True)
    result = await commit(source=source, generate=declare, store=store, tools=tools,
                          abort=AbortController(), persist=persist, require_phase=True)
    assert result['mechanical_status'] == 'VALIDATED' and result['semantic_status'] == 'SEMANTIC_UNVERIFIED'
    restored = resolve_transcript_rows(load_transcript(path), path)
    assert path.read_bytes().startswith(prefix)
    cp = latest_todo_snapshot(restored).checkpoint
    assert cp['phase_state'] == declaration()['checkpoint']['phase_state']
    assert all('scope' not in fact for field in ('constraints', 'decisions') for fact in cp[field])
    from memory.runtime import force_compact, project_for_model
    from memory import wsc_projection
    monkeypatch.setattr(wsc_projection, '_STATE', {})
    full = restored + [{'id': 'archive-' + str(i), 'role': 'assistant', 'content': 'x' * 1000} for i in range(35)]
    working = WorkingSnapshot(session_id='inline-scope')
    emitted = force_compact(full, working, cwd=tmp_path)
    assert working.compact_cursor > 0
    head = emitted[0]['content']
    assert DURABLE in head and DESIGN not in head
    full.append({'id': 'new', 'role': 'assistant', 'content': 'new result'})
    assert project_for_model(full, working, cwd=tmp_path)[0]['content'] == head
    assert path.read_bytes().startswith(prefix)
