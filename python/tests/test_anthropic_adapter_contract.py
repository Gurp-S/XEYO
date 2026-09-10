"""Anthropic 原生适配器契约测试（纯离线，不发网络请求）。

覆盖三块：
  1) 形状护栏 —— 客户端必须保留的方法（防「重构删到只剩 stub」的 P1 类事故）。
  2) 请求体构造 —— 内部消息 → Messages API 的六条协议差异（system 提顶层、
     tool_use/tool_result block、tool_result 必与 tool_use 同序列、严格交替、
     thinking 块带签名回传、adaptive thinking）。
  3) SSE 解析 —— thinking/text/tool_use 增量、signature 落定、usage 合并、
     异常事件。
"""

from __future__ import annotations

import json

import pytest

from model.anthropic import (
    AnthropicModelClient,
    _consume_sse_event,
    _usage_to_openai_shape,
    normalize_messages_for_anthropic,
    to_anthropic_tool,
)
from model.chunks import ModelChunk


def _tool_use_block(tid: str, name: str, inp: dict) -> dict:
	return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _tool_result_block(tid: str, content: str, *, is_error: bool = False) -> dict:
	return {
		"type": "tool_result",
		"tool_use_id": tid,
		"content": content,
		"is_error": is_error,
	}


# ------------------------------------------------------------ 1) 形状护栏


def test_client_exposes_required_api() -> None:
	"""缺一即算结构性回归（镜像 test_model_client_contract 的做法）。"""
	for name in (
		"__init__",
		"_headers",
		"_build_body",
		"stream",
		"_stream_httpx",
		"_stream_stdlib",
		"set_session_id",
	):
		assert callable(getattr(AnthropicModelClient, name, None)), (
			f"AnthropicModelClient 缺少方法 {name}，疑似被缩进成死代码或被删除"
		)


def test_client_rejects_missing_key() -> None:
	with pytest.raises(RuntimeError):
		AnthropicModelClient(api_key="")
	with pytest.raises(RuntimeError):
		AnthropicModelClient(api_key="   ")


def test_headers_use_x_api_key_not_bearer() -> None:
	"""Anthropic 用 x-api-key + anthropic-version，不是 Bearer。"""
	h = AnthropicModelClient(api_key="sk-ant-x")._headers()
	assert h["x-api-key"] == "sk-ant-x"
	assert "Authorization" not in h
	assert h["anthropic-version"]


# ------------------------------------------------- 2) 请求体构造（协议差异）


def test_system_is_hoisted_to_top_level() -> None:
	body = AnthropicModelClient(api_key="k")._build_body(
		[
			{"role": "system", "content": "你是 XEYO"},
			{"role": "user", "content": "hi"},
		],
		[],
		stream=False,
	)
	assert body["system"] == "你是 XEYO"
	assert all(m["role"] != "system" for m in body["messages"])


def test_multiple_system_messages_are_joined() -> None:
	sys_text, msgs = normalize_messages_for_anthropic(
		[
			{"role": "system", "content": "A"},
			{"role": "system", "content": "B"},
			{"role": "user", "content": "hi"},
		]
	)
	assert sys_text == "A\n\nB"
	assert len(msgs) == 1


def test_tool_result_becomes_user_block_not_tool_role() -> None:
	"""OpenAI 的独立 role=tool 行必须并成 user 消息里的 tool_result block。"""
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [_tool_use_block("tu_1", "Read", {"path": "a.txt"})],
			},
			{"role": "tool", "tool_call_id": "tu_1", "content": "file body"},
		]
	)
	assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
	last = msgs[-1]
	assert last["content"][0]["type"] == "tool_result"
	assert last["content"][0]["tool_use_id"] == "tu_1"
	assert last["content"][0]["content"] == "file body"


