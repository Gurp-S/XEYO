"""Observed TODO state exercises real projection, immutable prefix and cold Read."""

from memory.wsc_projection import production_params
from synaptic.coldstore import node_handle
from synaptic.project import project
from tests.wsc._fixtures import msg_user
from tests.wsc._recovery_contract import parse_read_refs
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers
from tests.wsc.test_todo_snapshot import event, item
from tools.todo_write_tool.todo_write_tool import _merge_todos


def test_merge_missing_task_is_hot_and_full_output_is_readable(tmp_path):
    old = [item("a", "Implement"), item("b", "Verify")]
    old[1].active_form = "Running offline verification"
    update = [item("a", "Implement", "completed")]
    messages = [msg_user("Finish the implementation and verification")] + event("initial", old, old) + event("merge", update, _merge_todos(old, update), merge=True)
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    projected = project(messages, region_end=len(messages), params=production_params(), view_path=view)
    assert projected.seeds.todos == ("[pending] Verify",)
    assert "[pending] Verify" in projected.text
    assert 4 in projected.seeds.pin_nodes
    raw = projected.graph.node(4).text
    assert projected.cold.expand(node_handle(4)) == (raw,)
    results = [_strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=ref.offset, limit=ref.limit)) for ref in parse_read_refs(projected.text)]
    assert any(raw in result and "Running offline verification" in result for result in results)


def test_current_state_fix_preserves_previously_published_prefix(tmp_path):
    old = [item("a", "Implement"), item("b", "Verify")]
    update = [item("a", "Implement", "completed")]
    messages = [msg_user("Finish the work")] + event("initial", old, old)
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    before = project(messages, region_end=len(messages), params=production_params(), view_path=view)
    old_view = before.cold.render_text_view()[0]
    old_bindings = dict(before.cold.handles)
    messages += event("merge", update, _merge_todos(old, update), merge=True)
    after = project(messages, region_end=len(messages), params=production_params(), view_path=view, prev=before.state, cold=before.cold)
    assert after.text.startswith(before.text)
    assert after.cold.render_text_view()[0].startswith(old_view)
    assert all(after.cold.handles[h] == nodes for h, nodes in old_bindings.items())
    assert after.seeds.todos == ("[pending] Verify",)
