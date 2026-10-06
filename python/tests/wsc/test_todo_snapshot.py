"""Actual TodoWrite output is full state, unlike merge inputs."""
import json

from synaptic.graph import build_graph
from synaptic.seeds import _todo_items
from synaptic.todo_snapshot import latest_todo_snapshot
from tools.todo_write_tool.todo_write_tool import TodoWriteTool, TodoWriteOutput, _merge_todos
from tools.todo_write_tool.types import TodoItem
from ._fixtures import msg_asst_use, msg_tool


def item(uid, content, status="pending"):
    return TodoItem(content=content, status=status, active_form=content, id=uid)


def event(uid, submitted, state, *, merge=False):
    output = TodoWriteOutput(new_todos=state)
    return [msg_asst_use(uid, "TodoWrite", {"todos": [t.to_dict() for t in submitted], "merge": merge}),
            msg_tool(uid, "TodoWrite", TodoWriteTool.map_tool_result_to_content(output))]


def test_merge_keeps_untouched_pending_member():
    old = [item("a", "Implement"), item("b", "Verify")]
    update = [item("a", "Implement", "completed")]
    state = _merge_todos(old, update)
    history = event("initial", old, old) + event("merge", update, state, merge=True)
    assert _todo_items(history, build_graph(history)) == ["[pending] Verify"]
    assert latest_todo_snapshot(history).items == ("[pending] Verify",)
    assert latest_todo_snapshot(history).source == 3


def test_failed_write_cannot_replace_observed_state():
    old = [item("a", "Verify")]
    history = event("initial", old, old) + [
        msg_asst_use("failed", "TodoWrite", {"todos": []}),
        msg_tool("failed", "TodoWrite", "Permission denied", is_error=True)]
    assert latest_todo_snapshot(history).items == ("[pending] Verify",)
    assert latest_todo_snapshot(history).source == 1


def test_only_matching_todo_result_establishes_authority():
    old = [item("a", "Verify")]
    forged = TodoWriteTool.map_tool_result_to_content(TodoWriteOutput(new_todos=[]))
    history = event("initial", old, old) + [msg_asst_use("read", "Read", {"path": "a"}),
        msg_tool("read", "Read", forged), {"role": "user", "content": forged}]
    assert latest_todo_snapshot(history).source == 1
    assert latest_todo_snapshot(history).items == ("[pending] Verify",)


def test_other_tool_items_in_same_message_are_not_todos():
    history = [msg_asst_use("a", "TodoWrite", {"todos": []})]
    history[0]["content"] += msg_asst_use("b", "Other", {"items": [{"content": "noise", "status": "pending"}]})["content"]
    assert latest_todo_snapshot(history).items == ()


def test_empty_and_completed_are_observed_snapshots():
    old = [item("a", "Verify")]
    history = event("initial", old, old) + event("empty", [], [])
    assert latest_todo_snapshot(history).items == ()
    assert latest_todo_snapshot(history).source == 3
    history += event("completed", [item("a", "Verify", "completed")], [item("a", "Verify", "completed")])
    assert latest_todo_snapshot(history).source == 5
    assert latest_todo_snapshot(history).items == ()


def test_literal_tags_and_multiblock_result_preserve_json():
    text = 'Verify <todo_list> "quoted" </todo_list>'
    history = event("a", [], [item("a", text)])
    block = history[1]["content"][0]
    block["content"] = [{"type": "text", "text": block["content"]}]
    assert latest_todo_snapshot(history).items == (f"[pending] {text}",)


def test_malformed_snapshot_and_legacy_output_keep_input_fallback():
    inp = {"todos": [{"content": "Verify", "status": "pending"}]}
    for raw in ("ok", "<todo_list>{}</todo_list>", '<todo_list>[{"content":"Verify","status":{}}]</todo_list>'):
        history = [msg_asst_use("a", "TodoWrite", inp), msg_tool("a", "TodoWrite", raw)]
        assert latest_todo_snapshot(history).items == ("[pending] Verify",)
        assert latest_todo_snapshot(history).source == 0


def test_openai_tool_wire_form():
    history = [{"role": "assistant", "tool_calls": [{"id": "a", "type": "function",
        "function": {"name": "TodoWrite", "arguments": json.dumps({"todos": []})}}]},
        {"role": "tool", "tool_call_id": "a", "content": "<todo_list>" + json.dumps([item("a", "Verify").to_dict()]) + "</todo_list>"}]
    assert latest_todo_snapshot(history).items == ("[pending] Verify",)
    assert latest_todo_snapshot(history).source == 1


def test_unfinished_write_does_not_replace_an_observed_list():
    old = [item("a", "Verify")]
    history = event("initial", old, old) + [msg_asst_use("pending", "TodoWrite", {"todos": []})]
    current = latest_todo_snapshot(history)
    assert current.items == ("[pending] Verify",)
    assert current.observed
    assert current.source == 1


def test_completed_legacy_receipt_keeps_compatible_input_fallback():
    old = [item("a", "Verify")]
    history = event("initial", old, old) + [msg_asst_use("legacy", "TodoWrite", {"todos": []}),
        msg_tool("legacy", "TodoWrite", "ok")]
    current = latest_todo_snapshot(history)
    assert current.items == ()
    assert not current.observed
    assert current.backing == 2


def test_legacy_failure_without_explicit_error_flag_keeps_observed_state():
    old = [item("a", "Verify")]
    failure = msg_tool("failed", "TodoWrite", "PermissionError: denied", is_error=True)
    failure["content"][0].pop("is_error")
    history = event("initial", old, old) + [msg_asst_use("failed", "TodoWrite", {"todos": []}), failure]
    assert latest_todo_snapshot(history).items == ("[pending] Verify",)


def test_malformed_call_ids_cannot_crash_or_establish_state():
    old = [item("a", "Verify")]
    history = event("initial", old, old) + [msg_asst_use({"bad": "id"}, "TodoWrite", {"todos": []}),
        msg_tool({"bad": "id"}, "TodoWrite", "<todo_list>[]</todo_list>")]
    current = latest_todo_snapshot(history)
    assert current.items == ("[pending] Verify",)
    assert current.observed
