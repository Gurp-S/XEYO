"""模型客户端契约回归测试。

背景（《起步阶段评测结果》P1 级缺陷）：
  python/model/deepseek.py 的死代码事件 —— DeepSeekModelClient 的五个类方法曾
  被整体缩进进模块级函数 _extract_sse_usage 的函数体，导致流式路径整体不可用；
  而既有测试（test_vendor_models.py 等）从不调用 .stream()，故 pytest 全绿，
  生产主路径（engine/query_engine.py:822）直到首轮评测才 AttributeError。

本测试补上两道防护：
  1) 形状护栏：断言两个客户端类必须暴露哪些方法（防止类被「重构」删到只剩 stub）。
  2) SSE 解析契约：用真实 JSON 逐行喂给 _consume_sse_line_with_usage /
     _finish_tool_bufs，锁定文本增量、跨行 tool_call 聚合、usage 提取、
     [DONE]/非 data 行/畸形 JSON 的容错语义。

不发起网络请求，纯离线。
"""

from __future__ import annotations

import json

from model.chunks import ModelChunk
from model.deepseek import (
    DeepSeekModelClient,
    _consume_sse_line_with_usage,
    _finish_tool_bufs,
)
from model.openai_compat import OpenAICompatClient


def _sse(payload: dict) -> str:
	"""构造一行 `data: <json>`。"""
	return "data: " + json.dumps(payload, ensure_ascii=False)


def _only(chunks: list[ModelChunk]) -> ModelChunk:
	assert len(chunks) == 1, f"expected exactly 1 chunk, got {chunks}"
	return chunks[0]


# ---------------------------------------------------------------- 1) 形状护栏


def test_deepseek_client_exposes_required_api() -> None:
	"""DeepSeekModelClient 必须保留这些方法；缺一即算结构性回归。"""
	for name in (
		"__init__",
		"_headers",
		"_build_body",
		"stream",
		"_stream_httpx",
		"_stream_stdlib",
		"_complete_non_stream",
	):
		assert callable(getattr(DeepSeekModelClient, name, None)), (
			f"DeepSeekModelClient 缺少方法 {name}，疑似被缩进成死代码或被删除"
		)


def test_openai_client_exposes_required_api() -> None:
	"""OpenAICompatClient 必须保留这些方法。"""
	for name in ("__init__", "_headers", "_build_body", "stream"):
		assert callable(getattr(OpenAICompatClient, name, None)), (
			f"OpenAICompatClient 缺少方法 {name}"
		)


def test_deepseek_client_not_shadowed_by_function_body() -> None:
	"""直接防住本次 P1：确认 _extract_sse_usage 是独立函数而非吞掉类方法的容器。"""
	from model import deepseek

	# 类方法不能「长」在别的函数里：方法必须可被类自身属性访问，且 _extract_sse_usage
	# 作为函数存在（用来承载类的死代码反而说明类被掏空）。
	assert callable(deepseek._extract_sse_usage)
	assert hasattr(DeepSeekModelClient, "stream")


# ---------------------------------------------------------------- 2) SSE 解析契约


def test_text_delta_yields_text_chunk() -> None:
	u, chunks = _consume_sse_line_with_usage(
		_sse({"choices": [{"delta": {"content": "Hi"}}]}), {}
	)
	assert u is None
	assert _only(chunks).kind == "text_delta"
	assert _only(chunks).text == "Hi"


def test_reasoning_delta_yields_reasoning_chunk() -> None:
	u, chunks = _consume_sse_line_with_usage(
		_sse({"choices": [{"delta": {"reasoning_content": "Let me think"}}]}), {}
	)
	assert u is None
	assert _only(chunks).kind == "reasoning_delta"
	assert _only(chunks).text == "Let me think"


def test_tool_call_aggregates_across_lines() -> None:
	bufs: dict[int, dict] = {}
	u, chunks1 = _consume_sse_line_with_usage(
		_sse(
			{
				"choices": [
					{
						"delta": {
							"tool_calls": [
								{
									"index": 0,
									"id": "call_1",
									"type": "function",
									"function": {
										"name": "get_weather",
										"arguments": '{"location": "',
									},
								}
							]
						}
					}
				]
			}
		),
		bufs,
	)
	assert u is None
	assert chunks1 == []  # 残缺 JSON：不发
	# 第二行补全 arguments 尾部 → 立刻 emit tool_use
	_, chunks2 = _consume_sse_line_with_usage(
		_sse(
			{
				"choices": [
					{
						"delta": {
							"tool_calls": [
								{"index": 0, "function": {"arguments": '北京","unit":"celsius"}'}}
							]
						}
					}
				]
			}
		),
		bufs,
	)
	chunk = _only(chunks2)
	assert chunk.kind == "tool_use"
	tu = chunk.tool_use
	assert tu is not None
	assert tu.id == "call_1"
	assert tu.name == "get_weather"
	assert tu.input == {"location": "北京", "unit": "celsius"}
	# 流尾不应再发同一条
	assert _finish_tool_bufs(bufs) == []