def test_consecutive_tool_results_coalesce_into_one_user_message() -> None:
	"""多工具并行：每个工具一条内部 tool 行 → 合成一条 user 的多个 block。

	若不合并，会出现连续两条 user 消息，被厂商以 400 拒绝。
	"""
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [
					_tool_use_block("tu_1", "Read", {"path": "a"}),
					_tool_use_block("tu_2", "Read", {"path": "b"}),
				],
			},
			{"role": "tool", "tool_call_id": "tu_1", "content": "A"},
			{"role": "tool", "tool_call_id": "tu_2", "content": "B"},
		]
	)
	assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
	assert len(msgs[-1]["content"]) == 2
	assert all(b["type"] == "tool_result" for b in msgs[-1]["content"])


def test_alternation_is_strict_no_adjacent_same_role() -> None:
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "a"},
			{"role": "user", "content": "b"},
			{"role": "assistant", "content": "c"},
			{"role": "assistant", "content": "d"},
		]
	)
	roles = [m["role"] for m in msgs]
	assert roles == ["user", "assistant"]
	assert len(msgs[0]["content"]) == 2  # 两条 user 文本合并
	assert len(msgs[1]["content"]) == 2


def test_thinking_block_replayed_with_signature() -> None:
	"""思考态回放的核心：text + signature 逐块原样带回。"""
	sig = "sig-abc-123=="
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [
					{"type": "thinking", "text": "让我想想", "signature": sig},
					_tool_use_block("tu_1", "Read", {"path": "a"}),
				],
			},
		]
	)
	asst = msgs[-1]
	assert asst["role"] == "assistant"
	assert asst["content"][0] == {
		"type": "thinking",
		"thinking": "让我想想",
		"signature": sig,
	}
	# 顺序保持：thinking 在前，tool_use 在后
	assert asst["content"][1]["type"] == "tool_use"


def test_thinking_block_without_signature_is_dropped() -> None:
	"""无签名 thinking 不能发给厂商（会被拒），也不伪造签名。"""
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [
					{"type": "thinking", "text": "想了"},
					_tool_use_block("tu_1", "Read", {"path": "a"}),
				],
			},
		]
	)
	assert all(b["type"] != "thinking" for b in msgs[-1]["content"])
	assert msgs[-1]["content"][0]["type"] == "tool_use"


def test_openai_reasoning_block_is_dropped_not_faked() -> None:
	"""跨厂商转码：DeepSeek 明文 reasoning 无签名，Anthropic 承载不了 → 丢弃。"""
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [
					{"type": "reasoning", "text": "DeepSeek 的思考明文"},
					_tool_use_block("tu_1", "Read", {"path": "a"}),
				],
			},
		]
	)
	types = [b["type"] for b in msgs[-1]["content"]]
	assert "reasoning" not in types
	assert "thinking" not in types
	assert types == ["tool_use"]


def test_redacted_thinking_passthrough() -> None:
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [
					{"type": "redacted_thinking", "data": "opaque-bytes"},
					_tool_use_block("tu_1", "Read", {"path": "a"}),
				],
			},
		]
	)
	assert msgs[-1]["content"][0] == {
		"type": "redacted_thinking",
		"data": "opaque-bytes",
	}


def test_tool_result_with_images_becomes_block_array() -> None:
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [_tool_use_block("tu_1", "Screenshot", {})],
			},
			{
				"role": "tool",
				"tool_call_id": "tu_1",
				"content": [
					{"type": "tool_result", "tool_use_id": "tu_1", "content": "done"},
					{
						"type": "image_url",
						"image_url": {"url": "data:image/png;base64,QUJD"},
					},
				],
			},
		]
	)
	block = msgs[-1]["content"][0]
	assert block["type"] == "tool_result"
	assert isinstance(block["content"], list)
	assert block["content"][0]["type"] == "text"
	assert block["content"][1]["type"] == "image"
	assert block["content"][1]["source"]["media_type"] == "image/png"
	assert block["content"][1]["source"]["data"] == "QUJD"


def test_tool_result_is_error_flag_passthrough() -> None:
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{
				"role": "assistant",
				"content": [_tool_use_block("tu_1", "Bash", {})],
			},
			{
				"role": "tool",
				"tool_call_id": "tu_1",
				"content": [_tool_result_block("tu_1", "boom", is_error=True)],
			},
		]
	)
	assert msgs[-1]["content"][0]["is_error"] is True


