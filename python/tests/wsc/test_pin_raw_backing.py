"""PIN summaries do not replace the original evidence behind a selected node."""
from synaptic.coldstore import node_handle
from synaptic.project import project
from synaptic.types import WscParams
from tests.wsc._fixtures import msg_asst_use, msg_tool, msg_user
from tests.wsc._recovery_contract import parse_read_refs
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers


def test_short_pinned_error_retains_full_original_backing():
    messages = [msg_user("Investigate this failure"),
                msg_asst_use("r", "Read", {"path": "src/a.py"}),
                msg_tool("r", "Read", "PermissionError: denied\nrequest_id=case-17", is_error=True)]
    projection = project(messages, region_end=3, params=WscParams())
    node = projection.graph.node(2)
    assert node.tokens <= 48 and node.idx in projection.seeds.pin_nodes
    assert node.idx in projection.result.hot.kept_nodes
    assert node.text not in projection.text
    assert projection.cold.expand(node_handle(node.idx)) == (node.text,)


def test_short_pinned_todo_retains_its_original_fields():
    messages = [msg_user("Implement the pending task"),
                msg_asst_use("t", "TodoWrite", {"todos": [{"content": "Build", "status": "pending", "activeForm": "Building release"}]})]
    projection = project(messages, region_end=2, params=WscParams())
    node = projection.graph.node(1)
    assert node.tokens <= 48 and node.idx in projection.seeds.pin_nodes
    assert node.idx in projection.result.hot.kept_nodes
    assert node.text not in projection.text
    assert projection.cold.expand(node_handle(node.idx)) == (node.text,)


def test_missing_error_detail_can_be_recovered_from_a_published_read(tmp_path):
    from dataclasses import replace

    messages = [msg_user("Investigate this failure"),
                msg_asst_use("r", "Read", {"path": "src/a.py"}),
                msg_tool("r", "Read", "PermissionError: denied\nrequest_id=case-17", is_error=True)]
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    projection = project(messages, region_end=3, params=replace(WscParams(), handle_style="read"), view_path=view)
    assert "case-17" not in projection.text
    entrances = parse_read_refs(projection.text)
    assert entrances, "PIN summary has no original-evidence entrance"
    entrance = entrances[0]
    text = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=entrance.offset, limit=entrance.limit))
    assert text == projection.graph.node(2).text
    assert "request_id=case-17" in text


def test_an_error_already_fully_shown_does_not_add_a_duplicate_origin():
    messages = [msg_user("Investigate this failure"),
                msg_asst_use("r", "Read", {"path": "src/a.py"}),
                msg_tool("r", "Read", "PermissionError: denied", is_error=True)]
    projection = project(messages, region_end=3, params=WscParams())
    assert projection.graph.node(2).text in projection.text
    assert "source=#2" not in projection.text


def test_pending_todo_can_recover_fields_omitted_from_the_summary(tmp_path):
    from dataclasses import replace

    messages = [msg_user("Implement the pending task"),
                msg_asst_use("t", "TodoWrite", {"todos": [{"content": "Build", "status": "pending", "activeForm": "Building release"}]})]
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    projection = project(messages, region_end=2, params=replace(WscParams(), handle_style="read"), view_path=view)
    assert "Building release" not in projection.text
    entrances = parse_read_refs(projection.text)
    assert entrances, "TODO summary has no full-snapshot entrance"
    entrance = entrances[0]
    text = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=entrance.offset, limit=entrance.limit))
    assert text == projection.graph.node(1).text
    assert "Building release" in text
