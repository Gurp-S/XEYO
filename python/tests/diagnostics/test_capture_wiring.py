"""三个模型适配器 → diagnostics 捕获接线的回归测试（纯离线，假 HTTP 层）。

验收口径来自 ``docs/xeyo-diagnostics-design-2026-09-24.md`` §11 阶段二：

- 请求正文 / hash 对得上、credential 不落盘、脱敏不标完整；
- 捕获文件写失败时任务不被观察器拖死，报告正确标缺项；
- **记录开/关不能改变模型可见消息或工具执行结果**。

每条用例跑真实适配器发送路径（httpx 分支与 urllib 分支各一套替身），断言的是
「交给 HTTP 客户端的那份请求体」，不是替身自己造的东西。
"""

from __future__ import annotations

import asyncio
import dataclasses
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import pytest

from common.errors import ProviderError
from diagnostics import capture as cap
from diagnostics import store
from diagnostics.identity import COMPLETE, PARTIAL, REDACTED
from engine.abort import AbortController
from engine.execution_context import ExecutionContext
from engine.workspace_context import bind_workspace_context
from model import anthropic as anthropic_module
from model import deepseek as deepseek_module
from model import openai_compat as openai_module
from model._capture_hook import capture_body, capture_response
from model.anthropic import AnthropicModelClient
from model.chunks import ModelChunk
from model.deepseek import DeepSeekModelClient
from model.openai_compat import OpenAICompatClient

SESSION = "sess_capture_wiring"
# 同时充当客户端 api_key 的字面量：它只该出现在认证头里，绝不允许进产物。
SECRET = "sk-WiringSecret-0123456789abcdef"
REQUEST_ID = "mrq_wiring_1"
ATTEMPT = 3


# -------------------------------------------------------------- 诊断目录隔离


@pytest.fixture(autouse=True)
def _capture_env(tmp_path, monkeypatch):
	"""四个数据根一律钉进 tmp：用例永不碰真实 ``~/.xeyo``。"""
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(tmp_path / "diagnostics"))
	monkeypatch.setenv("XEYO_DATA_DIR", str(tmp_path / "data"))
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / "usage"))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.delenv("XEYO_DIAGNOSTICS_CAPTURE_SESSIONS", raising=False)
	monkeypatch.setenv("XEYO_DIAGNOSTICS_MAX_BYTES", str(64 * 1024 * 1024))
	store.reset_store_caches()
	yield
	# 换 env 之后进程内缓存一律作废，下一个用例从干净开关开始。
	store.reset_store_caches()


def _enable() -> None:
	cap.set_capture_enabled(SESSION, True)
	assert cap.capture_enabled(SESSION) is True


# ------------------------------------------------------------ 捕获产物读取


def _canon(payload: Any) -> str:
	return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rows() -> list[dict[str, Any]]:
	return store.read_jsonl(cap.index_path())


def _request_rows() -> list[dict[str, Any]]:
	return [r for r in _rows() if r.get("body_hash") and r.get("type") != "response"]


def _response_rows() -> list[dict[str, Any]]:
	return [r for r in _rows() if r.get("type") == "response"]


def _diag_files() -> list[Path]:
	root = store.diagnostics_root()
	if not root.is_dir():
		return []
	return sorted(p for p in root.rglob("*") if p.is_file())


def _blob_raw(body_hash: str) -> str:
	target = store.captures_dir() / body_hash[:2] / f"{body_hash}.json.gz"
	assert target.is_file(), f"no capture blob for {body_hash}"
	with gzip.open(target, "rb") as handle:
		return handle.read().decode("utf-8", "replace")


def _rehash(payload: Any) -> str:
	"""独立重算规范化 hash：不复用捕获层自己的函数，否则是自证循环。"""
	serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(serialized.encode("utf-8", "replace")).hexdigest()


# ----------------------------------------------------------------- 假 HTTP 层


class _Headers(dict):
	"""大小写不敏感响应头（httpx.Headers 与 urllib Message 都是这语义）。"""

	def get(self, key, default=None):  # type: ignore[override]
		wanted = str(key).lower()
		for name, value in self.items():
			if str(name).lower() == wanted:
				return value
		return default


