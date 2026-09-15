"""证据 DAG 构建测试：节点分类、四类边、失败归因、确定性。"""

from __future__ import annotations

from synaptic.graph import build_graph, graph_digest
from synaptic.types import (
	EDGE_ERR,
	EDGE_FILE,
	EDGE_SEQ,
	EDGE_USE,
	KIND_ASST_TEXT,
	KIND_TOOL_RESULT,
	KIND_TOOL_USE,
	KIND_USER,
)
from wsc._fixtures import SRC, msg_asst_use, msg_tool, msg_user, synth_session


def test_node_kinds_and_tool_classification():
	g = build_graph(synth_session(turns=5))
	kinds = {n.kind for n in g.nodes}
	assert KIND_USER in kinds and KIND_TOOL_USE in kinds and KIND_TOOL_RESULT in kinds
	assert KIND_ASST_TEXT in kinds

	reads = [n for n in g.nodes if n.tool_name == "Read" and n.kind == KIND_TOOL_RESULT]
	assert reads and all(n.read_only is False for n in reads)  # 结果节点自身不可重放
	use_nodes = [n for n in g.nodes if n.kind == KIND_TOOL_USE and n.tool_name == "Read"]
	assert use_nodes and all(n.read_only for n in use_nodes)
	edits = [n for n in g.nodes if n.tool_name == "Edit" and n.kind == KIND_TOOL_USE]
	assert edits and all(n.is_write for n in edits)


def test_all_four_edge_kinds_present():
	g = build_graph(synth_session(turns=5, error_turn=3))
	kinds = {e.kind for e in g.edges}
	assert {EDGE_SEQ, EDGE_USE, EDGE_FILE}.issubset(kinds), kinds
	assert EDGE_ERR in kinds, "失败结果未连到后续同文件调用"


def test_error_node_records_signature_and_attribution():
	g = build_graph(synth_session(turns=5, error_turn=3))
	errs = [n for n in g.nodes if n.is_error]
	assert errs, "合成会话里有 is_error=True 的 tool_result，未被识别"
	assert any("AssertionError" in n.error_sig or "FAILED" in n.error_sig for n in errs)
	err_node = errs[0]
	assert err_node.refs, "失败现场没有抽出文件引用，err 边无从建立"
	assert g.outgoing(err_node.idx, EDGE_ERR)


def test_use_edge_links_call_to_result_by_id():
	msgs = [
		msg_user("go"),
		msg_asst_use("u1", "Read", {"path": SRC}),
		msg_tool("u1", "Read", "content"),
	]
	g = build_graph(msgs)
	assert g.by_use_id == {"u1": 1}
	assert g.outgoing(1, EDGE_USE) == (2,)
	assert g.incoming(2, EDGE_USE) == (1,)


def test_bare_exit_code_gets_semantic_prefix():
	msgs = [
		msg_user("go"),
		msg_asst_use("c1", "Bash", {"command": "make"}),
		msg_tool("c1", "Bash", "output\nexit code 255", is_error=True),
	]
	g = build_graph(msgs)
	node = g.node(2)
	assert node is not None and node.error_sig, "退出码未被抽成签名"
	assert not node.error_sig.isdigit(), f"裸数字签名未加语义前缀: {node.error_sig}"


def test_graph_is_deterministic():
	m = synth_session(turns=5)
	assert graph_digest(build_graph(m)) == graph_digest(build_graph(m))


def test_command_paths_extracted_from_bash_readonly_whitelist():
	msgs = [
		msg_user("go"),
		msg_asst_use("b1", "Bash", {"command": "grep -rn proxy src/auth.ts"}),
		msg_tool("b1", "Bash", "src/auth.ts:120: proxy"),
	]
	g = build_graph(msgs)
	use = g.node(1)
	assert use is not None and use.read_only and use.replay_cmd.startswith("grep")
	assert SRC in use.refs
