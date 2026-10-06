"""Exercise live history recovery, item-local recall and recoverable fragments."""
from dataclasses import replace
import pytest
from engine.query_engine import QueryEngine
from engine.execution_context import ExecutionContext
from engine.workspace_context import bind_workspace_context
from model.fake import FakeModelClient
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from server.session_pool import ModelConfig, SessionPool
from memory.governance import parse_and_validate, today_iso
from memory.memdir import workspace_id, write_note, rewrite_index
from memory.search import search
from memory.runtime import _store_c2_fragments
from memory.working import WorkingSnapshot
from memory import memindex


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for key in ('HOME', 'MEMORY_DIR', 'SESSIONS_DIR', 'SNAPSHOTS_DIR', 'USAGE_DIR', 'JOURNAL_DIR'):
        monkeypatch.setenv('XEYO_' + key, str(tmp_path / key.lower()))
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['config', 'eviction'])
async def test_pool_recovers_live_assistant_and_tool_history(isolated, monkeypatch, operation):
    pool = SessionPool(str(isolated), max_engines=1)
    def build(cfg, *, session_id, initial_messages=None, cwd):
        registry = ToolRegistry()
        registry.register(EchoTool())
        return QueryEngine({'cwd': cwd, 'session_id': session_id, 'initial_messages': initial_messages,
            'model_client': FakeModelClient(), 'tools': registry, 'provider': 'fake', 'model': cfg.model})
    monkeypatch.setattr(pool, '_build', build)
    cfg = ModelConfig(provider='fake', model='probe', api_key='offline', base_url='http://offline.invalid')
    engine = pool.get_or_create('live-history', cfg)
    _ = [e async for e in engine.submit('echo:important-data')]
    expected = [(m.id, m.role, m.content) for m in engine._session.messages.items]
    assert [m.role for m in engine.mutable_messages] == ['user', 'assistant', 'tool', 'assistant']
    public = engine.mutable_messages
    public.clear()
    assert not engine.is_empty()
    if operation == 'eviction':
        pool.get_or_create('other', cfg)
    else:
        cfg = replace(cfg, max_budget_usd=0.5)
    recovered = pool.get_or_create('live-history', cfg)
    assert [(m.id, m.role, m.content) for m in recovered.mutable_messages] == expected
    assert not recovered.hydrate_if_empty([])


def make_note(ident, title, body, *, scope='workspace', date='2020-01-01'):
    return parse_and_validate({'id': ident, 'type': 'project', 'title': title, 'scope': scope,
        'source': {'kind': 'user'}, 'confidence': 1.0, 'status': 'active', 'created_at': date,
        'updated_at': date, 'last_confirmed_at': date}, body)


@pytest.mark.parametrize('scope', ['workspace', 'user'])
def test_memory_index_never_supplies_another_notes_match(isolated, scope):
    wsid = workspace_id(str(isolated))
    notes = [make_note('target', 'archivedsetting', 'old setting', scope=scope),
        make_note('noise', 'theme', 'color is blue', scope=scope, date=today_iso()),
        make_note('cache', 'cache', 'enabled', scope=scope),
        make_note('ttl', 'ttl', '600 seconds', scope=scope),
        make_note('cjk', '中文规则', '必须运行真实数据库测试', scope=scope)]
    for n in notes: write_note(n, wsid=wsid)
    rewrite_index(notes, wsid='user' if scope == 'user' else wsid)
    assert [n.id for n in search('archivedsetting', cwd=str(isolated), touch=False)] == ['target']
    assert search('cache ttl', cwd=str(isolated), touch=False) == []
    assert [n.id for n in search('数据库测试', cwd=str(isolated), touch=False)] == ['cjk']


def test_c2_fragments_keep_distinct_blocks_and_recent_stack(isolated):
    sid = 'fragment-identities'
    text = ('Traceback (most recent call last):\n  File "old.py", line 1, in run\n'
        'ValueError: OLD_ERROR\n\nphase boundary\n\n'
        'Traceback (most recent call last):\n  File "recent.py", line 2, in run\nRuntimeError: RECENT_ERROR\n')
    left = [{'role': 'assistant', 'content': [{'type': 'text', 'text': 'first=one\n'},
        {'type': 'text', 'text': 'second=two\n'}]}, {'role': 'tool', 'content': text}]
    with bind_workspace_context(ExecutionContext(session_id=sid, cwd=str(isolated))):
        for _ in range(2):
            _store_c2_fragments(WorkingSnapshot(session_id=sid), left)
        kv = memindex.get_fragments(sid, 0, kind='kv')
        stacks = memindex.get_fragments(sid, 1, kind='stack')
        assert {r['text'].strip() for r in kv} == {'first=one', 'second=two'}
        assert len(stacks) == 2
        assert 'RECENT_ERROR' in stacks[0]['text']
        assert 'OLD_ERROR' in stacks[1]['text']


def test_recent_stack_survives_fragment_row_cap(isolated):
    sid = 'fragment-cap'
    left = [{'role': 'tool', 'content': f'unique_{i}=value_{i}\n'} for i in range(450)]
    left.append({'role': 'tool', 'content': 'Traceback (most recent call last):\n  File "last.py", line 1\nRuntimeError: LATEST\n'})
    with bind_workspace_context(ExecutionContext(session_id=sid, cwd=str(isolated))):
        _store_c2_fragments(WorkingSnapshot(session_id=sid), left)
        assert 'LATEST' in memindex.get_fragments(sid, 450, kind='stack')[0]['text']