class _StreamResponse:
	"""httpx 流式响应替身：只实现适配器真正用到的成员。"""

	def __init__(self, lines: list[str], *, status: int, headers: dict[str, str]):
		self.status_code = status
		self.headers = _Headers(headers)
		self._lines = list(lines)

	async def aiter_lines(self):
		for line in self._lines:
			yield line

	async def aread(self) -> bytes:
		return b'{"error":{"message":"provider boom"}}'


class _StreamContext:
	def __init__(self, resp: _StreamResponse):
		self._resp = resp

	async def __aenter__(self) -> _StreamResponse:
		return self._resp

	async def __aexit__(self, *_exc: Any) -> bool:
		return False


class FakeHTTPXClient:
	"""``client.stream("POST", url, headers=..., json=body, timeout=...)`` 替身。"""

	def __init__(self, lines: list[str], *, status: int = 200, headers: dict[str, str] | None = None):
		self.canon: list[str] = []
		self.bodies: list[Any] = []
		self._resp = _StreamResponse(lines, status=status, headers=headers or {})

	def stream(self, method: str, url: str, **kwargs: Any) -> _StreamContext:
		body = kwargs.get("json")
		self.bodies.append(body)
		self.canon.append(_canon(body))
		return _StreamContext(self._resp)


class _URLResponse:
	"""urllib 响应替身：``readline()`` 喂 SSE，``read()`` 喂非流式 JSON。"""

	def __init__(
		self,
		lines: list[str],
		*,
		status: int = 200,
		headers: dict[str, str] | None = None,
		json_body: str = "{}",
	):
		self.status = status
		self.headers = _Headers(headers or {})
		self._lines = [str(line).encode("utf-8") + b"\n" for line in lines]
		self._body = json_body.encode("utf-8")

	def readline(self) -> bytes:
		return self._lines.pop(0) if self._lines else b""

	def read(self) -> bytes:
		return self._body

	def __enter__(self) -> "_URLResponse":
		return self

	def __exit__(self, *_exc: Any) -> bool:
		return False


class FakeUrlopen:
	"""替身记录 ``req.data``：那才是要真正写进请求体的字节。"""

	def __init__(self, resp: _URLResponse):
		self.canon: list[str] = []
		self.wire: list[bytes] = []
		self._resp = resp

	def __call__(self, req: Any, timeout: Any = None) -> _URLResponse:
		data = bytes(req.data or b"")
		self.wire.append(data)
		self.canon.append(_canon(json.loads(data.decode("utf-8"))))
		return self._resp


# ---------------------------------------------------------------- 发送夹具


def _sse(event: dict[str, Any]) -> str:
	return "data: " + json.dumps(event, ensure_ascii=False)


_ARGS_JSON = json.dumps({"path": "a.txt"})

_OPENAI_SSE = [
	_sse({"choices": [{"delta": {"content": "hel"}}]}),
	_sse({"choices": [{"delta": {"content": "lo"}}]}),
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
								"function": {"name": "Read", "arguments": _ARGS_JSON},
							}
						]
					}
				}
			]
		}
	),
	"data: [DONE]",
]

_ANTHROPIC_SSE = [
	"event: message_start",
	_sse({"type": "message_start", "message": {"id": "msg_1"}}),
	"event: content_block_start",
	_sse(
		{
			"type": "content_block_start",
			"index": 0,
			"content_block": {"type": "tool_use", "id": "toolu_1", "name": "Read"},
		}
	),
	"event: content_block_delta",
	_sse(
		{
			"type": "content_block_delta",
			"index": 0,
			"delta": {"type": "text_delta", "text": "hello"},
		}
	),
	"event: content_block_delta",
	_sse(
		{
			"type": "content_block_delta",
			"index": 0,
			"delta": {"type": "input_json_delta", "partial_json": _ARGS_JSON},
		}
	),
	"event: content_block_stop",
	_sse({"type": "content_block_stop", "index": 0}),
	"event: message_stop",
	_sse({"type": "message_stop"}),
]

_NON_STREAM_BODY = json.dumps(
	{
		"choices": [
			{
				"message": {
					"content": "hello",
					"tool_calls": [
						{
							"id": "call_9",
							"type": "function",
							"function": {"name": "Read", "arguments": _ARGS_JSON},
						}
					],
				}
			}
		]
	}
)