def test_thinking_adaptive_not_enabled_on_47_plus() -> None:
	"""Claude 4.7+ 对 thinking:{type:"enabled"} 返回 400，必须发 adaptive。"""
	body = AnthropicModelClient(api_key="k", thinking="enabled")._build_body(
		[{"role": "user", "content": "hi"}], [], stream=False
	)
	assert body["thinking"] == {"type": "adaptive"}
	assert body["thinking"] != {"type": "enabled"}


def test_thinking_off_omits_field() -> None:
	body = AnthropicModelClient(api_key="k", thinking="disabled")._build_body(
		[{"role": "user", "content": "hi"}], [], stream=False
	)
	assert "thinking" not in body
	assert "output_config" not in body


def test_effort_only_sent_with_adaptive() -> None:
	client = AnthropicModelClient(api_key="k", thinking="adaptive", reasoning_effort="high")
	body = client._build_body([{"role": "user", "content": "hi"}], [], stream=False)
	assert body["output_config"] == {"effort": "high"}

	off = AnthropicModelClient(api_key="k", thinking="off", reasoning_effort="high")
	body_off = off._build_body([{"role": "user", "content": "hi"}], [], stream=False)
	assert "output_config" not in body_off


def test_max_tokens_always_present() -> None:
	"""Messages API 的 max_tokens 必填；不给就发默认值。"""
	body = AnthropicModelClient(api_key="k")._build_body(
		[{"role": "user", "content": "hi"}], [], stream=False
	)
	assert isinstance(body["max_tokens"], int)
	assert body["max_tokens"] > 0

	custom = AnthropicModelClient(api_key="k", max_tokens=2048)._build_body(
		[{"role": "user", "content": "hi"}], [], stream=False
	)
	assert custom["max_tokens"] == 2048


def test_temperature_dropped_when_thinking_on() -> None:
	"""扩展思考开启时 temperature 只能是 1，故不回传用户值。"""
	client = AnthropicModelClient(api_key="k", thinking="adaptive", temperature=0.2)
	body = client._build_body([{"role": "user", "content": "hi"}], [], stream=False)
	assert "temperature" not in body

	off = AnthropicModelClient(api_key="k", thinking="off", temperature=0.2)
	body_off = off._build_body([{"role": "user", "content": "hi"}], [], stream=False)
	assert body_off["temperature"] == 0.2


def test_tools_use_native_input_schema() -> None:
	"""内部 schema 已是 {name, description, input_schema}，与 Anthropic 同构。"""
	tool = to_anthropic_tool(
		{
			"name": "Read",
			"description": "读文件",
			"input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
		}
	)
	assert tool["name"] == "Read"
	assert tool["input_schema"]["properties"]["path"]["type"] == "string"

	body = AnthropicModelClient(api_key="k")._build_body(
		[{"role": "user", "content": "hi"}],
		[
			{
				"name": "Read",
				"description": "读文件",
				"input_schema": {"type": "object", "properties": {}},
			}
		],
		stream=False,
	)
	assert body["tools"][0]["name"] == "Read"
	# 不能出现 OpenAI 的 function 包装
	assert "function" not in body["tools"][0]


def test_to_anthropic_tool_falls_back_to_parameters_key() -> None:
	tool = to_anthropic_tool(
		{"name": "X", "parameters": {"type": "object", "properties": {"a": {"type": "string"}}}}
	)
	assert tool["input_schema"]["properties"]["a"]["type"] == "string"


def test_empty_assistant_text_is_not_emitted() -> None:
	"""纯工具轮的 assistant content 里没有 text block，不能塞空 text（厂商拒空块）。"""
	_, msgs = normalize_messages_for_anthropic(
		[
			{"role": "user", "content": "hi"},
			{"role": "assistant", "content": [_tool_use_block("tu_1", "Read", {})]},
		]
	)
	types = [b["type"] for b in msgs[-1]["content"]]
	assert types == ["tool_use"]


# ------------------------------------------------------- 3) SSE 解析契约


def _sse(payload: dict) -> str:
	return json.dumps(payload, ensure_ascii=False)


