"""Native query-loop semantic publication, failure continuation and recovery."""
from copy import deepcopy
import json

import pytest


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for key, directory in [('XEYO_HOME', 'home'), ('XEYO_USAGE_DIR', 'usage'),
                           ('XEYO_SESSIONS_DIR', 'sessions'), ('XEYO_SPILL_DIR', 'spill')]:
        monkeypatch.setenv(key, str(tmp_path / directory))
    monkeypatch.setenv('XEYO_WSC', '1')
    monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', '1')
    monkeypatch.setenv('XEYO_WSC_HEAD_STORE', '1')
    monkeypatch.setattr('memory.wsc_projection._STATE', {})
    monkeypatch.setattr('engine.first_sniff.maybe_first_sniff_text', lambda **kwargs: '')
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ok', 'empty', 'truncated', 'unexpected_tool', 'legacy_empty', 'legacy_baseline',
                                '503', 'timeout', 'legacy_503', 'legacy_timeout'])
@pytest.mark.parametrize('oversized', [False, True])
async def test_real_query_boundary(isolated, mode, oversized, monkeypatch):
    from engine.query_loop import query_loop
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from memory.working import WorkingSnapshot, hydrate
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from session.compression_source import compression_messages
    from prompt.assembler import PromptAssembler
    from tools.tool_registry import ToolRegistry
    from memory import wsc_head_store, wsc_projection
    legacy = mode.startswith('legacy_')
    baseline = mode == 'legacy_baseline'
    if legacy:
        monkeypatch.setenv('XEYO_WSC_SEMANTIC_HANDOFF', '0')
    if baseline:
        monkeypatch.setattr('memory.wsc_compaction_failure.recoverable', lambda exc: False)
    store = MessageStore([Message(role='user', content='当前任务：生成报告；不发布。')])
    for _ in range(30):
        store.append(Message(role='assistant', content='旧执行观察 ' + 'x' * 1500))
    store.append(assistant_text_message('', [ToolUse('unread', 'Read', {'file_path': 'result.txt'})]))
    store.append(tool_result_message('unread', 'Read', 'UNREAD_EXACT_RESULT',
        execution={'status': 'ok', 'complete': True}))
    original = deepcopy(store.items)
    registry = ToolRegistry(cwd=str(isolated))
    if legacy:
        from tools.todo_write_tool.todo_write_tool import TodoWriteTool
        registry.register(TodoWriteTool(cwd=str(isolated)))
    class Heavy:
        name = 'Heavy'
        @staticmethod
        def is_read_only(): return True
        @staticmethod
        def is_concurrency_safe(): return True
        def schema(self): return {'name': self.name, 'description': 'x' * (410000 if oversized else 315000),
                                  'input_schema': {'type': 'object'}}
    registry.register(Heavy())
    path = isolated / 'source.jsonl'
    known = set()
    def persist(): record_transcript_sync(store.items, session_id='semantic', path=path, known_ids=known)
    persist(); prefix = path.read_bytes()
    calls = []
    class Summary:
        last_usage = None
        async def stream(self, messages, tools, abort):
            calls.append('summary')
            if legacy:
                assert any(tool['name'] == 'TodoWrite' for tool in tools)
            else:
                assert {t['name'] for t in tools} == {'HandoffSource', 'HandoffCatalog'}
                assert 'CONTEXT CHECKPOINT' in messages[-1]['content']
            self.last_usage = {'prompt_tokens': 100, 'completion_tokens': 20}
            if mode.endswith('503'):
                from common.errors import ProviderError
                raise ProviderError('unavailable', status_code=503)
            if mode.endswith('timeout'):
                from common.errors import NetworkError
                raise NetworkError('offline')
            if mode == 'truncated':
                from model.output_exhaustion import OutputLimitError
                yield ModelChunk(kind='text_delta', text='unfinished')
                raise OutputLimitError('length')
            if mode == 'unexpected_tool':
                yield ModelChunk(kind='tool_use', tool_use=ToolUse('forbidden', 'Heavy', {}))
            if mode == 'ok':
                yield ModelChunk(kind='text_delta', text='当前任务：生成报告。不发布。读取结果已返回，报告尚未生成。')
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return Summary()
        async def stream(self, messages, tools, abort):
            calls.append('main')
            assert 'UNREAD_EXACT_RESULT' in str(messages)
            if mode == 'ok': assert '报告尚未生成' in str(messages)
            self.last_usage = {'prompt_tokens': 200, 'completion_tokens': 10}
            yield ModelChunk(kind='text_delta', text='continued')
    working = WorkingSnapshot(session_id='semantic')
    budget = BudgetTracker(max_turns=4)
    events = [event async for event in query_loop(store=store, model=Model(), tools=registry,
        prompt=PromptAssembler(), system_prompt='fixture', abort=AbortController(), budget=budget,
        working=working, persist_handoff=persist)]
    assert path.read_bytes().startswith(prefix)
    assert store.items[:len(original)] == original
    assert calls == ['summary'] + ([] if oversized or baseline else ['main'])
    assert budget.used_tokens == (120 if oversized or baseline else 330)
    assert not any(getattr(item, 'name', '') == 'TodoWrite' for item in store.items)
    rows = compression_messages(store, working)
    if mode == 'ok':
        assert working.compact_cursor > 0
        frozen = wsc_head_store.load('semantic', cwd=str(isolated), cursor=working.compact_cursor, messages=rows)
        assert frozen and frozen.lifecycle['semantic_checkpoint']['semantic_status'] == 'SEMANTIC_UNVERIFIED'
        cold = json.loads(wsc_head_store.path_for('semantic').read_text(encoding='utf-8'))['publication']['objects']
        from session.transcript_blobs import message_fields
        for name in cold:
            if '-index.' in name:
                records = [json.loads(line) for line in open(name, encoding='utf-8')]
                assert records[0]['format'] == 'wsc_evidence_index_v1'
                assert len(records) == len(original) * 2 + 1
                continue
            expected = [message_fields(item) for item in original] if '-original.' in name else rows[:len(original)]
            assert [json.loads(line) for line in open(name, encoding='utf-8')] == expected
        restored = hydrate('semantic')
        wsc_projection._STATE.clear()
        emission = wsc_projection.project_c2_messages(rows, restored, cwd=isolated)
        assert emission[0]['content'] == frozen.text
    else:
        assert working.compact_cursor == 0
        assert not wsc_head_store.path_for('semantic').exists()
        if not baseline:
            key = 'handoff_generation_failure' if legacy else 'semantic_generation_failure'
            assert working.wsc_timing_state[key]['outcome'] == 'retained_source'
    if baseline:
        assert any(getattr(event, 'reason', '') == 'handoff_declaration_missing' for event in events)
    elif oversized:
        assert any(str(getattr(event, 'reason', '')).startswith('context_capacity_exceeded:') for event in events)


