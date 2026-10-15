"""Persistent identity and active-task preconditions at the native boundary."""
from copy import deepcopy
import json

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate, MAX_REQUESTS, source_schema
from memory.wsc_handoff_validation import validate, StateError
from model.chunks import ModelChunk
from model.deepseek import _normalize_messages_for_openai
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_scope_encoding import Model, inline
from tests.wsc.test_task_phase import declaration, sources
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


@pytest.mark.parametrize('identity', [None, '', ' \t\n', 7, {}])
def test_missing_or_blank_original_identity_is_rejected_without_mutation(identity):
    raw = declaration()
    if identity is None:
        del raw['todos'][0]['id']
    else:
        raw['todos'][0]['id'] = identity
    original = deepcopy(raw)
    with pytest.raises(StateError) as error:
        validate(raw, sources(), require_phase=True)
    assert error.value.detail == {'error': 'handoff_step_identity_invalid', 'field': '$.todos[*].id',
                                 'missing_or_blank_indices': [0], 'duplicate_normalized_ids': []}
    assert raw == original


@pytest.mark.parametrize('other', ['report', ' report ', '\treport\n'])
def test_distinct_wire_spellings_cannot_collapse_into_duplicate_persistent_ids(other):
    raw = declaration()
    raw['todos'].append(dict(raw['todos'][0], id=other))
    before = deepcopy(raw)
    with pytest.raises(StateError) as error:
        validate(raw, sources(), require_phase=True)
    assert error.value.detail['duplicate_normalized_ids'] == ['report']
    assert raw == before


def test_single_normalized_identity_and_distinct_other_step_remain_compatible():
    raw = declaration()
    raw['todos'][0]['id'] = ' report '
    raw['todos'].append(dict(raw['todos'][0], id='review'))
    assert [x.id for x in validate(raw, sources(), require_phase=True).todos] == ['report', 'review']
    assert raw['todos'][0]['id'] == ' report '


@pytest.mark.parametrize('objective', [None, '', ' \t\n'])
def test_active_objective_error_identifies_absent_nonempty_value(objective):
    raw = declaration()
    if objective is None:
        del raw['checkpoint']['objective']
    else:
        raw['checkpoint']['objective'] = objective
    with pytest.raises(StateError) as error:
        validate(raw, sources(), require_phase=True)
    assert error.value.detail == {'error': 'handoff_active_context_required',
                                 'nonempty_fields_missing': ['$.checkpoint.objective']}


def test_active_no_source_and_no_objective_error_reports_both_without_inventing_either():
    raw = {'todos': declaration()['todos'], 'checkpoint': {'context_message_ids': []}}
    before = deepcopy(raw)
    with pytest.raises(StateError) as error:
        validate(raw, sources())
    assert error.value.detail['nonempty_fields_missing'] == [
        '$.checkpoint.objective', '$.checkpoint.context_message_ids']
    assert raw == before


@pytest.mark.parametrize('empty', [True, False])
def test_terminal_declaration_retains_empty_objective_barrier(empty):
    raw = {'todos': [] if empty else [dict(declaration()['todos'][0], status='completed')],
           'checkpoint': {'context_message_ids': []}}
    assert validate(raw, sources()).checkpoint['objective'] == ''


