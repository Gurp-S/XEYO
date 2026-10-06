"""API 与可见性台账必须共享最新状态、声道、撤回和配对清理口径。"""

from msgtypes.message import ToolUse, assistant_text_message, notice_note, system_note, tool_result_message, user_message
from session.message_store import MessageStore
import pytest


def test_state_update_shares_latest_constraints_with_visibility():
	store = MessageStore([user_message("request"), system_note("old contract", key="contract", fp="old"), assistant_text_message("result")])
	before = store.as_api_messages()
	store.append(system_note("new contract", key="contract", fp="new"))
	store.append(user_message("follow-up"))
	after = store.as_api_messages()
	assert after[0] == before[0] and after[1] == before[2]
	assert [row["content"] for row in after] == ["request", "result", "new contract", "follow-up"]
	assert store.note_fingerprints(start=2) == {("contract", "new")}
	assert store.note_fingerprints(start=3) == set()
	assert len(store.items) == 5  # 原始留痕面完整。


def test_retraction_policy_and_reload_use_same_visible_state():
	store = MessageStore([user_message("request"), system_note("system", key="system", fp="s"), notice_note("notice", key="notice", fp="n")])
	store.set_note_policy(False)
	assert store.note_fingerprints() == {("notice", "n")}
	assert [row["content"] for row in store.as_api_messages()] == ["request", "notice"]
	store.retract_note("notice")
	assert not store.note_fingerprints()
	store.set_note_policy(True)
	assert store.note_fingerprints() == {("system", "s")}
	reloaded = MessageStore(list(store.items))
	assert reloaded.as_api_messages() == store.as_api_messages()


def test_visibility_uses_positions_after_tool_pair_repair():
	store = MessageStore([
		user_message("inspect"),
		assistant_text_message("", [ToolUse(id="c", name="Read", input={})]),
		system_note("current constraint", key="world_state", fp="current"),
		tool_result_message("c", "Read", "result"),
	])
	# 先查询去重身份也必须触发与 API 完全相同的配对整理。
	assert store.note_fingerprints(start=3) == {("world_state", "current")}
	assert store.as_api_messages()[2]["role"] == "tool"
	assert store.note_fingerprints(start=4) == set()


def test_api_cache_mutations_still_repair_pairs_and_update_state():
	store = MessageStore([user_message("inspect")])
	cached = store.as_api_messages()
	assert store.as_api_messages() is cached
	store.append(assistant_text_message("", [ToolUse(id="c", name="Read", input={})]))
	store.append(system_note("contract", key="world_state", fp="current"))
	store.append(tool_result_message("c", "Read", "result"))
	rows = store.as_api_messages()
	assert rows is not cached and rows[2]["role"] == "tool"
	store.retract_note("world_state")
	assert not any(row.get("note_key") for row in store.as_api_messages())
	store.replace([user_message("new request")])
	assert [row["content"] for row in store.as_api_messages()] == ["new request"]
	store.insert(0, user_message("earlier request"))
	assert store.as_api_messages()[0]["content"] == "earlier request"


@pytest.mark.asyncio
async def test_mutable_state_cannot_reuse_stale_incremental_projection(mem_switch):
	from engine.abort import AbortController
	from engine.budget import BudgetTracker
	from engine.query_loop import query_loop
	from memory.working import WorkingSnapshot
	from model.chunks import ModelChunk
	from prompt.assembler import PromptAssembler
	from tools.tool_registry import ToolRegistry

	mem_switch(XEYO_L5="project")
	store = MessageStore([user_message("inspect"), system_note("old contract", key="contract", fp="old"), system_note("current contract", key="contract", fp="current")])
	working = WorkingSnapshot(session_id="state-cache-regression")
	working.proj_cache = (len(store), 0, 0, 0, [{"role": "user", "content": "stale cache contract"}], {})

	class CaptureModel:
		messages = None

		async def stream(self, messages, tools, abort):
			self.messages = messages
			yield ModelChunk(kind="text_delta", text="done")

	model = CaptureModel()
	async for _ in query_loop(store=store, model=model, tools=ToolRegistry(), prompt=PromptAssembler(), system_prompt="facts", abort=AbortController(), budget=BudgetTracker(max_turns=2), working=working):
		pass
	assert model.messages is not None
	text = str(model.messages)
	assert "current contract" in text
	assert "stale cache contract" not in text
	assert "old contract" not in text