def _messages() -> list[dict[str, Any]]:
	return [
		{"role": "system", "content": "engine system prompt"},
		{"role": "user", "content": "read a.txt"},
	]


def _tools() -> list[dict[str, Any]]:
	return [
		{
			"name": "Read",
			"description": "read a file",
			"input_schema": {
				"type": "object",
				"properties": {"path": {"type": "string"}},
			},
		}
	]


def _stamp_meta(client: Any) -> None:
	"""engine/query_loop 每次尝试前注入的归因 meta，同口径。"""
	client._meta_request_id = REQUEST_ID
	client._meta_attempt = ATTEMPT
	client._meta_kind = "turn"


def _openai_client() -> OpenAICompatClient:
	client = OpenAICompatClient(
		api_key=SECRET,
		base_url="https://wire.test/v1",
		model="wm-1",
		provider="openai",
		session_id=SESSION,
	)
	_stamp_meta(client)
	return client


def _deepseek_client(*, session_id: str | None = SESSION) -> DeepSeekModelClient:
	client = DeepSeekModelClient(api_key=SECRET, base_url="https://wire.test", model="ds-1")
	if session_id is not None:
		client.set_session_id(session_id)
	_stamp_meta(client)
	return client


def _anthropic_client() -> AnthropicModelClient:
	client = AnthropicModelClient(
		api_key=SECRET, base_url="https://wire.test", model="cl-1", session_id=SESSION
	)
	_stamp_meta(client)
	return client


def _inject_body_credential(client: Any, monkeypatch, *, secret: bool) -> None:
	"""把凭证样字段塞进待发 body，验证出口打码。

	三个真实适配器都把密钥只放在认证头里（Authorization / x-api-key），body 不含
	密钥；这里显式造出该形态，好让「credential 不落盘」在适配器接线上真被执行到。
	"""
	if not secret:
		return
	build = client._build_body

	def _patched(*args: Any, **kwargs: Any) -> dict[str, Any]:
		body = build(*args, **kwargs)
		body["api_key"] = SECRET
		body["metadata"] = {"Authorization": f"Bearer {SECRET}"}
		return body

	monkeypatch.setattr(client, "_build_body", _patched)


async def _drain(agen: AsyncIterator[ModelChunk]) -> list[ModelChunk]:
	return [chunk async for chunk in agen]


def _chunk_sig(chunks: list[ModelChunk]) -> tuple[str, ...]:
	"""模型可见输出的可比签名（文本增量 + 工具调用及其参数）。"""
	out: list[str] = []
	for chunk in chunks:
		tool = ""
		if chunk.tool_use is not None:
			tool = f"{chunk.tool_use.id}|{chunk.tool_use.name}|{_canon(chunk.tool_use.input)}"
		out.append(f"{chunk.kind}|{chunk.text}|{tool}")
	return tuple(out)


@dataclasses.dataclass(frozen=True)
class Case:
	name: str
	module: Any
	new_client: Callable[[], Any]
	lines: list[str]
	provider: str
	model: str
	stdlib: bool = False
	non_stream: bool = False
	id_header: str = "x-request-id"
	provider_request_id: str = "prov-1"
	# 非流式不是 engine 的流式逻辑调用：适配器自己清掉 request_id（B0.5 归因洁净）。
	expected_request_id: str = REQUEST_ID


@dataclasses.dataclass(frozen=True)
class Send:
	"""一次发送的可核查事实。"""

	wire: str  # 交给 HTTP 客户端的请求体（规范化 JSON 文本）
	reference: str  # 发送之后重新构造的同一 body（捕获接线不参与）
	late: str  # 发送之后再规范化一次当时交给客户端的那个 body 对象
	chunks: tuple[str, ...]  # 适配器 yield 给引擎的块
	sends: int  # 替身观察到的 HTTP 发送次数


