"""Mixed media cannot retire a normal invocation or get bound by adjacency."""
from copy import deepcopy
import json

import pytest

from tests.wsc.test_mixed_late_receipt import source_rows

IMAGE_DATA = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg=="
IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + IMAGE_DATA}}


@pytest.mark.parametrize("binding", ["shared", "nested"])
def test_mixed_media_keeps_normal_calls_and_exact_image_bindings(monkeypatch, binding):
    from session.late_result_projection import ENV, project
    from model.deepseek import DeepSeekModelClient
    from model.anthropic import AnthropicModelClient
    monkeypatch.setenv(ENV, "1")
    rows = source_rows()
    if binding == "shared":
        rows[-1]["content"].append(deepcopy(IMAGE))
    else:
        rows[-1]["content"][1]["content"] = [
            {"type": "text", "text": "normal receipt c=74"}, deepcopy(IMAGE)]
    original = deepcopy(rows)
    prior = project(rows[:4])
    projected = project(rows)
    assert rows == original and projected[:4] == prior
    assert projected[4] == rows[4]
    native = projected[-1]["content"][0]
    assert native["type"] == "tool_result" and native["tool_use_id"] == "c"
    assert "normal receipt c=74" in native["content"]
    facts = [block["text"] for block in projected[-1]["content"] if block.get("type") == "text"]
    media = json.loads(next(text.removeprefix("Recorded source media: ") for text in facts
                            if text.startswith("Recorded source media: ")))
    assert media["source_message_id"] == "mixed-arrival"
    assert media["projected_message_image_index"] == 0
    if binding == "shared":
        assert media["binding"] == "source_message" and media["call_ids"] == ["a", "c"]
        assert "call_id" not in media
    else:
        assert media["binding"] == "result_body" and media["call_id"] == "c"
        assert media["block_index"] == 1
        assert IMAGE["image_url"]["url"] not in native["content"]
    for client in [DeepSeekModelClient(api_key="not-sent", model="deepseek-flash", thinking="disabled"),
                   AnthropicModelClient(api_key="not-sent", model="claude-sonnet")]:
        body = client._build_body(projected, [], stream=False)
        encoded = json.dumps(body, ensure_ascii=False)
        assert encoded.count(IMAGE_DATA) == 1
        assert "late error a=137" in encoded and "normal receipt c=74" in encoded
        if isinstance(client, AnthropicModelClient):
            results = [block for row in body["messages"] for block in row["content"]
                       if block.get("type") == "tool_result"]
            assert all(isinstance(block["content"], str) for block in results)
