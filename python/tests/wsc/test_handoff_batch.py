"""Invalid model batches have neutral atomic rejection, not partial execution."""
from copy import deepcopy
import json

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate, MAX_REQUESTS
from model.chunks import ModelChunk
from model.deepseek import _normalize_messages_for_openai
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_scope_encoding import Model, inline
from tests.wsc.test_task_phase import declaration, sources
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


class BatchModel(Model):
    def __init__(self, names, *, persistent=False, reused=False):
        super().__init__()
        self.names, self.persistent, self.reused = names, persistent, reused

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy({'messages': messages, 'tools': tools}))
        self.last_usage = {'prompt_tokens': 10, 'completion_tokens': 20}
        attempt = len(self.requests)
        if attempt == 1 or self.persistent:
            yield ModelChunk(kind='text_delta', text='original batch body')
            yield ModelChunk(kind='reasoning_delta', text='original batch thought')
            for index, name in enumerate(self.names):
                raw = inline(declaration()) if name == 'TodoWrite' else {'message_id': 'permit', 'offset': 0, 'limit': 64}
                yield ModelChunk(kind='tool_use', tool_use=ToolUse('verify' if self.reused else f'batch-{attempt}-{index}', name, raw))
        else:
            yield ModelChunk(kind='tool_use', tool_use=ToolUse('valid', 'TodoWrite', inline(declaration())))


@pytest.mark.asyncio
@pytest.mark.parametrize('names', [
    ['TodoWrite', 'HandoffSource'], ['HandoffCatalog', 'TodoWrite'], ['TodoWrite', 'TodoWrite'],
    ['TodoWrite', 'OtherTaskTool'], ['OtherTaskTool'], ['HandoffSource', 'OtherTaskTool']])
async def test_rejected_batches_execute_nothing_and_preserve_original_frame(names):
    model, rows, usage, reads = BatchModel(names), sources(), [], []
    before = deepcopy(rows)
    result = await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
        TodoWriteTool().schema(), AbortController(), account=usage.append,
        admit_read=lambda: reads.append(True), scope_protocol=True)
    assert result.input == declaration() and reads == [] and rows == before and len(usage) == 2
    request = model.requests[1]
    assistant = next(row for row in request['messages'] if row['role'] == 'assistant')
    wire = _normalize_messages_for_openai([assistant])[0]
    assert wire['content'] == 'original batch body' and wire['reasoning_content'] == 'original batch thought'
    assert [call['function']['name'] for call in wire['tool_calls']] == names
    errors = [row for row in request['messages'] if row['role'] == 'tool']
    assert len(errors) == len(names)
    expected = 'handoff_mixed_declaration' if 'TodoWrite' in names else 'handoff_invalid_call'
    for row in errors:
        assert row['content'][0]['is_error'] is True
        facts = json.loads(row['content'][0]['content'])
        assert facts['error'] == expected and facts['executed_call_ids'] == []
    assert request in model.counted


@pytest.mark.asyncio
@pytest.mark.parametrize('names,error', [(['TodoWrite', 'HandoffSource'], 'handoff_mixed_declaration'),
                                        (['OtherTaskTool'], 'handoff_invalid_call')])
async def test_persistent_bad_batches_stop_at_original_bound(names, error):
    model, rows, usage = BatchModel(names, persistent=True), sources(), []
    before = deepcopy(rows)
    with pytest.raises(ValueError, match=error):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert len(usage) == MAX_REQUESTS and rows == before


@pytest.mark.asyncio
async def test_reused_call_id_stays_fatal_before_any_batch_replay():
    model, usage = BatchModel(['TodoWrite', 'HandoffSource'], reused=True), []
    with pytest.raises(ValueError, match='handoff_call_identity_conflict'):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], sources(),
            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert len(usage) == 1 and len(model.requests) == 1


@pytest.mark.asyncio
async def test_rejected_batch_never_publishes_before_real_commit_restore_and_fold(tmp_path, monkeypatch):
    from tests.wsc import test_handoff_scope_encoding as contract
    monkeypatch.setattr(contract, 'Model', lambda: BatchModel(['TodoWrite', 'HandoffCatalog']))
    await contract.test_inline_declaration_commits_restores_and_keeps_published_head(tmp_path, monkeypatch)
    assert 'batch-1-' not in (tmp_path / 'scope.jsonl').read_text(encoding='utf-8')