@pytest.mark.asyncio
async def test_source_change_rejects_before_publication(isolated):
    from memory import wsc_semantic_compaction as s
    from memory.working import WorkingSnapshot
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    rows = [{'role': 'assistant', 'content': str(i)} for i in range(12)]
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            rows.append({'role': 'user', 'content': 'changed scope'})
            yield ModelChunk(kind='text_delta', text='old summary')
    with pytest.raises(ValueError, match='semantic_source_changed'):
        await s.prepare(model=Model(), messages=rows, source=lambda: rows,
            working=WorkingSnapshot(session_id='changed'), abort=AbortController(), account=lambda _: None, persist=lambda: None)


def test_publication_failure_does_not_retire_source(isolated, monkeypatch):
    from memory import wsc_semantic_compaction as s
    from memory.wsc_handoff_transaction import fingerprint
    from memory.working import WorkingSnapshot
    rows = [{'role': 'assistant', 'content': str(i)} for i in range(12)]
    working = WorkingSnapshot(session_id='failure')
    candidate = dict(text='summary', cut=6, rows=rows, previous_cursor=0, source_fingerprint=fingerprint(rows))
    from memory.wsc_semantic_binding import capture
    candidate['binding'] = capture(isolated, working)
    monkeypatch.setattr('memory.working.flush', lambda *args: None)
    with pytest.raises(ValueError, match='publication_working_not_durable'):
        s.publish(candidate, rows, working, cwd=isolated)
    assert working.compact_cursor == 0 and working.c2_summary_text == ''
    from memory.wsc_head_store import load
    assert load('failure', cwd=str(isolated), cursor=0, messages=rows) is None