def test_finish_emits_empty_args_once() -> None:
	"""空 arguments 在流中不发，finish 用 {} 收尾且只发一次。"""
	from model._openai_common import try_finalize_tool_buf

	bufs = {
		0: {
			"id": "call_empty",
			"name": "getTime",
			"arguments": "",
			"_emitted": False,
		}
	}
	assert try_finalize_tool_buf(bufs[0]) is None
	finished = _finish_tool_bufs(bufs)
	chunk = _only(finished)
	assert chunk.tool_use is not None
	assert chunk.tool_use.input == {}
	assert _finish_tool_bufs(bufs) == []


def test_try_finalize_ignores_post_close_whitespace() -> None:
	from model._openai_common import try_finalize_tool_buf

	buf = {
		"id": "c1",
		"name": "echo",
		"arguments": '{"text":"a"}',
		"_emitted": False,
	}
	tu = try_finalize_tool_buf(buf)
	assert tu is not None
	assert tu.input == {"text": "a"}
	buf["arguments"] += "   "
	assert try_finalize_tool_buf(buf) is None


def test_usage_is_extracted_alongside_choices() -> None:
	payload = {
		"choices": [{"delta": {}}],
		"usage": {"prompt_tokens": 5, "completion_tokens": 3},
	}
	u, chunks = _consume_sse_line_with_usage(_sse(payload), {})
	assert u == {"prompt_tokens": 5, "completion_tokens": 3}
	assert chunks == []


def test_done_line_is_ignored() -> None:
	u, chunks = _consume_sse_line_with_usage("data: [DONE]", {})
	assert u is None
	assert chunks == []


def test_non_data_line_is_ignored() -> None:
	u, chunks = _consume_sse_line_with_usage("event: ping", {})
	assert u is None
	assert chunks == []


def test_malformed_json_is_tolerated() -> None:
	u, chunks = _consume_sse_line_with_usage("data: {not-json", {})
	assert u is None
	assert chunks == []


def test_missing_tool_name_skips_finish() -> None:
	# 只有 id/arguments、没有 name 的 buffer 不应生成 tool_use。
	bufs = {0: {"id": "call_x", "name": "", "arguments": '{"a":1}'}}
	assert _finish_tool_bufs(bufs) == []


# ---------------------------------------------------------------- 3) 请求构造契约


def test_build_body_matches_production_shaping() -> None:
	"""心跳：请求体必须由产品客户端 _build_body 构造（_normalize_messages_for_openai +
	_to_openai_tool + thinking/temperature）。evals/client.py 已改为复用该路径。"""
	client = DeepSeekModelClient(api_key="k", model="deepseek-v4-flash-vision-exp", thinking="disabled")
	body = client._build_body(
		[
			{"role": "system", "content": "sys"},
			{"role": "user", "content": "hi"},
		],
		[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"loc": {"type": "string"}}}}}],
		stream=False,
	)
	assert body["model"] == "deepseek-v4-flash-vision-exp"
	assert body["stream"] is False
	assert body["messages"][0]["role"] == "system"  # 规范化后的消息
	assert body["tools"][0]["function"]["name"] == "get_weather"
	assert body["tool_choice"] == "auto"
	assert body["thinking"] == {"type": "disabled"}
	assert "max_tokens" not in body  # max_tokens 由调用方追加，不属于请求构造契约


def test_build_body_stream_adds_usage_option() -> None:
	client = DeepSeekModelClient(api_key="k", model="m")
	body = client._build_body([{"role": "user", "content": "hi"}], [], stream=True)
	assert body["stream_options"] == {"include_usage": True}

	assert "stream_options" not in client._build_body(
		[{"role": "user", "content": "hi"}], [], stream=False
	)


def test_openai_compat_max_tokens_optional() -> None:
	"""max_tokens 可选：设置则出现在 body；None 则不发送（保持默认行为）。"""
	with_pk = OpenAICompatClient(api_key="k", base_url="https://api.test/v1", model="m", max_tokens=4096)
	body = with_pk._build_body([{"role": "user", "content": "hi"}], [], stream=False)
	assert body["max_tokens"] == 4096

	without = OpenAICompatClient(api_key="k", base_url="https://api.test/v1", model="m")
	body = without._build_body([{"role": "user", "content": "hi"}], [], stream=False)
	assert "max_tokens" not in body
