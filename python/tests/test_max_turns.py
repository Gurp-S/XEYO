import sys
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import ResultEvent, StoppedEvent
from msgtypes.message import ToolUse
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


class AlwaysToolModel:
	"""每次都返回 tool_use，用于验证 max_turns 的共享 grace。"""

	def __init__(self) -> None:
		self.calls = 0
		self.messages: list[list[dict]] = []
		self.tools: list[list[dict]] = []

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		self.calls += 1
		self.messages.append(messages)
		self.tools.append(tools)
		abort.raise_if_aborted()
		yield ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(
				id=f"call_{uuid4().hex[:8]}",
				name="echo",
				input={"text": "loop"},
			),
		)


class FinishOnGraceModel(AlwaysToolModel):
	"""在第一个 grace Turn 返回文本，验证可以正常完成。"""

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		self.calls += 1
		self.messages.append(messages)
		self.tools.append(tools)
		abort.raise_if_aborted()
		if self.calls == 4:
			yield ModelChunk(kind="text_delta", text="已收尾")
			return
		yield ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(
				id=f"call_{uuid4().hex[:8]}",
				name="echo",
				input={"text": "loop"},
			),
		)


def _engine(model: object) -> QueryEngine:
	reg = ToolRegistry()
	reg.register(EchoTool())
	return QueryEngine(
		{
			"cwd": ".",
			"tools": reg,
			"model_client": model,  # type: ignore[typeddict-item]
			"max_turns": 3,
			"max_tool_calling": 16,
		}
	)


def _system_text(messages: list[dict]) -> str:
	return "\n".join(
		str(message.get("content", ""))
		for message in messages
		if message.get("role") == "system"
	)


def _request_text(messages: list[dict]) -> str:
	"""整份请求文本（含 T_now 投影 user 块），用于断言 runtime / wrap-up。"""
	parts: list[str] = []
	for message in messages:
		content = message.get("content", "")
		if isinstance(content, list):
			for block in content:
				if isinstance(block, dict):
					parts.append(str(block.get("text") or block.get("content") or ""))
		else:
			parts.append(str(content))
	return "\n".join(parts)


@pytest.mark.asyncio
async def test_max_turns_allows_three_shared_grace_turns_and_stops():
	model = AlwaysToolModel()
	eng = _engine(model)
	events = [event async for event in eng.submit("go")]

	stopped = [event for event in events if isinstance(event, StoppedEvent)]
	assert stopped and stopped[-1].reason == "max_turns"
	# 3 主轮 + 3 grace 轮 + 1 次硬停前的禁工具收尾调用（query_loop 强制 wrap-up）。
	# 收尾仍无文本（假模型硬吐 tool_use）→ 回退原 max_turns 硬停语义。
	assert model.calls == 7
	assert eng._session.budget.turn_count == 7
	# 收尾轮也经 begin_turn 计入共享 grace（3+1=4）。
	assert eng._session.budget.grace_turns_used == 4
	# 回归断言（S1 修复）：收尾请求（最后一枪）仍保留与常规轮一致的 tools。
	# 若在此摘掉 tools，DeepSeek 会从工具段起整段前缀错位重哈希，收尾枪命中率
	# 坍缩到仅 system 段（观测 90%+ → 6%），白付一次全量 miss。
	assert model.tools[-1] == model.tools[0]
	assert len(model.tools[-1]) > 0

	warning = "任务已经运行较久，请检查进度并准备收尾。"
	requests_with_warning = [
		_request_text(messages).count(warning) for messages in model.messages
	]
	assert requests_with_warning == [0, 0, 0, 1, 0, 0, 0]
	# 提醒挂 T_now，不得进 system 左段（KV）。
	assert all(warning not in _system_text(m) for m in model.messages)
	wrapup = "# Wrap-up required"
	assert wrapup in _request_text(model.messages[-1])
	assert wrapup not in _system_text(model.messages[-1])
	assert all(wrapup not in _request_text(m) for m in model.messages[:-1])
	assert warning not in "\n".join(
		str(message.content) for message in eng._session.messages.items
	)

	results = [event for event in events if isinstance(event, ResultEvent)]
	assert results and results[-1].subtype == "error_max_turns"
	assert results[-1].is_error is True
	assert results[-1].stop_reason == "max_turns"


@pytest.mark.asyncio
async def test_max_turns_grace_can_finish_normally():
	model = FinishOnGraceModel()
	eng = _engine(model)
	events = [event async for event in eng.submit("go")]

	assert model.calls == 4
	results = [event for event in events if isinstance(event, ResultEvent)]
	assert results and results[-1].subtype == "success"
	assert results[-1].result == "已收尾"
	assert not any(
		isinstance(event, StoppedEvent) and event.reason == "max_turns"
		for event in events
	)


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
