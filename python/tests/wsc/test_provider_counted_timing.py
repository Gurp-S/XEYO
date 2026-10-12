"""Count the actual notice/fold input without making provider requests."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from engine.abort import AbortController
from memory.wsc_counted_input import CountedInput
from memory.wsc_request_timing import prepare_counted


@pytest.mark.asyncio
async def test_notice_crosses_capacity_and_post_fold_input_gets_a_new_count():
    calls, folds = [], []
    class Model:
        def context_input(self, messages, tools):
            return {"messages": messages, "tools": tools}
        def context_output_limit(self, messages, tools): return 10
        async def predict_context_tokens(self, messages, tools, abort):
            calls.append(deepcopy(messages))
            return 10 if messages[0]["content"] == "folded" else 85 if len(messages) > 1 else 80
    working = SimpleNamespace(compact_cursor=0, wsc_timing_state={})
    def compact():
        folds.append(True)
        working.compact_cursor = 1
        return [{"role": "user", "content": "folded"}]
    model = CountedInput(Model(), AbortController())
    result = await prepare_counted([{"role": "user", "content": "before"}], [], working,
        context_limit=100, build=lambda rows: rows,
        render=lambda rows, text: rows + [{"role": "user", "content": text}],
        compact=compact, model=model)
    assert len(calls) == 3 and len(folds) == 1
    assert "厂商预计数" in calls[1][-1]["content"]
    assert result.facts["before"]["emitted_tokens"] == 85
    assert result.facts["after"]["emitted_tokens"] == 10
    assert result.facts["after"]["basis"] == "anthropic_count_tokens_prediction"
    assert result.delivery_key is None


@pytest.mark.asyncio
async def test_official_counter_uses_encoded_input_and_does_not_change_usage(monkeypatch):
    from model.anthropic import AnthropicModelClient
    sent = []
    class Http:
        async def post(self, url, **kwargs):
            sent.append((url, kwargs))
            return SimpleNamespace(status_code=200, json=lambda: {"input_tokens": 111})
    monkeypatch.setattr("model._openai_common.get_shared_httpx_client", lambda timeout: Http())
    model = AnthropicModelClient(api_key="not-sent", model="claude-sonnet", base_url="https://api.anthropic.com")
    model.last_usage = {"prompt_tokens": 99}
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "source"}]
    body = model._build_body(messages, [], stream=False)
    count = await model.predict_context_tokens(messages, [], AbortController())
    assert count == 111 and model.last_usage == {"prompt_tokens": 99}
    assert sent[0][0] == "https://api.anthropic.com/v1/messages/count_tokens"
    payload = sent[0][1]["json"]
    assert payload == {key: body[key] for key in ("model", "messages", "system", "tools", "thinking", "tool_choice") if key in body}
    assert sent[0][1]["follow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://gateway.example", "http://api.anthropic.com", "https://api.anthropic.com/v1"])
async def test_counter_does_not_send_to_non_native_origins(monkeypatch, origin):
    from model.anthropic import AnthropicModelClient
    def unexpected(*args): raise AssertionError("No HTTP client was expected")
    monkeypatch.setattr("model._openai_common.get_shared_httpx_client", unexpected)
    model = AnthropicModelClient(api_key="not-sent", model="claude-sonnet", base_url=origin)
    assert await model.predict_context_tokens([], [], AbortController()) is None
