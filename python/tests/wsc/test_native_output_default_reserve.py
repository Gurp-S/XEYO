"""Same wire, opt-in documented defaults and request-total admission."""
import pytest
from model.deepseek import DeepSeekModelClient
from model.deepseek_output_defaults import ENV
from memory.wsc_request_timing import finish
from memory.wsc_timing import decide
from memory.working import WorkingSnapshot


def test_verified_native_default_is_on_with_explicit_control_opt_out(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    assert client.context_output_limit_measure([], []) == (8192, 'provider_documented_default_output_limit')
    monkeypatch.setenv(ENV, '0')
    assert client.context_output_limit_measure([], []) == (None, 'unknown')


@pytest.mark.parametrize('thinking,effort,expected', [('disabled', None, 8192), ('enabled', None, 65536), ('enabled', 'max', 131072)])
def test_default_measurement_ab_preserves_complete_wire(monkeypatch, thinking, effort, expected):
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking=thinking)
    client._reasoning_effort = effort
    messages = [{'role': 'user', 'content': 'Observation.'}]
    before = client._build_body(messages, [], stream=False)
    monkeypatch.setenv(ENV, '0')
    assert client.context_output_limit_measure(messages, []) == (None, 'unknown')
    monkeypatch.setenv(ENV, '1')
    assert client.context_output_limit_measure(messages, []) == (expected, 'provider_documented_default_output_limit')
    assert client._build_body(messages, [], stream=False) == before
    client._max_tokens = 512
    assert client.context_output_limit_measure(messages, []) == (512, 'provider_request_output_limit')


@pytest.mark.parametrize('base', ['https://custom.example', 'http://api.deepseek.com', 'https://api.deepseek.com/proxy'])
def test_custom_origin_has_no_inferred_native_default(monkeypatch, base):
    monkeypatch.setenv(ENV, '1')
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', base_url=base, thinking='disabled')
    assert client.context_output_limit_measure([], []) == (None, 'unknown')


@pytest.mark.parametrize('model', ['other-model', 'deepseek-v4-flash-vision-exp'])
def test_unverified_model_has_no_default_inference(monkeypatch, model):
    monkeypatch.setenv(ENV, '1')
    client = DeepSeekModelClient(api_key='not-sent', model=model, thinking='disabled')
    assert client.context_output_limit_measure([], []) == (None, 'unknown')


@pytest.mark.parametrize('enabled', [False, True])
def test_native_default_enters_request_total_check(monkeypatch, enabled):
    monkeypatch.setenv(ENV, str(int(enabled)))
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    working = WorkingSnapshot()
    timing = decide(3000, 10000)
    invoke = lambda: finish([], [], None, [], working, client, timing, timing, 0, 0, False, False)
    if enabled:
        with pytest.raises(ValueError, match='output_reserve=8192'):
            invoke()
        assert working.wsc_timing_state['last_request_admission']['output_reserve_basis'] == 'provider_documented_default_output_limit'
    else:
        assert invoke().facts['output_reserve_tokens'] is None
