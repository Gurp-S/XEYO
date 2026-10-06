from memory import wsc_projection as wp
from memory.working import WorkingSnapshot
from msgtypes.message import ToolUse, assistant_text_message, system_note, tool_result_message, user_message
from session.message_store import MessageStore
from evals.wsc_extension_economics_ab import canonical_projection
import json
import pytest


@pytest.mark.parametrize("note_keys", [("world_state",), ("world_state", "goal")])
def test_replaced_state_and_new_round_cannot_reuse_split_tool_boundary(tmp_path, monkeypatch, note_keys):
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "0")
	monkeypatch.setenv("XEYO_WSC_FROZEN_HEAD", "1")
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	store = MessageStore([user_message("inspect API"), *[system_note("old state", key=key, fp="old") for key in note_keys]])
	for i in range(14):
		store.append(assistant_text_message("", [ToolUse(id=f"call_{i}", name="Bash", input={"command": f"inspect {i}"})]))
		store.append(tool_result_message(f"call_{i}", "Bash", f"result {i}\n" + "API detail\n" * 120))
	w = WorkingSnapshot(session_id="note_boundary_rewrite", compact_cursor=12, c1_frozen_until=12)
	wp._STATE.clear()
	try:
		first = wp.project_c2_messages(store.as_api_messages(), w, cwd=str(tmp_path))
		assert first
		before = wp._STATE[wp._state_key(w.session_id, str(tmp_path))]
		old_head = before.head
		for key in note_keys:
			store.append(system_note("new state", key=key, fp="new"))
		store.append(assistant_text_message("", [ToolUse(id="call_14", name="Bash", input={"command": "inspect 14"})]))
		store.append(tool_result_message("call_14", "Bash", "fresh result\n" + "API detail\n" * 120))
		second = wp.project_c2_messages(store.as_api_messages(), w, cwd=str(tmp_path))
		assert second
		after = wp._STATE[wp._state_key(w.session_id, str(tmp_path))]
		assert after.head != old_head
		assert wp._junction_intact(store.as_api_messages(), after.region_end)
		wire = json.loads(canonical_projection(second, "openai"))
		tail_results = [block["tool_use_id"] for row in second for block in (row.get("content") if isinstance(row.get("content"), list) else [])
		                if isinstance(block, dict) and block.get("type") == "tool_result"]
		assert tail_results == [row["tool_call_id"] for row in wire if row["role"] == "tool"]
		# 曾经被孤儿清理静默丢弃的第 11 条结果，在重建后仍有完整原文。
		assert any("result 11\nAPI detail" in text for text in after.cold.texts.values()) or any(
			"result 11\nAPI detail" in str(row.get("content")) for row in second
		)
	finally:
		wp._STATE.clear()
