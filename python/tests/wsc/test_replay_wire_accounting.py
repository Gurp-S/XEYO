"""离线台不能把存档/UI 字段当作发送内容。"""

import copy
import json
import pytest

from evals.wsc_extension_economics_ab import canonical_projection


@pytest.mark.parametrize("adapter", ["deepseek", "openai_compat"])
def test_text_replay_matches_native_request_builder_without_network(adapter):
    from model.deepseek import DeepSeekModelClient
    from model.openai_compat import OpenAICompatClient

    messages = [{"role": "system", "content": "stable facts"},
                {"role": "user", "content": "任务", "note_key": "world_state", "note_fp": "f"},
                {"role": "assistant", "content": [
                    {"type": "reasoning", "text": "推理"},
                    {"type": "tool_use", "id": "c1", "name": "Read", "input": {"file_path": "a.py"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": ""}]
    client = (DeepSeekModelClient(api_key="offline-placeholder") if adapter == "deepseek" else
              OpenAICompatClient(api_key="offline-placeholder", base_url="http://invalid.local", model="offline"))
    original = copy.deepcopy(messages)
    body = client._build_body(messages, [], stream=True)
    assert json.loads(canonical_projection(messages, "openai")) == body["messages"]
    assert messages == original
    assert "stream_options" in body
    assert "reasoning_content" in body["messages"][2]
    assert body["messages"][3]["content"] == "(no output)"


def test_wire_projection_ignores_archive_metadata_but_keeps_model_payload():
    messages = [{"role": "assistant", "id": "ui-id", "timestamp": 123,
                 "content": [{"type": "reasoning", "text": "reason"},
                             {"type": "tool_use", "id": "c1", "name": "Read",
                              "input": {"file_path": "a.py"}}]},
                {"role": "tool", "tool_call_id": "c1", "tool_duration": 42,
                 "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "result"}]}]
    changed = copy.deepcopy(messages)
    changed[0]["timestamp"] = 456
    changed[1]["tool_duration"] = 99
    assert canonical_projection(messages, "openai") == canonical_projection(changed, "openai")
    wire = json.loads(canonical_projection(messages, "openai"))
    assert wire[0]["reasoning_content"] == "reason"
    assert wire[0]["tool_calls"][0]["function"]["arguments"] == '{"file_path": "a.py"}'
    assert wire[1]["content"] == "result"
    assert canonical_projection(messages, "internal") != canonical_projection(changed, "internal")


def test_text_replay_does_not_materialize_unavailable_media():
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {
        "url": "xeyo-media://" + "a" * 64}}]}]
    before = copy.deepcopy(messages)
    wire = json.loads(canonical_projection(messages, "openai"))
    assert wire[0]["content"][1]["image_url"]["url"].startswith("offline-media://")
    assert messages == before
