"""增量投影缓存的 base_len 必须落在**投影**下标空间，不是 append-only 历史空间。

合同（``engine/query_loop.py`` 的 ``proj_cache`` 分支）：命中后用
``api_all[base_len:]`` 取新段，而 ``api_all = store.as_api_messages()`` 是**筛选
后**的列表（``session/state_projection.current_context_items`` 会把被取代 / 已撤回
的留痕整行剔掉；``discard_unpaired_tool_results`` 会剔掉无主结果）。可
``cur_len = len(store)`` 数的是**未筛选**的历史行。两者一旦不等，切片就跳过
``len(store) - len(api_all)`` 条真实消息：上一枪的助手回复（或一条工具结果）
直接从模型输入里消失，且**不出现在任何报错里**。

同一分支的既有守卫只挡了"投影里还留着带 note_key 的行"这一半
（``use_proj_cache = ... and not any(row.get("note_key") ...)``）；会话里**所有**
留痕都被撤回（或声道降级后 system 形态留痕全部不可见）时该条件为假、缓存照用，
位移就发生——这正是 ``prompt/pre_llm_inject.py`` 里"本轮一个状态段都没产出 ⇒
上一版整段必须离开投影"的常态出口。

对照档（等长的普通会话）必须保持绿色：它证明丢消息不是夹具本身的问题，
而是"历史比投影长"这一个条件触发的。
"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from memory.working import WorkingSnapshot
from model.chunks import ModelChunk
from msgtypes.message import system_note, user_message
from prompt.assembler import PromptAssembler
from session.message_store import MessageStore
from tools.tool_registry import ToolRegistry

FIRST_USER = "FIRST-MARKER-用户原始问题"
FIRST_REPLY = "FIRST-REPLY-助手上一枪的回答"
SECOND_USER = "SECOND-MARKER-本枪唯一的新事实"


class _CaptureModel:
	"""记录每一枪模型真正收到的消息列表；回复文本固定，便于判定可见性。"""

	def __init__(self) -> None:
		self.shots: list[list[dict]] = []

	async def stream(self, messages, tools, abort):
		del tools
		abort.raise_if_aborted()
		self.shots.append([m for m in messages if isinstance(m, dict)])
		yield ModelChunk(kind="text_delta", text=FIRST_REPLY)


async def _run(store: MessageStore, model: _CaptureModel, working) -> None:
	async for _ in query_loop(
		store=store,
		model=model,
		tools=ToolRegistry(),
		prompt=PromptAssembler(),
		system_prompt="facts",
		abort=AbortController(),
		budget=BudgetTracker(max_turns=4),
		working=working,
	):
		pass


def _blob(rows: list[dict]) -> str:
	return str(rows)


@pytest.mark.asyncio
async def test_equal_length_history_reuses_increment_safely(mem_switch):
	"""对照（必须绿）：历史与投影等长时，上一枪回复与新增消息都要可见。"""
	mem_switch(XEYO_L5="project")
	store = MessageStore([user_message(FIRST_USER)])
	working = WorkingSnapshot(session_id="cache-space-control")
	assert len(store) == len(store.as_api_messages())

	model = _CaptureModel()
	await _run(store, model, working)

	store.append(user_message(SECOND_USER))
	await _run(store, model, working)

	assert working.proj_cache is not None, "对照档必须真的走到增量缓存分支"
	last = _blob(model.shots[-1])
	assert FIRST_USER in last
	assert FIRST_REPLY in last, "等长历史下增量缓存不得丢消息（夹具自证）"
	assert SECOND_USER in last


@pytest.mark.asyncio
async def test_retracted_note_must_not_shift_incremental_projection(mem_switch):
	"""缺陷档（已修，本条钉死回归）：历史比投影长时增量缓存不得跳过头部消息。"""
	mem_switch(XEYO_L5="project")
	store = MessageStore([user_message(FIRST_USER), system_note("contract", key="world_state", fp="v1")])
	assert store.retract_note("world_state") == 1
	# 前置：投影确实比历史短一行，且投影里已无 note_key（缓存分支可用）。
	assert len(store) == 2 and len(store.as_api_messages()) == 1
	assert not any(row.get("note_key") for row in store.as_api_messages())

	working = WorkingSnapshot(session_id="cache-space-divergence")
	model = _CaptureModel()
	await _run(store, model, working)
	assert working.proj_cache is not None, "缺陷前提：本枪建立了增量缓存"
	assert len(store) > len(store.as_api_messages()), "缺陷前提：历史仍长于投影"

	store.append(user_message(SECOND_USER))
	await _run(store, model, working)

	last = _blob(model.shots[-1])
	assert SECOND_USER in last, "夹具自证：新增消息要能进到本枪请求里"
	assert FIRST_REPLY in last, (
		"丢消息：上一枪的助手回复被 api_all[base_len:] 的错误下标跳过"
	)