@pytest.mark.asyncio
async def test_frozen_restart_next_fold_and_failed_generation(isolated):
    from evals.wsc_production_continuation import ProductionTask, PublishedRead
    from memory import wsc_semantic_compaction as s, wsc_head_store as hs
    from memory.wsc_handoff_transaction import fingerprint
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    from msgtypes.message import Message, ToolUse
    task = ProductionTask(isolated, [{'id': str(i), 'role': 'user' if i == 0 else 'assistant',
        'content': 'EXACT_COLD_VALUE=28317' if i == 0 else 'prior observation ' + str(i)} for i in range(20)])
    task.persist()
    def candidate(text):
        from memory.wsc_semantic_binding import capture
        rows = task.source()
        return dict(text=text, rows=rows, cut=s.boundary(rows, task.working),
            binding=capture(isolated, task.working),
            previous_cursor=task.working.compact_cursor, source_fingerprint=fingerprint(rows))
    first = s.publish(candidate('Current task: unfinished report.'), task.source(), task.working, cwd=isolated)
    head_bytes = hs.path_for(task.working.session_id).read_bytes()
    original = json.loads(head_bytes)
    objects = {name: __import__('pathlib').Path(name).read_bytes() for name in original['publication']['objects']}
    task.store.append(Message(role='user', content='Add a section to the report.'))
    task.persist()
    assert task.project()[0] == first[0]
    assert hs.path_for(task.working.session_id).read_bytes() == head_bytes
    task = task.restart()
    assert task.project()[0] == first[0]
    class Empty:
        last_usage = None
        context_limit = 100000
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            if False: yield ModelChunk(kind='text_delta', text='')
    for i in range(12): task.store.append(Message(role='assistant', content='new observation '+str(i)))
    with pytest.raises(ValueError, match='semantic_generation_empty'):
        await s.prepare(model=Empty(), messages=task.project(), source=task.source, working=task.working,
            abort=AbortController(), account=lambda _: None, persist=task.persist)
    assert hs.path_for(task.working.session_id).read_bytes() == head_bytes
    reader = PublishedRead(task, original)
    result = await reader.execute(ToolUse('recall', 'Read', {'file_path': original['view_path'], 'offset': 1, 'limit': 1}), AbortController())
    assert not result.is_error and 'EXACT_COLD_VALUE=28317' in str(result.content)
    second = s.publish(candidate('Current task: unfinished report with new section.'), task.source(), task.working, cwd=isolated)
    assert second[0] != first[0]
    task = task.restart()
    assert task.project() == second
    for name, raw in objects.items(): assert __import__('pathlib').Path(name).read_bytes() == raw


@pytest.mark.asyncio
async def test_long_record_exact_chunks_and_native_read(isolated):
    from memory.wsc_semantic_evidence import publish
    from memory.working import WorkingSnapshot
    from tools.file_read_tool.file_read_tool import FileReadTool
    from engine.abort import AbortController
    from pathlib import Path
    import ast, hashlib
    from memory.wsc_publication import _READ
    rows = [{'id': 'long', 'role': 'user', 'content': '原始内容\n' * 30000}]
    raw, entrance = publish(rows, 0, WorkingSnapshot(session_id='long'), isolated)
    assert json.loads(raw.read_text(encoding='utf-8')) == rows[0]
    directory = Path(ast.literal_eval(_READ.search(entrance).group(1)))
    readable = Path(json.loads(directory.read_text(encoding='utf-8').splitlines()[0])['views']['compression'])
    records = [json.loads(line) for line in readable.read_text(encoding='utf-8').splitlines()]
    text = ''.join(record['text'] for record in records[1:])
    assert hashlib.sha256(text.encode()).hexdigest() == records[0]['sha256']
    assert json.loads(text) == rows[0]
    reader = FileReadTool(cwd=str(isolated))
    result = await reader.execute({'file_path': str(readable), 'offset': len(records)-1, 'limit': 2}, AbortController())
    assert not result.is_error and str(records[-1]['end']) in str(result.content)


