"""Multi-Agent chip：软提示偏向 Agent，不裁剪工具、不拦截收尾。"""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import _attach_turn_context, _plan_tool_schemas, query_loop
from model.chunks import ModelChunk
from msgtypes.events import FinalEvent
from msgtypes.message import user_message
from prompt.assembler import PromptAssembler
from session.message_store import MessageStore
from tools.agent_tool.prompt import MULTI_AGENT_HINT
from tools.catalog import build_default_registry


@pytest.fixture
def registry(tmp_path):
	return build_default_registry(cwd=str(tmp_path))


def test_multi_agent_keeps_full_tool_schemas(registry):
	names = {
		str(s.get("name") or "")
		for s in _plan_tool_schemas(registry, registry.schemas())
	}
	assert "Agent" in names
	assert "Glob" in names
	assert "Read" in names


def test_attach_turn_context_injects_soft_hint():
	msgs = [{"role": "user", "content": "分别总结 a 与 b"}]
	out = _attach_turn_context(
		msgs,
		approved_plan=None,
		forced_wrap_up=False,
		runtime_notice=None,
		include_memory_index=False,
		multi_agent=True,
	)
	last = out[-1]
	content = last.get("content")
	blob = content if isinstance(content, str) else str(content)
	assert "用户开启了 multi-agent" in blob

	plain = _attach_turn_context(
		msgs,
		approved_plan=None,
		forced_wrap_up=False,
		runtime_notice=None,
		include_memory_index=False,
		multi_agent=False,
	)
	plain_blob = str(plain[-1].get("content"))
	assert "Multi-Agent preference" not in plain_blob


def test_attach_after_tool_skips_memory_index(monkeypatch):
	"""工具轮后尾插 Continue，且不挂 Memory index（否则弱模型答非所问）。"""
	from prompt.turn_context import CONTINUE_AFTER_TOOLS

	monkeypatch.setattr(
		"memory.runtime.memory_index_context_block",
		lambda: "# Memory index (background only — NOT the user request)\n- old test entry",
	)
	msgs = [
		{"role": "user", "content": "测试多agent工具"},
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": "1", "name": "Agent"}],
		},
		{
			"role": "tool",
			"content": "[Agent tool_result] created test file ok",
		},
	]
	out = _attach_turn_context(
		msgs,
		approved_plan=None,
		forced_wrap_up=False,
		runtime_notice=None,
		include_memory_index=True,
		multi_agent=False,
	)
	assert out[-1]["role"] in {"user", "system"}
	# 声道无关：legacy=text 块（Continue 首块）；env_channel（方案A）=伪对
	# tool_result 正文；system_channel（默认档，2026-09-15 起）=原生 system 消息。
	content = out[-1]["content"]
	parts = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
	texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
	res = [
		str(p.get("content") or "")
		for p in parts
		if isinstance(p, dict) and p.get("type") == "tool_result"
	]
	blob = "\n".join([*texts, *res])
	assert blob.strip(), blob
	assert "# Continue" in blob
	assert CONTINUE_AFTER_TOOLS[:20] in blob
	assert "Memory index" not in blob
	assert "old test entry" not in blob


def test_attach_on_user_turn_no_longer_pushes_memory(monkeypatch):
	"""批次3：Memory index 不再推送 T_now（能力宣告住工具 description）。"""
	monkeypatch.setattr(
		"memory.runtime.memory_index_context_block",
		lambda: "# Memory index (background only — NOT the user request)\n- note",
	)
	msgs = [{"role": "user", "content": "普通问题"}]
	out = _attach_turn_context(
		msgs,
		approved_plan=None,
		forced_wrap_up=False,
		runtime_notice=None,
		include_memory_index=True,
		multi_agent=False,
	)
	blob = str(out[-1].get("content"))
	assert "Memory index" not in blob
	assert "note" not in blob


@pytest.mark.asyncio
async def test_no_remediation_after_glob_without_agent(registry):
	"""干活用 Glob 后直接文本收尾 → 立即 Final，不再补 Agent-only 轮。"""

	class _GlobThenDone:
		def __init__(self) -> None:
			self.turns = 0

		async def stream(
			self,
			messages: list[dict[str, Any]],
			tools: list[dict],
			abort: AbortController,
		) -> AsyncIterator[ModelChunk]:
			from msgtypes.message import ToolUse

			abort.raise_if_aborted()
			self.turns += 1
			if self.turns == 1:
				yield ModelChunk(
					kind="tool_use",
					tool_use=ToolUse(
						id="g1", name="Glob", input={"pattern": "a/**"}
					),
				)
				return
			yield ModelChunk(kind="text_delta", text="done without agent")

	store = MessageStore([user_message("分别总结 a 与 b")])
	model = _GlobThenDone()
	events = []
	async for ev in query_loop(
		store=store,
		model=model,
		tools=registry,
		prompt=PromptAssembler(),
		system_prompt="sys",
		abort=AbortController(),
		budget=BudgetTracker(
			max_turns=6,
			max_tool_calling=12,
			usd_limit=None,
			provider="fake",
			model="fake",
		),
		multi_agent=True,
	):
		events.append(ev)

	assert model.turns == 2
	finals = [e for e in events if isinstance(e, FinalEvent)]
	assert len(finals) == 1
	assert "done without agent" in finals[0].text