def test_message_start_returns_usage() -> None:
	state: dict = {}
	u, chunks = _consume_sse_event(
		"message_start",
		_sse(
			{
				"type": "message_start",
				"message": {"usage": {"input_tokens": 100, "output_tokens": 1}},
			}
		),
		state,
	)
	assert u == {"input_tokens": 100, "output_tokens": 1}
	assert chunks == []


def test_text_delta_streams_text_chunk() -> None:
	state: dict = {}
	_, chunks = _consume_sse_event(
		"content_block_delta",
		_sse(
			{
				"type": "content_block_delta",
				"index": 0,
				"delta": {"type": "text_delta", "text": "Hi"},
			}
		),
		state,
	)
	assert len(chunks) == 1
	assert chunks[0].kind == "text_delta"
	assert chunks[0].text == "Hi"


def test_thinking_delta_yields_reasoning_chunk() -> None:
	state: dict = {}
	_, chunks = _consume_sse_event(
		"content_block_delta",
		_sse(
			{
				"type": "content_block_delta",
				"index": 0,
				"delta": {"type": "thinking_delta", "thinking": "让我想"},
			}
		),
		state,
	)
	assert chunks[0].kind == "reasoning_delta"
	assert chunks[0].text == "让我想"


def test_signature_delta_accumulates_without_emitting_chunk() -> None:
	state: dict = {}
	u, chunks = _consume_sse_event(
		"content_block_delta",
		_sse(
			{
				"type": "content_block_delta",
				"index": 0,
				"delta": {"type": "signature_delta", "signature": "sig-part"},
			}
		),
		state,
	)
	assert chunks == []
	assert state["thinking_bufs"][0]["signature"] == "sig-part"


def test_tool_use_aggregates_json_deltas_then_emits_on_stop() -> None:
	state: dict = {}
	_, c1 = _consume_sse_event(
		"content_block_start",
		_sse(
			{
				"type": "content_block_start",
				"index": 1,
				"content_block": {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {}},
			}
		),
		state,
	)
	assert c1 == []
	_, c2 = _consume_sse_event(
		"content_block_delta",
		_sse(
			{
				"type": "content_block_delta",
				"index": 1,
				"delta": {"type": "input_json_delta", "partial_json": '{"pa'},
			}
		),
		state,
	)
	assert c2 == []  # 残缺 JSON 不发
	_, c3 = _consume_sse_event(
		"content_block_delta",
		_sse(
			{
				"type": "content_block_delta",
				"index": 1,
				"delta": {"type": "input_json_delta", "partial_json": 'th":"a.txt"}'},
			}
		),
		state,
	)
	assert c3 == []  # 仍在同一 block 内累积，闭合在 stop 时落定
	_, c4 = _consume_sse_event(
		"content_block_stop", _sse({"type": "content_block_stop", "index": 1}), state
	)
	assert len(c4) == 1
	assert c4[0].kind == "tool_use"
	assert c4[0].tool_use is not None
	assert c4[0].tool_use.id == "tu_1"
	assert c4[0].tool_use.name == "Read"
	assert c4[0].tool_use.input == {"path": "a.txt"}


def test_empty_tool_input_emits_empty_dict() -> None:
	state: dict = {}
	_consume_sse_event(
		"content_block_start",
		_sse(
			{
				"type": "content_block_start",
				"index": 0,
				"content_block": {"type": "tool_use", "id": "tu_9", "name": "getTime", "input": {}},
			}
		),
		state,
	)
	_, chunks = _consume_sse_event(
		"content_block_stop", _sse({"type": "content_block_stop", "index": 0}), state
	)
	assert chunks[0].tool_use is not None
	assert chunks[0].tool_use.input == {}


def test_message_delta_merges_input_usage() -> None:
	"""message_delta 只带 output_tokens，须与 message_start 的输入侧合并。"""
	state: dict = {}
	_consume_sse_event(
		"message_start",
		_sse(
			{
				"type": "message_start",
				"message": {"usage": {"input_tokens": 100, "output_tokens": 1}},
			}
		),
		state,
	)
	u, _ = _consume_sse_event(
		"message_delta",
		_sse({"type": "message_delta", "usage": {"output_tokens": 42}}),
		state,
	)
	assert u == {"input_tokens": 100, "output_tokens": 42}


