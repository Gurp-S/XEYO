"""Reference estimates cover actual input and retain conservative fallbacks."""
from copy import deepcopy

import pytest

from engine.abort import AbortController
from memory.wsc_counted_input import CountedInput
from memory.wsc_timing import request_measure
from model.deepseek import DeepSeekModelClient
from model.deepseek_count import BASIS


def client(**options):
    return DeepSeekModelClient(api_key='not-sent', model='deepseek-flash',
                               base_url=options.pop('base_url', 'https://api.deepseek.com'),
                               thinking='disabled', **options)


def test_estimate_covers_current_encoded_input_without_mutating_body_or_usage():
    model = client()
    messages = [{'role': 'system', 'content': '只读会话'},
                {'role': 'user', 'content': 'field ' * 200}]
    original = deepcopy(messages)
    model.last_usage = {'prompt_tokens': 900000}
    body = model._build_body(messages, [], stream=False)
    measure = request_measure(messages, [], context_limit=1048576, model=model)
    assert measure.basis == BASIS and measure.input_tokens < 400
    assert measure.action == 'keep' and not measure.notify
    assert messages == original and model._build_body(messages, [], stream=False) == body
    assert model.last_usage == {'prompt_tokens': 900000}


@pytest.mark.asyncio
async def test_wrapper_reuses_only_the_same_input_and_includes_tool_schema(monkeypatch):
    model = client()
    original = model.context_token_measure
    sources = []
    def measured(source):
        sources.append(deepcopy(source))
        return original(source)
    monkeypatch.setattr(model, 'context_token_measure', measured)
    counted = CountedInput(model, AbortController())
    messages = [{'role': 'user', 'content': 'current objective'}]
    tool = {'type': 'function', 'function': {'name': 'Read', 'description': 'Read file',
            'parameters': {'type': 'object', 'properties': {'file_path': {'type': 'string'}}}}}
    await counted.prime(messages, [])
    first = request_measure(messages, [], context_limit=1000, model=counted)
    await counted.prime(messages, [])
    assert len(sources) == 1
    await counted.prime(messages, [tool])
    second = request_measure(messages, [tool], context_limit=1000, model=counted)
    assert len(sources) == 2 and second.input_tokens > first.input_tokens
    assert second.basis == first.basis == BASIS
    assert sources[-1] == model.context_input(messages, [tool])
    changed = messages + [{'role': 'user', 'content': '上下文已达80%（当前完整请求估算）'}]
    await counted.prime(changed, [tool])
    assert len(sources) == 3
    third = request_measure(changed, [tool], context_limit=1000, model=counted)
    assert third.input_tokens > second.input_tokens


@pytest.mark.parametrize('body', [
    '<image>local.png</image>', '<｜deepseek_image｜>',
])
def test_ambiguous_image_markup_has_no_reference_count(body, monkeypatch):
    calls = []
    def unexpected():
        calls.append(True)
        raise AssertionError('Media must not reach text tokenizer')
    monkeypatch.setattr('model.deepseek_count.tokenizer', unexpected)
    assert client().context_token_measure({'messages': [{'role': 'user', 'content': body}]}) is None
    assert not calls


@pytest.mark.parametrize('origin', ['https://gateway.example', 'http://api.deepseek.com',
                                   'https://api.deepseek.com/anthropic'])
def test_other_templates_do_not_use_native_reference(origin, monkeypatch):
    calls = []
    def unexpected():
        calls.append(True)
        raise AssertionError('Non-native origin must not load reference assets')
    monkeypatch.setattr('model.deepseek_count.tokenizer', unexpected)
    assert client(base_url=origin).context_token_measure({'messages': [{'role': 'user', 'content': 'hello'}]}) is None
    assert not calls


@pytest.mark.parametrize('failure', [ImportError, ValueError])
def test_missing_dependency_or_bad_asset_keeps_explicit_estimate(monkeypatch, failure):
    def unavailable():
        raise failure('reference unavailable')
    monkeypatch.setattr('model.deepseek_count.tokenizer', unavailable)
    model = client()
    measured = request_measure([{'role': 'user', 'content': 'hello'}], [], context_limit=1048576, model=model)
    assert measured.basis == 'provider_normalized_input_utf8_quarters_estimate'


def test_unknown_alias_does_not_guess_a_reference_template(monkeypatch):
    model = client()
    model._model = 'deepseek-flash-future'
    assert model.context_token_measure({'messages': [{'role': 'user', 'content': 'hello'}]}) is None


@pytest.mark.parametrize('thinking', ['disabled', 'enabled'])
def test_gui_compat_route_uses_same_reference_input_and_mode(thinking):
    from model.openai_compat import OpenAICompatClient
    from model.deepseek_count import measure
    model = OpenAICompatClient(api_key='not-sent', base_url='https://api.deepseek.com/v1',
                              model='deepseek-flash', provider='deepseek', thinking=thinking,
                              reasoning_effort='max')
    messages = [{'role': 'system', 'content': '只读会话'}, {'role': 'user', 'content': 'current goal'}]
    source = model.context_input(messages, [])
    body = model._build_body(messages, [], stream=False)
    assert source['messages'] == body['messages']
    expected = measure(source, model=body['model'], base_url=model._base_url,
                       thinking=body['thinking']['type'], reasoning_effort=body.get('reasoning_effort'))
    counted = request_measure(messages, [], context_limit=1048576, model=model)
    assert (counted.input_tokens, counted.basis) == expected


def test_other_compat_provider_does_not_infer_deepseek_template():
    from model.openai_compat import OpenAICompatClient
    model = OpenAICompatClient(api_key='not-sent', base_url='https://api.deepseek.com',
                              model='deepseek-flash', provider='openai')
    assert model.context_token_measure({'messages': [{'role': 'user', 'content': 'hello'}]}) is None
