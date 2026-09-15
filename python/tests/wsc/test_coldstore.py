"""冷层与 expand 句柄测试：无损往返、未知句柄不静默降级、gzip 落盘。"""

from __future__ import annotations

import pytest

from synaptic.coldstore import (
	ColdStore,
	branch_handle,
	node_group_handle,
	node_handle,
	parse_handle,
)


def test_handle_parsing_roundtrip():
	assert parse_handle(branch_handle("B12")) == ("branch", "B12")
	assert parse_handle(node_handle(7)) == ("node", "7")
	assert parse_handle("weird") == ("unknown", "weird")


def test_expand_returns_byte_identical_originals():
	cs = ColdStore(session="s1")
	cs.put_nodes([(1, "原文一", {"kind": "tool_result"}), (2, "原文二\n带换行", {})])
	cs.bind(branch_handle("B1"), (1, 2))
	assert cs.expand(branch_handle("B1")) == ("原文一", "原文二\n带换行")


def test_unknown_handle_raises_instead_of_silently_degrading():
	cs = ColdStore()
	with pytest.raises(KeyError):
		cs.expand(branch_handle("nope"))
	assert cs.expand_loose(branch_handle("nope")) == ()


def test_missing_node_raises():
	cs = ColdStore()
	cs.bind(branch_handle("B2"), (9,))
	with pytest.raises(KeyError):
		cs.expand(branch_handle("B2"))


def test_group_node_handle_expands_all_originals():
	cs = ColdStore(session="group")
	cs.put_nodes([(1, "原文一", {}), (2, "原文二", {})])
	handle = node_group_handle((1, 2))
	cs.bind(handle, (1, 2))
	assert handle == "node://1,2"
	assert cs.expand(handle) == ("原文一", "原文二")


def test_gzip_roundtrip_preserves_handles_and_texts(tmp_path):
	cs = ColdStore(session="sess-x")
	cs.put_nodes([(3, "abc", {"kind": "tool_use"})])
	cs.bind(node_handle(3), (3,))
	path = tmp_path / "cold" / "sess-x.jsonl.gz"
	n = cs.write(path)
	assert n > 0 and path.is_file()

	back = ColdStore.read(path)
	assert back.session == "sess-x"
	assert back.expand(node_handle(3)) == ("abc",)
	assert back.meta[3]["kind"] == "tool_use"


def test_to_json_is_sorted_and_stable():
	cs = ColdStore(session="s")
	cs.put_nodes([(2, "b", {}), (1, "a", {})])
	cs.bind(node_handle(2), (2,))
	cs.bind(node_handle(1), (1,))
	j1 = cs.to_json()
	j2 = ColdStore.from_json(j1).to_json()
	assert j1 == j2
	assert list(j1["texts"].keys()) == sorted(j1["texts"].keys())