def test_error_event_raises_provider_error() -> None:
	from common.errors import ProviderError

	with pytest.raises(ProviderError):
		_consume_sse_event(
			"error",
			_sse({"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}),
			{},
		)


def test_malformed_json_tolerated() -> None:
	u, chunks = _consume_sse_event("content_block_delta", "{not-json", {})
	assert u is None
	assert chunks == []


def test_unknown_event_type_is_ignored() -> None:
	u, chunks = _consume_sse_event("ping", _sse({"type": "ping"}), {})
	assert u is None
	assert chunks == []


# --------------------------------------------------------- 4) usage 形状转换


def test_usage_conversion_sums_cache_into_prompt() -> None:
	"""Anthropic 的 input_tokens 不含缓存部分，须求和否则面板输入偏低。"""
	converted = _usage_to_openai_shape(
		{
			"input_tokens": 10,
			"output_tokens": 5,
			"cache_read_input_tokens": 100,
			"cache_creation_input_tokens": 20,
		}
	)
	assert converted["prompt_tokens"] == 130
	assert converted["completion_tokens"] == 5
	assert converted["prompt_tokens_details"] == {"cached_tokens": 100}
	assert converted["cache_creation_tokens"] == 20


def test_usage_conversion_without_cache() -> None:
	converted = _usage_to_openai_shape({"input_tokens": 7, "output_tokens": 3})
	assert converted["prompt_tokens"] == 7
	assert "prompt_tokens_details" not in converted


# ------------------------------------------------- 5) 端到端往返（SSE 全链路）


def _feed_sse_script(
    lines: list[tuple[str, dict]], state: dict
) -> list[ModelChunk]:
    """把 (event_name, payload) 脚本喂给解析器，收集全部 chunk。"""
    out: list[ModelChunk] = []
    for name, payload in lines:
        _, chunks = _consume_sse_event(name, _sse(payload), state)
        out.extend(chunks)
    return out


def test_full_thinking_then_tool_turn_roundtrip() -> None:
    """一轮完整流：thinking(带签名) → tool_use，且签名可被回收用于回放。"""
    state: dict = {}
    chunks = _feed_sse_script(
        [
            ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 50, "output_tokens": 1}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "先读文件"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "SIG=="}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {}}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":"a.txt"}'}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 1}),
            ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 30}}),
        ],
        state,
    )
    kinds = [c.kind for c in chunks]
    assert "reasoning_delta" in kinds
    tool_chunks = [c for c in chunks if c.kind == "tool_use"]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].tool_use is not None
    assert tool_chunks[0].tool_use.name == "Read"
    assert tool_chunks[0].tool_use.input == {"path": "a.txt"}
    # 签名在 state 里落定（回放时由 query_loop 写进 thinking block）
    assert state["thinking_bufs"][0]["signature"] == "SIG=="
    assert state["thinking_bufs"][0]["text"] == "先读文件"


def test_replayed_thinking_survives_body_rebuild() -> None:
    """回放闭环：捕获的 thinking+签名 → 内部消息 → 请求体仍是原块。"""
    state: dict = {}
    _feed_sse_script(
        [
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "推理正文"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "SIG-XYZ"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ],
        state,
    )
    buf = state["thinking_bufs"][0]
    # 模拟 query_loop 落档后重建请求
    body = AnthropicModelClient(api_key="k")._build_body(
        [
            {"role": "user", "content": "读一下"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "text": buf["text"], "signature": buf["signature"]},
                    _tool_use_block("tu_1", "Read", {"path": "a"}),
                ],
            },
            {"role": "tool", "tool_call_id": "tu_1", "content": "内容"},
        ],
        [],
        stream=False,
    )
    asst = body["messages"][1]
    assert asst["content"][0] == {
        "type": "thinking",
        "thinking": "推理正文",
        "signature": "SIG-XYZ",
    }
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
