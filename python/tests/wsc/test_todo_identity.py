"""Task completion uses actual IDs from the declared source, not short labels."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import json

import pytest

from memory.wsc_projection import production_params
from synaptic.project import project
from synaptic.todo_snapshot import _payload, latest_todo_snapshot
from tests.wsc._fixtures import msg_asst_use, msg_tool, msg_user
from tests.wsc._recovery_contract import parse_read_refs
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers
from tests.wsc.test_todo_snapshot import event, item
from tools.todo_write_tool.todo_write_tool import (
    TodoWriteOutput, TodoWriteTool, _merge_todos, parse_input,
)


@pytest.mark.parametrize("allocated", [True, False], ids=["allocated-ID", "same-label-merge"])
def test_declared_origin_supports_completing_every_actual_task(tmp_path, allocated):
    if allocated:
        submitted = {"todos": [{"content": "Verify", "status": "pending", "activeForm": "Verifying"}]}
        with patch("tools.todo_write_tool.types.uuid4", return_value=SimpleNamespace(hex="12345678abcdef")):
            current = parse_input(submitted).todos
        history = [msg_asst_use("create", "TodoWrite", submitted),
                   msg_tool("create", "TodoWrite", TodoWriteTool.map_tool_result_to_content(TodoWriteOutput(new_todos=current)))]
    else:
        old = [item("a", "Verify"), item("b", "Verify")]
        update = [item("a", "Verify")]
        update[0].active_form = "Verifying the first result"
        current = _merge_todos(old, update)
        history = event("initial", old, old) + event("merge", update, current, merge=True)
    history.insert(0, msg_user("Complete every currently pending task by its actual ID"))
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    projection = project(history, region_end=len(history), params=production_params(), view_path=view)
    line = next(line for line in projection.text.splitlines() if line.startswith("[TODO]") and "source=#" in line)
    ref = parse_read_refs(line)[0]
    content = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=ref.offset, limit=ref.limit))
    records = _payload(content)
    assert records is not None
    ids = {record["id"] for record in records if record["status"] in ("pending", "in_progress")}
    assert ids == {task.id for task in current}
    submitted = [replace(task, status="completed") for task in current if task.id in ids]
    assert all(task.status == "completed" for task in _merge_todos(current, submitted))
    assert projection.seeds.todo_active_count == len(current)
    if not allocated:
        assert projection.seeds.todos == ("[pending] Verify（×2）",)


@pytest.mark.parametrize("field,value", [
    ("id", "different"), ("content", "Verify" + "x" * 200),
    ("activeForm", "Changed continuation"), ("output", "Evidence"), ("extra", "Fact"),
])
def test_changed_active_fact_uses_the_observed_origin(field, value):
    task = item("a", "Verify" + "x" * 190)
    observed = task.to_dict()
    observed[field] = value
    text = "<todo_list>" + json.dumps([observed]) + "</todo_list>"
    history = [msg_asst_use("write", "TodoWrite", {"todos": [task.to_dict()]}), msg_tool("write", "TodoWrite", text)]
    assert latest_todo_snapshot(history).backing == 1


def test_identical_active_fields_keep_the_existing_input_origin():
    task = item("a", "Verify")
    observed = task.to_dict()
    submitted = dict(observed)
    submitted.pop("output", None)
    submitted["active_form"] = submitted.pop("activeForm")
    history = [msg_asst_use("write", "TodoWrite", {"todos": [submitted]}),
               event("unused", [], [task])[1]]
    history[1]["content"][0]["tool_use_id"] = "write"
    assert latest_todo_snapshot(history).backing == 0


def test_empty_content_does_not_turn_a_pending_entry_into_zero_tasks():
    history = [msg_asst_use("write", "TodoWrite", {"todos": [{"content": " ", "status": "pending"}]}),
               msg_tool("write", "TodoWrite", "ok")]
    snapshot = latest_todo_snapshot(history)
    assert snapshot.active_count == 1
    assert snapshot.items == ()