def _send(case: Case, monkeypatch, *, secret: bool = False, status: int = 200) -> Send:
	client = case.new_client()
	_inject_body_credential(client, monkeypatch, secret=secret)
	messages, tools = _messages(), _tools()
	headers = {"Retry-After": "7", case.id_header: case.provider_request_id}
	urllib_path = case.stdlib or case.non_stream
	if urllib_path:
		fake: Any = FakeUrlopen(
			_URLResponse(
				case.lines,
				status=status,
				headers=headers,
				json_body=_NON_STREAM_BODY,
			)
		)
		monkeypatch.setattr(case.module, "urlopen", fake)
		monkeypatch.setattr(case.module, "httpx", None)  # 强制 stdlib 分支
	else:
		fake = FakeHTTPXClient(case.lines, status=status, headers=headers)
		monkeypatch.setattr(case.module, "get_shared_httpx_client", lambda timeout: fake)
	if case.non_stream:
		text, tool_uses = asyncio.run(client._complete_non_stream(messages, tools))
		chunks = [
			ModelChunk(kind="text_delta", text=text),
			*[ModelChunk(kind="tool_use", tool_use=tu) for tu in tool_uses],
		]
	else:
		chunks = asyncio.run(_drain(client.stream(messages, tools, AbortController())))
	return Send(
		wire=fake.canon[-1],
		reference=_canon(client._build_body(messages, tools, stream=not case.non_stream)),
		late=fake.canon[-1] if urllib_path else _canon(fake.bodies[-1]),
		chunks=_chunk_sig(chunks),
		sends=len(fake.canon),
	)


_CASES: list[Case] = [
	Case("openai_compat_httpx", openai_module, _openai_client, _OPENAI_SSE, "openai", "wm-1"),
	Case(
		"openai_compat_stdlib",
		openai_module,
		_openai_client,
		_OPENAI_SSE,
		"openai",
		"wm-1",
		stdlib=True,
	),
	Case("deepseek_httpx", deepseek_module, _deepseek_client, _OPENAI_SSE, "deepseek", "ds-1"),
	Case(
		"deepseek_stdlib",
		deepseek_module,
		_deepseek_client,
		_OPENAI_SSE,
		"deepseek",
		"ds-1",
		stdlib=True,
	),
	Case(
		"deepseek_non_stream",
		deepseek_module,
		_deepseek_client,
		[],
		"deepseek",
		"ds-1",
		non_stream=True,
		provider_request_id="prov-ds-ns",
		expected_request_id="",
	),
	Case(
		"anthropic_httpx",
		anthropic_module,
		_anthropic_client,
		_ANTHROPIC_SSE,
		"anthropic",
		"cl-1",
		id_header="request-id",
		provider_request_id="prov-ant-1",
	),
	Case(
		"anthropic_stdlib",
		anthropic_module,
		_anthropic_client,
		_ANTHROPIC_SSE,
		"anthropic",
		"cl-1",
		stdlib=True,
		id_header="request-id",
		provider_request_id="prov-ant-1",
	),
]

ALL_CASES = pytest.mark.parametrize("case", _CASES, ids=[c.name for c in _CASES])

_CASE_BY_NAME = {case.name: case for case in _CASES}


# --------------------------------------------------------------------- 验收


@ALL_CASES
def test_capture_off_is_byte_identical_and_writes_nothing(case: Case, monkeypatch) -> None:
	first = _send(case, monkeypatch)
	second = _send(case, monkeypatch)
	assert cap.capture_enabled(SESSION) is False
	# 上线字节 == 适配器自己构造的 body，且两次逐字一致。
	assert first.wire == first.reference == second.wire
	assert first.late == first.wire
	assert first.chunks == second.chunks
	assert first.sends == 1
	assert _diag_files() == []


@ALL_CASES
def test_capture_on_keeps_bytes_and_chunks_identical_to_off(
	case: Case, monkeypatch
) -> None:
	off = _send(case, monkeypatch)
	_enable()
	on = _send(case, monkeypatch)
	# 记录开/关不得改变上线字节，也不得改变模型可见输出与工具调用。
	assert on.wire == off.wire == on.reference
	assert on.late == on.wire
	assert on.chunks == off.chunks
	assert on.chunks  # 非空：确实在比对模型可见输出，不是两个空元组相等


@ALL_CASES
def test_capture_on_body_hash_matches_stored_json(case: Case, monkeypatch) -> None:
	_enable()
	on = _send(case, monkeypatch)
	rows = _request_rows()
	assert len(rows) == 1
	row = rows[0]
	assert row["session_id"] == SESSION
	assert row["model_request_id"] == case.expected_request_id
	assert row["attempt"] == ATTEMPT
	assert row["provider"] == case.provider
	assert row["model"] == case.model
	blob = _blob_raw(row["body_hash"])
	doc = json.loads(blob)
	assert _rehash(doc["body"]) == row["body_hash"]
	assert row["state"] == COMPLETE
	assert doc["body"] == json.loads(on.wire)
	# 密钥只在认证头里，头部从未进捕获层：正文与索引都不留该字面量。
	assert SECRET not in blob
	assert SECRET not in json.dumps(_rows())


