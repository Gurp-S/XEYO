"""The eval reader's declared evidence must reach native permission checks."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    from evals.wsc_cold_recovery_diagnostic import Reader
    from tools.tool_registry import ToolRegistry
    from tools.file_read_tool.file_read_tool import FileReadTool
    root = tmp_path / 'task'
    root.mkdir()
    for key in ('XEYO_HOME', 'XEYO_USAGE_DIR', 'XEYO_SESSIONS_DIR', 'XEYO_SPILL_DIR'):
        monkeypatch.setenv(key,str(tmp_path/key))
    monkeypatch.setenv('XEYO_PERMISSION_MODE','default')
    public = tmp_path / 'shared' / 'source.jsonl'
    public.parent.mkdir()
    public.write_text('DECLARED_EXACT_EVIDENCE\n',encoding='utf-8')
    secret = public.parent / 'private-answer.json'
    secret.write_text('PRIVATE_ANSWER\n',encoding='utf-8')
    registry = ToolRegistry(cwd=str(root))
    registry.register(FileReadTool(cwd=str(root)))
    task = SimpleNamespace(root=root,registry=registry,working=SimpleNamespace(session_id='reader-scope'))
    return Reader(task,{'objects':[str(public)]}),public,secret


@pytest.mark.asyncio
async def test_declared_external_read_and_context_restore(evidence):
    from engine.abort import AbortController
    from engine.execution_context import ExecutionContext
    from engine.workspace_context import bind_workspace_context, get_workspace_context
    from msgtypes.message import ToolUse
    reader,public,_ = evidence
    parent = ExecutionContext(session_id='parent',cwd=str(public.parent),allowed_paths=[])
    with bind_workspace_context(parent):
        result = await reader.execute(ToolUse('external','Read',
            {'file_path':str(public),'offset':1,'limit':1}),AbortController())
        assert get_workspace_context() is parent
    assert not result.is_error and 'DECLARED_EXACT_EVIDENCE' in str(result.content)


@pytest.mark.asyncio
async def test_declared_external_grep(evidence):
    from engine.abort import AbortController
    from msgtypes.message import ToolUse
    reader,public,_ = evidence
    result = await reader.execute(ToolUse('external-grep','Grep',
        {'path':str(public),'pattern':'DECLARED_EXACT_EVIDENCE','output_mode':'content'}),AbortController())
    assert not result.is_error and 'DECLARED_EXACT_EVIDENCE' in str(result.content)


@pytest.mark.asyncio
async def test_private_sibling_and_mutations_stay_denied(evidence):
    from engine.abort import AbortController
    from msgtypes.message import ToolUse
    reader,public,secret = evidence
    for tool,args in [('Read',{'file_path':str(secret)}),('Grep',{'path':str(public.parent),'pattern':'.'}),
                      ('Write',{'file_path':str(public),'content':'changed'}),('Bash',{'command':'echo bad'})]:
        result = await reader.execute(ToolUse('denied-'+tool,tool,args),AbortController())
        assert result.is_error and 'PRIVATE_ANSWER' not in str(result.content)
    assert public.read_text(encoding='utf-8') == 'DECLARED_EXACT_EVIDENCE\n'