@pytest.mark.parametrize('phase', [True, False])
def test_dedicated_shape_exposes_existing_preconditions_without_mutating_general_schema(phase):
    original = TodoWriteTool().schema()
    before = deepcopy(original)
    specific, _ = source_schema(original, sources(), scope_protocol=phase)
    assert original == before
    generic_id = original['input_schema']['properties']['todos']['items']['properties']['id']
    assert 'minLength' not in generic_id and 'auto-generated' in generic_id['description']
    item = specific['input_schema']['properties']['todos']['items']
    assert 'id' in item['required']
    assert 'auto-generated' not in item['properties']['id']['description']
    for field in ('id', 'content', 'activeForm'):
        assert item['properties'][field]['minLength'] == 1
        assert item['properties'][field]['pattern'] == r'\S'
    conditional = specific['input_schema']['allOf'][0]
    assert conditional['if']['properties']['todos']['contains']['properties']['status']['enum'] == [
        'pending', 'in_progress']
    checkpoint = conditional['then']['properties']['checkpoint']
    assert checkpoint['required'] == ['objective', 'context_message_ids'] + (['phase_state'] if phase else [])
    assert checkpoint['properties']['context_message_ids']['minItems'] == 1
    assert checkpoint['properties']['objective'] == {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
    # Object equality cannot express uniqueness of just the id property.
    assert 'uniqueItems' not in specific['input_schema']['properties']['todos']


class ShapeModel(Model):
    def __init__(self, problem='duplicate', persistent=False):
        super().__init__()
        self.problem, self.persistent = problem, persistent

    def broken(self):
        raw = inline(declaration())
        if self.problem == 'duplicate':
            raw['todos'].append(dict(raw['todos'][0], id=' report '))
        else:
            del raw['checkpoint']['objective']
        return raw

    async def stream(self, messages, tools, abort):
        self.requests.append(deepcopy({'messages': messages, 'tools': tools}))
        self.last_usage = {'prompt_tokens': 12, 'completion_tokens': 18}
        raw = self.broken() if len(self.requests) == 1 or self.persistent else inline(declaration())
        if len(self.requests) > 1:
            error = json.loads(messages[-1]['content'][0]['content'])
            if self.problem == 'duplicate':
                assert error['duplicate_normalized_ids'] == ['report']
            else:
                assert error['nonempty_fields_missing'] == ['$.checkpoint.objective']
        yield ModelChunk(kind='text_delta', text='unchanged original body')
        yield ModelChunk(kind='reasoning_delta', text='unchanged original thought')
        yield ModelChunk(kind='tool_use', tool_use=ToolUse('shape-' + str(len(self.requests)), 'TodoWrite', raw))


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['duplicate', 'objective'])
async def test_rejected_original_frame_is_counted_and_model_replacement_revalidates(problem):
    rows, model, usage = sources(), ShapeModel(problem), []
    before = deepcopy(rows)
    result = await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
                            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert result.input == declaration() and rows == before and len(usage) == 2
    assert len(model.requests) == 2 and model.requests[1] in model.counted
    assistant = next(x for x in model.requests[1]['messages'] if x['role'] == 'assistant')
    wire = _normalize_messages_for_openai([assistant])[0]
    assert json.loads(wire['tool_calls'][0]['function']['arguments']) == model.broken()
    assert wire['content'] == 'unchanged original body'
    assert wire['reasoning_content'] == 'unchanged original thought'


@pytest.mark.asyncio
@pytest.mark.parametrize('problem,code', [('duplicate', 'handoff_step_identity_invalid'),
                                       ('objective', 'handoff_active_context_required')])
async def test_persistent_invalid_shape_never_escapes_original_request_limit(problem, code):
    model, usage = ShapeModel(problem, persistent=True), []
    rows = sources()
    before = deepcopy(rows)
    with pytest.raises(ValueError, match=code):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], rows,
                       TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert len(model.requests) == MAX_REQUESTS and len(usage) == MAX_REQUESTS and rows == before


@pytest.mark.asyncio
async def test_budget_denial_before_replacement_prevents_second_model_call():
    model, usage = ShapeModel(), []
    def deny():
        raise ValueError('test_budget_denied')
    with pytest.raises(ValueError, match='test_budget_denied'):
        await generate(model, [{'role': 'user', 'content': 'fixture'}], sources(),
                       TodoWriteTool().schema(), AbortController(), account=usage.append,
                       scope_protocol=True, admit_next=deny)
    assert len(model.requests) == len(usage) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['duplicate', 'objective'])
async def test_only_corrected_state_survives_native_commit_restore_and_fold(tmp_path, monkeypatch, problem):
    from tests.wsc import test_handoff_scope_encoding as contract
    monkeypatch.setattr(contract, 'Model', lambda: ShapeModel(problem))
    await contract.test_inline_declaration_commits_restores_and_keeps_published_head(tmp_path, monkeypatch)
    content = (tmp_path / 'scope.jsonl').read_text(encoding='utf-8')
    assert 'shape-1' not in content and 'shape-2' in content
