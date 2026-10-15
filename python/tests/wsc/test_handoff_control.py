"""Control carrier contracts; semantic quality is measured by the paid trial."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from engine.abort import AbortController
from memory.wsc_handoff_control import legacy_message, factual_message, split_messages
from memory.wsc_handoff_generation import generate, REQUEST
from model.anthropic import AnthropicModelClient
from model.deepseek import DeepSeekModelClient
from model.openai_compat import OpenAICompatClient
from tests.wsc.test_handoff_scope_encoding import Model
from tests.wsc.test_task_phase import sources, declaration
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


def test_legacy_boundary_is_byte_identical_and_fact_has_only_invocation_type():
    identities = [{'source': 0, 'message_id': 'spec', 'role': 'user'}]
    before = deepcopy(identities)
    suffix = '\n来源身份=' + json.dumps(identities, ensure_ascii=False) + '\n来源总数=1'
    assert legacy_message(identities, 1) == {'role': 'user', 'content': REQUEST + suffix}
    actual = factual_message(identities, 1)
    assert actual == {'role': 'user', 'content': 'request_kind=task_state_declaration' + suffix}
    assert identities == before
    assert not set(actual) & {'id', 'message_id', 'task_id', 'phase_id'}


@pytest.mark.parametrize('provider', ['deepseek', 'openai', 'anthropic'])
def test_fact_carrier_preserves_last_user_contract_after_assistant_source(provider):
    clients = {
        'deepseek': lambda: DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled'),
        'openai': lambda: OpenAICompatClient(api_key='not-sent', base_url='https://api.openai.com/v1', model='fixture'),
        'anthropic': lambda: AnthropicModelClient(api_key='not-sent', model='fixture', thinking='enabled')}
    client = clients[provider]()
    original = [{'role': 'system', 'content': 'original system'}, {'role': 'assistant', 'content': 'original checkpoint'}]
    before = deepcopy(original)
    control = factual_message([], 0)
    body = client._build_body([*original, control], [], stream=False)
    assert body['messages'][-1]['role'] == 'user'
    assert 'request_kind=task_state_declaration' in json.dumps(body['messages'][-1])
    assert original == before
    assert client.context_input([*original, control], [])['messages'] == body['messages']


@pytest.mark.asyncio
async def test_fact_control_enters_actual_generation_counting_not_task_sources():
    rows, model, usage = sources(), Model(), []
    before = deepcopy(rows)
    with patch('memory.wsc_handoff_control.message', factual_message):
        result = await generate(model, [{'role': 'assistant', 'content': 'checkpoint'}], rows,
            TodoWriteTool().schema(), AbortController(), account=usage.append, scope_protocol=True)
    assert result.input == declaration() and len(usage) == 2
    first = model.requests[0]
    assert first['messages'][-1]['role'] == 'user'
    assert first['messages'][-1]['content'].startswith('request_kind=task_state_declaration\n')
    assert first in model.counted
    assert rows == before
    assert all(not r.get('content', '').startswith('request_kind=') for r in rows if isinstance(r.get('content'), str))
    assert not any(uid.startswith('request_kind') for uid in result.input['checkpoint']['context_message_ids'])


def test_system_diagnostic_would_remove_trailing_user_for_anthropic():
    # This is why system-only is not a universal default even if Flash likes it.
    client = AnthropicModelClient(api_key='not-sent', model='fixture', thinking='enabled')
    control = dict(factual_message([], 0), role='system')
    body = client._build_body([{'role': 'user', 'content': 'task'},
                              {'role': 'assistant', 'content': 'checkpoint'}, control], [], stream=False)
    assert body['messages'][-1]['role'] == 'assistant'
    assert 'request_kind=task_state_declaration' in body['system']


@pytest.mark.parametrize('provider', ['deepseek', 'openai', 'anthropic'])
def test_split_carriers_preserve_real_provider_end_role_and_single_type_fact(provider):
    clients = {
        'deepseek': lambda: DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled'),
        'openai': lambda: OpenAICompatClient(api_key='not-sent', base_url='https://api.openai.com/v1', model='fixture'),
        'anthropic': lambda: AnthropicModelClient(api_key='not-sent', model='fixture', thinking='enabled')}
    client = clients[provider]()
    identities = [{'message_id': 'spec', 'role': 'user', 'source': 0}]
    original = [{'role': 'user', 'content': 'task'}, {'role': 'assistant', 'content': 'checkpoint'}]
    before = deepcopy(original)
    carriers = split_messages(identities, 1)
    body = client._build_body([*original, *carriers], [], stream=False)
    assert body['messages'][-1]['role'] == 'user'
    assert json.dumps(body, ensure_ascii=False).count('request_kind=task_state_declaration') == 1
    assert 'spec' in json.dumps(body['messages'][-1])
    if provider == 'anthropic': assert 'request_kind=task_state_declaration' in body['system']
    assert original == before
    assert client.context_input([*original, *carriers], [])['messages'] == body['messages']


@pytest.mark.asyncio
async def test_split_type_and_evidence_both_enter_counted_generator_without_source_mutation():
    rows, model = sources(), Model()
    before = deepcopy(rows)
    with patch('memory.wsc_handoff_control.messages', split_messages):
        result = await generate(model, [{'role': 'assistant', 'content': 'checkpoint'}], rows,
            TodoWriteTool().schema(), AbortController(), account=lambda usage: None, scope_protocol=True)
    first = model.requests[0]
    assert first['messages'][-2] == {'role': 'system', 'content': 'request_kind=task_state_declaration'}
    assert first['messages'][-1]['role'] == 'user' and first['messages'][-1]['content'].startswith('来源身份=')
    assert first in model.counted
    assert result.input == declaration() and rows == before
