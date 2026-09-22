"""**错误卡的句柄必须能取回失败输出本身**（可恢复性守卫）。

事故形态（2026-09-21 探针实测，1255 消息真实会话）：卡片以"尝试单元"为单位，而
部分被剪的典型形状恰好是**调用被剪、失败结果没被剪** ⇒ 旧实现只认领被剪成员
（卡 `B29 nodes=(29,)`，失败文本在 30）⇒ `cold.expand("branch://B29")` 回的是
**命令行**，不是那条报错。抽样 8 张错误卡，展开含失败原文 **0/8**。

为什么一直没人发现：`test_invariants::test_every_pruned_node_has_a_cold_handle` 只遍历
**被剪节点**，而那个失败结果节点压根没被剪 ⇒ 它不在任何检查域里。守卫是绿的，
承诺却是空的——这比缺测试更危险，因为它提供"已验过"的错觉。
"""

from __future__ import annotations

from synaptic.graph import EDGE_USE, build_graph
from synaptic.prune import build_cards
from synaptic.project import default_params
from tests.wsc._fixtures import msg_asst_text, msg_asst_use, msg_tool, msg_user

FAIL_TEXT = "AssertionError: expected 1000 got 3000\nPROXY_OVERRIDE_MARKER"


def _session():
	return [
		msg_user("修复登录超时"),
		msg_asst_use("c1", "Read", {"path": "src/auth.ts", "offset": 1, "limit": 40}),
		msg_tool("c1", "Read", "source body " + ("x" * 400)),
		msg_asst_use("c2", "Bash", {"command": "npm test -- src/auth.ts"}),
		msg_tool("c2", "Bash", FAIL_TEXT, is_error=True),
		msg_asst_text("第 1 轮：先看超时配置"),
	]


def _cards_with_partial_prune():
	"""只剪"调用"节点、保留它的失败结果 ⇒ 复现部分被剪形状。"""
	msgs = _session()
	graph = build_graph(msgs)
	call = next(n for n in graph.nodes if n.kind == "tool_use" and n.tool_name == "Bash")
	result = next(d for d in graph.outgoing(call.idx, EDGE_USE) if graph.node(d).is_error)
	cards = build_cards(graph, (call.idx,), default_params("Medium+"), region_end=len(msgs))
	card = next((c for c in cards if c.error_sig), None)
	return card, result, call, msgs, graph


def test_error_card_handle_covers_the_failure_output() -> None:
	card, result, _call, _msgs, graph = _cards_with_partial_prune()
	assert card is not None, "部分被剪的失败单元没建出错误卡"
	assert result in card.nodes, (
		f"错误卡句柄只指向调用 {card.nodes}，不含失败结果 {result} ⇒ 展开拿不回报错原文"
	)


def test_expand_of_error_card_contains_verbatim_failure() -> None:
	card, _result, _call, _msgs, graph = _cards_with_partial_prune()
	# `ColdStore.expand(branch://X)` 返回的就是这些节点的原文（project.py 按 c.nodes 绑定），
	# 所以按同一集合拼文本即等价于真实取回结果。
	joined = "\n".join(graph.node(i).text for i in card.nodes if graph.node(i) is not None)
	assert "PROXY_OVERRIDE_MARKER" in joined, "错误卡展开后不含失败原文"


def test_no_error_card_loses_its_error_node_from_the_cold_store() -> None:
	"""整会话级：所有错误卡的节点并集必须覆盖它们各自摘要所依据的失败节点。"""
	msgs = _session()
	graph = build_graph(msgs)
	from synaptic.types import KIND_TOOL_RESULT

	pruned = tuple(
		n.idx for n in graph.nodes if n.kind in (KIND_TOOL_RESULT, "tool_use") and n.idx != 4
	)
	cards = build_cards(graph, pruned, default_params("Medium+"), region_end=len(msgs))
	err_nodes = {n.idx for n in graph.nodes if n.is_error and n.error_sig}
	bound = {i for c in cards for i in c.nodes}
	covered_by_branch = {i for i in err_nodes if i in bound}
	assert err_nodes, "夹具里没有失败节点"
	assert covered_by_branch == err_nodes, (
		f"失败节点 {sorted(err_nodes - covered_by_branch)} 既没进卡也没进句柄 ⇒ 永久不可取回"
	)
