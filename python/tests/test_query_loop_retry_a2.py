"""44 号 A2：LLM 失败语义协议化——重试环行为（query_loop 级）。

用会失败一次的模型客户端验证：
- 429 等可重试错误 → 先发 LlmRetryEvent（含 code/next_retry_ms）→ 重试开始帧 → 成功；
- 失败尝试零 chunk（请求未产出）→ assistant 消息只落一次（无半条/重复）；
- 401 等不可重试错误 → 立即向上抛（无重试帧）；
- 空响应（零 chunk 正常结束）→ 按 empty_response 重试，耗尽后抛 EmptyResponseError；
- 已产出 chunk 的尝试不原地重试（防 GUI 重复吐字）→ 直接抛错、无重试帧。
"""

import sys
from pathlib import Path
from typing import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from common.errors import EmptyResponseError, ProviderError
from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from model.chunks import ModelChunk
from model.fake import FakeModelClient
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from session.message_store import MessageStore
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from msgtypes.events import FinalEvent, LlmRetryEvent, LlmRetryStartedEvent
from msgtypes.message import user_message


class _FlakyClient(FakeModelClient):
	"""先失败 fail_times 次（抛指定错误 / 空响应 / 先吐一个 chunk 再错），之后转正常。"""

	def __init__(
		self,
		*,
		fail_times: int = 1,
		error: Exception | None = None,
		empty: bool = False,
		chunk_before_error: bool = False,
	) -> None:
		super().__init__()
		self._fail_times = fail_times
		self._error = error
		self._empty = empty
		self._chunk_before_error = chunk_before_error
		self.calls = 0

	async def stream(self, messages, tool_schemas, abort) -> AsyncIterator[ModelChunk]:
		self.calls += 1
		if self.calls <= self._fail_times:
			if self._chunk_before_error:
				yield ModelChunk(kind="text_delta", text="partial")
			if self._error is not None:
				raise self._error
			return  # 正常结束但零 chunk：EMPTY_RESPONSE
		async for chunk in super().stream(messages, tool_schemas, abort):
			yield chunk


def _patch_retry(monkeypatch) -> None:
	monkeypatch.setattr("engine.query_loop._llm_max_attempts", lambda: 3)
	monkeypatch.setattr("engine.query_loop._llm_retry_delay_ms", lambda attempt, after: 1)


async def _run(client, monkeypatch) -> tuple[list[object], MessageStore]:
	_patch_retry(monkeypatch)
	store = MessageStore([user_message("hello")])
	reg = ToolRegistry()
	reg.register(EchoTool())
	events: list[object] = []
	async for ev in query_loop(
		store=store,
		model=client,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
	):
		events.append(ev)
	return events, store


@pytest.mark.asyncio
async def test_retry_after_429_then_success(monkeypatch) -> None:
	client = _FlakyClient(
		fail_times=1, error=ProviderError("rate limited", status_code=429, retry_after_ms=0)
	)
	events, store = await _run(client, monkeypatch)
	retries = [e for e in events if isinstance(e, LlmRetryEvent)]
	started = [e for e in events if isinstance(e, LlmRetryStartedEvent)]
	assert len(retries) == 1
	assert retries[0].code == "rate_limit"
	assert retries[0].next_retry_ms == 1
	assert retries[0].attempt == 1
	assert len(started) == 1 and started[0].attempt == 2
	assert client.calls == 2
	assert any(isinstance(e, FinalEvent) for e in events)
	# assistant 消息只落一次（失败尝试零 chunk，不产生半条/重复）。
	assistant_rows = [m for m in store.items if m.role == "assistant"]
	assert len(assistant_rows) == 1


@pytest.mark.asyncio
async def test_empty_response_retried_then_success(monkeypatch) -> None:
	client = _FlakyClient(fail_times=1, empty=True)
	events, _store = await _run(client, monkeypatch)
	retries = [e for e in events if isinstance(e, LlmRetryEvent)]
	assert len(retries) == 1
	assert retries[0].code == "empty_response"
	assert client.calls == 2
	assert any(isinstance(e, FinalEvent) for e in events)


@pytest.mark.asyncio
async def test_auth_error_not_retried(monkeypatch) -> None:
	client = _FlakyClient(fail_times=99, error=ProviderError("bad key", status_code=401))
	with pytest.raises(ProviderError):
		await _run(client, monkeypatch)
	assert client.calls == 1


