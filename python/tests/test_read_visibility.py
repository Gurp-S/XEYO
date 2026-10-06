from types import SimpleNamespace

from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput
from tools.fileio.read_visibility import sync_read_visibility
from prompt.fence import fence_tool_output


def test_equivalent_range_saves_body_and_retained_body_still_dedups(tmp_path):
	path = tmp_path / "a.txt"
	path.write_text("payload line\n" * 200, encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	first = tool.call(ReadInput(file_path=str(path)))
	body = tool.map_tool_result_to_content(first)
	registry = SimpleNamespace(_tools={"Read": tool})
	sync_read_visibility(registry, [{"role": "tool", "content": fence_tool_output("Read", body)}])
	second = tool.call(ReadInput(file_path=str(path), offset=0, limit=2000))
	assert second.type == "file_unchanged"
	assert len(tool.map_tool_result_to_content(second)) < len(body) / 10


def test_folded_or_truncated_view_can_be_reread_without_losing_write_state(tmp_path):
	path = tmp_path / "a.txt"
	path.write_text("alpha\nbeta\n", encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	first = tool.call(ReadInput(file_path=str(path)))
	entry = tool._read_state.get(str(path))
	registry = SimpleNamespace(_tools={"Read": tool})
	sync_read_visibility(registry, [{"role": "assistant", "content": "summary: a.txt"}])
	assert tool._read_state.get(str(path)) is entry
	assert entry.content == "alpha\nbeta\n" and entry.content_known
	assert tool.call(ReadInput(file_path=str(path))).content == first.content
	body = tool.map_tool_result_to_content(first)
	sync_read_visibility(registry, [{"role": "tool", "content": body[:5]}])
	assert tool.call(ReadInput(file_path=str(path))).type == "text"


def test_sidecar_and_changed_file_never_return_unchanged_stub(tmp_path):
	path = tmp_path / "a.txt"
	path.write_text("original", encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	tool.call(ReadInput(file_path=str(path)))
	meta = tool._read_state.snapshot_meta()
	tool._read_state.clear()
	tool._read_state.load_meta(meta)
	assert tool.call(ReadInput(file_path=str(path))).type == "text"
	path.write_text("changed", encoding="utf-8")
	import os
	os.utime(path, (1, 1))
	assert tool.call(ReadInput(file_path=str(path))).content == "changed"


def test_c0_truncated_body_is_not_a_dedup_reference(tmp_path):
	from engine.compact import project
	path = tmp_path / "big.txt"
	path.write_text("still needed API detail\n" * 600, encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	first = tool.call(ReadInput(file_path=str(path)))
	body = tool.map_tool_result_to_content(first)
	source = [{"role": "assistant", "content": [{"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": str(path)}}]},
	          {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "r", "content": body}]}]
	projected = project(source, cwd=tmp_path)
	assert projected[1]["content"][0]["content"] != body
	sync_read_visibility(SimpleNamespace(_tools={"Read": tool}), projected)
	assert tool.call(ReadInput(file_path=str(path))).type == "text"


def test_default_read_keeps_existing_large_file_guard(tmp_path):
	import pytest
	path = tmp_path / "large.txt"
	path.write_text("small line\n" * 30000, encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	with pytest.raises(RuntimeError, match="maximum allowed size"):
		tool.call(ReadInput(file_path=str(path)))
	assert tool.call(ReadInput(file_path=str(path), limit=2000)).type == "text"


def test_non_read_copy_cannot_substitute_for_visible_read(tmp_path):
	path = tmp_path / "a.txt"
	path.write_text("required interface\n", encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	body = tool.map_tool_result_to_content(tool.call(ReadInput(file_path=str(path))))
	registry = SimpleNamespace(_tools={"Read": tool})
	# 相同文本的 Bash 结果不是先前 Read 的可见视图。
	sync_read_visibility(registry, [{"role": "tool", "name": "Bash", "content": body}])
	assert tool.call(ReadInput(file_path=str(path))).type == "text"


def test_internal_tool_identity_preserves_read_visibility(tmp_path):
	path = tmp_path / "a.txt"
	path.write_text("required interface\n", encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))
	body = tool.map_tool_result_to_content(tool.call(ReadInput(file_path=str(path))))
	registry = SimpleNamespace(_tools={"Read": tool})
	sync_read_visibility(registry, [
		{"role": "assistant", "content": [{"type": "tool_use", "id": "r", "name": "Read"}]},
		{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "r", "content": body}]},
	])
	assert tool.call(ReadInput(file_path=str(path))).type == "file_unchanged"