@ALL_CASES
def test_credential_bearing_body_is_redacted_but_still_sent(
	case: Case, monkeypatch
) -> None:
	_enable()
	sent = _send(case, monkeypatch, secret=True)
	assert SECRET in sent.wire  # 发出去的还是原 body
	assert sent.wire == sent.reference
	rows = _request_rows()
	assert len(rows) == 1
	assert rows[0]["state"] == REDACTED  # 脱敏过就不许标完整
	blob = _blob_raw(rows[0]["body_hash"])
	assert SECRET not in blob
	doc = json.loads(blob)
	assert doc["body"]["api_key"] == "[redacted]"
	assert SECRET not in doc["body"]["metadata"]["Authorization"]
	assert SECRET not in json.dumps(_rows())


@ALL_CASES
def test_capture_file_write_failure_does_not_break_send(case: Case, monkeypatch) -> None:
	off = _send(case, monkeypatch)
	_enable()

	def _boom(*_a: Any, **_k: Any) -> None:
		raise OSError("disk full")

	monkeypatch.setattr(cap.os, "replace", _boom)
	on = _send(case, monkeypatch)  # 不得抛
	assert on.wire == off.wire == on.reference
	assert on.chunks == off.chunks
	rows = _request_rows()
	assert len(rows) == 1
	assert rows[0]["state"] == PARTIAL  # 写失败要标缺项，不冒充已捕获
	assert [p for p in _diag_files() if p.suffix == ".gz"] == []


@ALL_CASES
def test_one_http_send_produces_exactly_one_index_row(case: Case, monkeypatch) -> None:
	_enable()
	sent = _send(case, monkeypatch)
	assert sent.sends == 1
	requests = _request_rows()
	assert len(requests) == 1
	joined = cap.captures_for_run(SESSION)
	assert len(joined) == 1  # 一次发送只配一行，重试不靠覆盖
	assert joined[0]["provider_request_id"] == case.provider_request_id
	assert joined[0]["http_status"] == 200
	assert joined[0]["blob_present"] is True
	assert joined[0]["provider"] == case.provider


@ALL_CASES
def test_response_identity_recorded_once_per_send(case: Case, monkeypatch) -> None:
	_enable()
	_send(case, monkeypatch)
	rows = _response_rows()
	assert len(rows) == 1
	assert rows[0]["http_status"] == 200
	assert rows[0]["provider_request_id"] == case.provider_request_id
	assert rows[0]["session_id"] == SESSION
	assert rows[0]["model_request_id"] == case.expected_request_id
	assert rows[0]["attempt"] == ATTEMPT


def test_missing_provider_request_id_is_left_empty(monkeypatch) -> None:
	"""厂商没回请求 id 就留空，不编造。"""
	case = dataclasses.replace(_CASES[0], provider_request_id="")
	_enable()
	_send(case, monkeypatch)
	joined = cap.captures_for_run(SESSION)
	assert len(joined) == 1
	assert joined[0]["provider_request_id"] == ""
	assert joined[0]["http_status"] == 200


def test_session_id_falls_back_to_execution_context_and_turn_is_kept(
	monkeypatch,
) -> None:
	"""客户端未注入 session_id 时接线从执行上下文取，并带 turn_id=trace_id。"""
	_enable()
	client = _deepseek_client(session_id="")
	messages, tools = _messages(), _tools()
	fake = FakeHTTPXClient(_OPENAI_SSE, headers={"x-request-id": "prov-ctx"})
	monkeypatch.setattr(deepseek_module, "get_shared_httpx_client", lambda timeout: fake)
	ctx = ExecutionContext(session_id=SESSION, cwd=".", trace_id="turn_ctx_7")
	with bind_workspace_context(ctx):
		asyncio.run(_drain(client.stream(messages, tools, AbortController())))
	rows = _request_rows()
	assert len(rows) == 1
	assert rows[0]["session_id"] == SESSION
	assert rows[0]["turn_id"] == "turn_ctx_7"
	assert _response_rows()[0]["provider_request_id"] == "prov-ctx"


