"""Final occupancy measures each provider's actual encoded input fields."""
from copy import deepcopy
import base64
import io
import json

import pytest

from memory.token import token_len
from memory.wsc_timing import request_measure


def client_for(provider):
    if provider == "deepseek":
        from model.deepseek import DeepSeekModelClient
        return DeepSeekModelClient(api_key="offline-credential", model="offline", thinking="disabled")
    from model.anthropic import AnthropicModelClient
    return AnthropicModelClient(api_key="offline-credential", model="offline", thinking="off", max_tokens=100)


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
def test_native_input_contains_system_tools_signed_reasoning_and_media_without_mutation(provider, monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(image, format="PNG")
    image_url = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode("ascii")
    client = client_for(provider)
    rows = [
        {"role": "system", "content": "事实：系统上下文"},
        {"role": "user", "content": [{"type": "text", "text": "观察输入"},
            {"type": "image_url", "image_url": {"url": image_url}}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "text": "signed observed reasoning", "signature": "signature-value"},
            {"type": "reasoning", "text": "unsigned observed reasoning"},
            {"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": "observations.txt"}}]},
        {"role": "tool", "tool_call_id": "read", "name": "Read", "content": [
            {"type": "tool_result", "tool_use_id": "read", "content": "验收原文"}]},
    ]
    schemas = [{"name": "Read", "description": "读取事实", "input_schema": {"type": "object"}}]
    original = deepcopy((rows, schemas))
    encoded = client._build_body(rows, schemas, stream=True)
    expected = {k: encoded[k] for k in ("messages", "system", "tools") if k in encoded}
    source = client.context_input(rows, schemas)
    assert source == expected
    text = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    reasoning = "signed observed reasoning" if provider == "anthropic" else "unsigned observed reasoning"
    for value in ("系统上下文", reasoning, "observations.txt", "验收原文", "base64"):
        assert value in text
    assert "offline-credential" not in text
    assert not set(source) & {"model", "stream", "max_tokens", "thinking", "temperature"}
    measured = request_measure(rows, schemas, context_limit=1000000, model=client)
    assert measured.input_tokens == token_len(text)
    assert measured.basis == "provider_normalized_input_utf8_quarters_estimate"
    assert (rows, schemas) == original


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
def test_no_tools_or_system_does_not_count_nonexistent_fields(provider):
    client = client_for(provider)
    rows = [{"role": "user", "content": "task"}]
    body = client._build_body(rows, [], stream=False)
    assert client.context_input(rows, []) == {"messages": body["messages"]}


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
def test_generation_options_do_not_change_input_occupancy(provider):
    client = client_for(provider)
    rows = [{"role": "user", "content": "task"}]
    first = request_measure(rows, [], context_limit=1000000, model=client)
    client._max_tokens = 999999
    client._temperature = 0.7
    client._thinking = "enabled" if provider == "deepseek" else "adaptive"
    second = request_measure(rows, [], context_limit=1000000, model=client)
    assert first == second