@pytest.mark.asyncio
async def test_retry_exhausted_raises_provider_error(monkeypatch) -> None:
	client = _FlakyClient(fail_times=99, error=ProviderError("overloaded", status_code=503))
	with pytest.raises(ProviderError):
		await _run(client, monkeypatch)
	assert client.calls == 3  # 尝试 1 + 2 次重试 = 3 次


@pytest.mark.asyncio
async def test_empty_response_exhausted_raises_empty_error(monkeypatch) -> None:
	client = _FlakyClient(fail_times=99, empty=True)
	with pytest.raises(EmptyResponseError):
		await _run(client, monkeypatch)
	assert client.calls == 3


@pytest.mark.asyncio
async def test_chunk_before_error_no_inplace_retry(monkeypatch) -> None:
	"""已产出 chunk 的尝试不原地重试（防 GUI 重复吐字）：直接抛错，无重试帧。"""
	client = _FlakyClient(
		fail_times=99,
		error=ProviderError("conn reset", status_code=503),
		chunk_before_error=True,
	)
	with pytest.raises(ProviderError):
		await _run(client, monkeypatch)
	assert client.calls == 1


class _AbortMidStreamClient(FakeModelClient):
	"""吐一个 chunk 后触发 abort（第二次 raise_if_aborted 即抛 Aborted）。"""

	def __init__(self, abort: AbortController) -> None:
		super().__init__()
		self._abort = abort
		self.calls = 0

	async def stream(self, messages, tool_schemas, abort) -> AsyncIterator[ModelChunk]:
		self.calls += 1
		yield ModelChunk(kind="text_delta", text="这是被中断的半")
		self._abort.abort()
		abort.raise_if_aborted()
		if False:  # pragma: no cover
			yield ModelChunk(kind="text_delta", text="句")


@pytest.mark.asyncio
async def test_abort_persists_interrupted_anchor(monkeypatch) -> None:
	"""44 号 A3：abort 时已有非空前缀 → 部分输出以 interrupted 锚入史。"""
	from engine.abort import Aborted
	from msgtypes.events import StoppedEvent

	abort = AbortController()
	client = _AbortMidStreamClient(abort)
	monkeypatch.setattr("engine.query_loop._llm_max_attempts", lambda: 3)
	monkeypatch.setattr("engine.query_loop._llm_retry_delay_ms", lambda attempt, after: 1)
	store = MessageStore([user_message("hello")])
	reg = ToolRegistry()
	reg.register(EchoTool())
	events: list[object] = []
	async for ev in query_loop(
		store=store,
		model=client,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=abort,
		budget=BudgetTracker(max_turns=4),
	):
		events.append(ev)
	assert client.calls == 1
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "aborted"
	assert stopped[-1].interrupted is True
	# 半句话已入史（用户看到的必须入史）。
	anchor = [m for m in store.items if m.role == "assistant"]
	assert len(anchor) == 1
	assert anchor[0].interrupted is True
	assert "被中断的半" in str(anchor[0].content)


@pytest.mark.asyncio
async def test_abort_without_content_no_anchor(monkeypatch) -> None:
	"""44 号 A3：abort 前零输出 → 不写中断锚（没有「用户看到的」）。"""
	from msgtypes.events import StoppedEvent

	abort = AbortController()
	client = _FlakyClient(fail_times=0)  # 正常客户端，但马上 abort
	class _NoOutput(_FlakyClient):
		async def stream(self, messages, tool_schemas, abort_) -> AsyncIterator[ModelChunk]:
			abort_.raise_if_aborted()
			abort.abort()
			abort_.raise_if_aborted()
			return
			yield  # pragma: no cover
	client = _NoOutput(fail_times=0)
	monkeypatch.setattr("engine.query_loop._llm_max_attempts", lambda: 3)
	monkeypatch.setattr("engine.query_loop._llm_retry_delay_ms", lambda attempt, after: 1)
	store = MessageStore([user_message("hello")])
	reg = ToolRegistry()
	reg.register(EchoTool())
	events: list[object] = []
	async for ev in query_loop(
		store=store,
		model=client,
		tools=reg,
		prompt=PromptAssembler(),
		system_prompt=DEFAULT_SYSTEM,
		abort=abort,
		budget=BudgetTracker(max_turns=4),
	):
		events.append(ev)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "aborted"
	assert stopped[-1].interrupted is False
	assert not [m for m in store.items if m.role == "assistant"]
