"""Full-state declaration schema and bounded native rejection recovery."""
from copy import deepcopy
import json

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate, source_schema, MAX_REQUESTS
from memory.wsc_handoff_validation import validate, StateError
from model.chunks import ModelChunk
from model.deepseek import _normalize_messages_for_openai
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_scope_encoding import Model, inline
from tests.wsc.test_task_phase import sources, declaration
from tools.todo_write_tool.todo_write_tool import TodoWriteTool, parse_input, TodoWriteInput


def test_complete_protocol_is_narrower_than_general_todo_merge():
    generic = TodoWriteTool().schema()
    before = deepcopy(generic)
    dedicated, _ = source_schema(generic, sources(), scope_protocol=True)
    assert generic == before
    assert generic['input_schema']['properties']['merge']['type'] == 'boolean'
    assert 'const' not in generic['input_schema']['properties']['merge']
    assert dedicated['input_schema']['properties']['merge'] == {'type': 'boolean', 'const': False, 'default': False}
    raw = dict(declaration(), merge=True)
    assert isinstance(parse_input(raw), TodoWriteInput)
    with pytest.raises(StateError) as error: validate(raw, sources(), require_phase=True)
    assert error.value.detail == {'error': 'handoff_full_state_required', 'field': '$.merge',
                                  'received': True, 'allowed_values': [False]}


@pytest.mark.parametrize('value', [True, 0, None, 'false', {}])
def test_invalid_merge_values_never_become_full_replace(value):
    raw = dict(declaration(), merge=value)
    before = deepcopy(raw)
    with pytest.raises(ValueError, match='handoff_full_state_required'):
        validate(raw, sources(), require_phase=True)
    assert raw == before


@pytest.mark.parametrize('explicit', [False, True])
def test_full_replace_false_and_omitted_remain_valid(explicit):
    raw = declaration()
    if explicit: raw['merge'] = False
    assert validate(raw, sources(), require_phase=True).merge is False


class MergeModel(Model):
    def __init__(self, *, problem='merge', persistent=False):
        super().__init__()
        self.problem, self.persistent = problem, persistent

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy({'messages': messages, 'tools': tools}))
        self.last_usage = {'prompt_tokens': 12, 'completion_tokens': 18}
        raw = inline(declaration())
        if len(self.requests) == 1 or self.persistent:
            if self.problem == 'merge': raw['merge'] = True
            else: del raw['checkpoint']
        else:
            feedback = json.loads(messages[-1]['content'][0]['content'])
            assert feedback['error'] == 'handoff_full_state_required'
            assert feedback['field'] == ('$.merge' if self.problem == 'merge' else '$.checkpoint')
        yield ModelChunk(kind='text_delta', text='original output body')
        yield ModelChunk(kind='reasoning_delta', text='original thought')
        yield ModelChunk(kind='tool_use', tool_use=ToolUse('attempt-' + str(len(self.requests)), 'TodoWrite', raw))


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['merge', 'checkpoint'])
async def test_mechanical_rejection_continues_with_original_frame_and_full_guard(problem):
    rows, model, usage = sources(), MergeModel(problem=problem), []
    before = deepcopy(rows)
    result = await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
        TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert result.input == declaration() and len(usage) == 2
    assert rows == before and len(model.requests) == 2
    assistant = next(row for row in model.requests[1]['messages'] if row['role'] == 'assistant')
    wire = _normalize_messages_for_openai([assistant])[0]
    original = json.loads(wire['tool_calls'][0]['function']['arguments'])
    assert (original.get('merge') is True) if problem == 'merge' else ('checkpoint' not in original)
    assert wire['content'] == 'original output body' and wire['reasoning_content'] == 'original thought'
    assert model.requests[1] in model.counted


@pytest.mark.asyncio
async def test_repeated_illegal_merge_is_bounded_and_not_committed():
    rows, model, usage = sources(), MergeModel(persistent=True), []
    before = deepcopy(rows)
    with pytest.raises(ValueError, match='handoff_full_state_required'):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert len(model.requests) == MAX_REQUESTS and len(usage) == MAX_REQUESTS
    assert rows == before


@pytest.mark.asyncio
async def test_budget_denial_after_rejection_precedes_another_request():
    model, usage = MergeModel(), []
    def deny(): raise ValueError('test_budget_denied')
    with pytest.raises(ValueError, match='test_budget_denied'):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], sources(),
            TodoWriteTool().schema(), AbortController(), account=usage.append, admit_next=deny, scope_protocol=True)
    assert len(model.requests) == 1 and len(usage) == 1


@pytest.mark.asyncio
async def test_rejected_merge_never_publishes_before_real_commit_restore_and_fold(tmp_path, monkeypatch):
    from tests.wsc import test_handoff_scope_encoding as contract
    monkeypatch.setattr(contract, 'Model', MergeModel)
    await contract.test_inline_declaration_commits_restores_and_keeps_published_head(tmp_path, monkeypatch)
    transcript = (tmp_path / 'scope.jsonl').read_text(encoding='utf-8')
    assert 'attempt-1' not in transcript and 'attempt-2' in transcript