def test_failed_attempt_keeps_provider_identity_without_changing_failure(
	monkeypatch,
) -> None:
	"""4xx 尝试：抛出的异常一字不差，响应身份照记（429 的可定位事实）。"""

	def _raise(case: Case) -> ProviderError:
		client = case.new_client()
		messages, tools = _messages(), _tools()
		fake = FakeHTTPXClient([], status=429, headers={"x-request-id": "prov-429", "Retry-After": "7"})
		monkeypatch.setattr(
			openai_module, "get_shared_httpx_client", lambda timeout: fake
		)
		with pytest.raises(ProviderError) as caught:
			asyncio.run(_drain(client.stream(messages, tools, AbortController())))
		assert fake.canon, "request must have been handed to the HTTP client"
		return caught.value

	case = _CASES[0]
	off = _raise(case)
	assert _diag_files() == []
	_enable()
	on = _raise(case)
	assert str(off) == str(on)
	assert off.status_code == on.status_code == 429
	assert off.retry_after_ms == on.retry_after_ms
	# 关闭那次零产物；打开那次一行请求 + 一行响应（失败尝试的响应身份照记）。
	assert len(_request_rows()) == 1
	ids = _response_rows()
	assert len(ids) == 1
	assert ids[0]["http_status"] == 429
	assert ids[0]["provider_request_id"] == "prov-429"


def test_same_body_across_attempts_dedupes_blob_but_keeps_rows(
	monkeypatch,
) -> None:
	"""重试同一正文：blob 按 hash 复用，索引仍逐次留痕。"""
	_enable()
	case = _CASES[0]
	first = _send(case, monkeypatch)
	second = _send(case, monkeypatch)
	assert first.wire == second.wire
	rows = _request_rows()
	assert len(rows) == 2
	assert rows[0]["body_hash"] == rows[1]["body_hash"]
	assert rows[0]["deduped"] is False
	assert rows[1]["deduped"] is True
	assert len([p for p in _diag_files() if p.suffix == ".gz"]) == 1


def test_capture_layer_import_failure_does_not_break_send(monkeypatch) -> None:
	"""捕获层不可用（import 失败）时适配器照发不误——观察器不得拖死任务。"""
	case = _CASES[0]
	_enable()
	off = _send(case, monkeypatch)
	monkeypatch.setitem(sys.modules, "diagnostics.capture", None)
	broken = _send(case, monkeypatch)
	assert broken.wire == off.wire == broken.reference
	assert broken.chunks == off.chunks
	assert len(_request_rows()) == 1  # 坏掉的那次没进索引，也没抛


def test_hook_helpers_never_raise_for_unusable_inputs() -> None:
	"""接线自身的 fail-open：奇怪类型也只吞不抛。"""
	_enable()
	assert capture_body(object(), provider="p", model="m", body={"a": 1}) is None
	capture_response(None, http_status=200, headers=None)
	capture_response({}, http_status="not-a-number", headers=object())
	capture_response(
		{"session_id": SESSION, "model_request_id": "r", "attempt": 1, "body_hash": ""},
		http_status=200,
		headers={"request-id": "prov-x"},
	)
	assert len(_response_rows()) == 1


def test_max_tokens_survives_capture_verbatim(monkeypatch) -> None:
	"""回归护栏：``max_tokens`` 是有效参数，不是凭证。

	捕获层早先用子串匹配密钥名，"token" 命中每个 Anthropic/OpenAI body 的
	``max_tokens`` ⇒ 每次捕获都被打成 redacted 且参数被抹掉，可复现记录失去意义。
	现在按名精确判定，这里钉住修复后的语义：正文逐字保留、state 保持 full。
	"""
	_enable()
	wire = json.loads(_send(_CASE_BY_NAME["anthropic_httpx"], monkeypatch).wire)
	assert wire["max_tokens"]  # Anthropic 必带该字段
	row = _request_rows()[0]
	doc = json.loads(_blob_raw(row["body_hash"]))
	assert doc["body"]["max_tokens"] == wire["max_tokens"]
	assert row["state"] == COMPLETE