@pytest.mark.asyncio
async def test_media_published_entrance_preserves_owned_bytes(isolated, monkeypatch):
    from evals.wsc_recovered_result_behavior import actual
    from memory import wsc_semantic_compaction as s, wsc_head_store as hs
    from memory.wsc_handoff_transaction import fingerprint
    from memory.working import WorkingSnapshot
    from tools.file_read_tool.file_read_tool import FileReadTool
    from engine.abort import AbortController
    from pathlib import Path
    import base64
    monkeypatch.setenv('XEYO_WSC_MEDIA_ARCHIVE', '1')
    monkeypatch.setenv('XEYO_MEDIA_DIR', str(isolated/'media'))
    media = actual(media=True)
    rows = [media] + [{'role':'assistant', 'content':str(i)} for i in range(12)]
    state = WorkingSnapshot(session_id='media')
    from memory.wsc_semantic_binding import capture
    s.publish(dict(text='Image observed.', rows=rows, cut=6, previous_cursor=0,
                   binding=capture(isolated, state),
                   source_fingerprint=fingerprint(rows)), rows, state, cwd=isolated)
    rec = json.loads(hs.path_for('media').read_text(encoding='utf-8'))
    catalog = next(Path(name) for name in rec['publication']['objects'] if 'media-index.' in name)
    record = json.loads(catalog.read_text(encoding='utf-8'))
    expected = base64.b64decode(media['content'][0]['content'][1]['image_url']['url'].split(';base64,')[1])
    assert Path(record['image_path']).read_bytes() == expected
    reader = FileReadTool(cwd=str(isolated))
    reader.set_vision_enabled(True)
    result = await reader.execute({'file_path': record['image_path']}, AbortController())
    assert not result.is_error and result.content


@pytest.mark.asyncio
@pytest.mark.parametrize('empty', [False, True])
async def test_real_manual_compaction_entry(isolated, empty):
    from types import SimpleNamespace
    from engine.manual_compaction import compact
    from engine.budget import BudgetTracker
    from engine.workspace_context import get_execution_context
    from prompt.assembler import PromptAssembler
    from model.chunks import ModelChunk
    from evals.wsc_production_continuation import ProductionTask
    task = ProductionTask(isolated, [{'role':'assistant', 'content':str(i)} for i in range(15)], session='manual')
    class Prompt(PromptAssembler):
        async def build_system(self, **kwargs): return 'fixture'
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            assert get_execution_context().session_id == 'manual'
            assert {t['name'] for t in tools} == {'HandoffSource', 'HandoffCatalog'}
            self.last_usage = {'prompt_tokens': 100, 'completion_tokens': 10}
            if not empty: yield ModelChunk(kind='text_delta', text='Current report is incomplete.')
    session = SimpleNamespace(working=task.working, messages=task.store, budget=BudgetTracker(),
        cwd=str(isolated), session_id='manual', transcript_persist_index=0,
        transcript_known_ids=set(), is_session_persistence_disabled=lambda: False)
    engine = SimpleNamespace(_session=session, _config={'cwd':str(isolated), 'tools':[]},
        _runtime_context=None, _permission_profile='workspace_write', _provider='deepseek',
        _model_name='fixture', _model=Model(), _prompt=Prompt(), _tools=task.registry,
        _date_iso='2026-10-15', budget_snapshot=lambda: {})
    result = await compact(engine)
    assert result['ok'] is not empty and result['advanced'] is not empty
    assert (task.working.compact_cursor > 0) is not empty
    assert session.budget.used_tokens == 110
    assert not get_execution_context()
