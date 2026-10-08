"""覆盖判据的证据面契约：结果节点必须保留**调用声明的执行范围**。

现场（sess_mux0q86a_ea2kv9，真实 transcript，777 条消息）：
``error_covered_by`` 在 15 条错误上闭合 0 条；把口径放宽成"同工具 + 文本成功标记"
后立刻在两条错误上误闭——因为 ``refs`` 只从结果正文抽取，而被拒结果的正文
（``write failed: path_denied``）一个路径都不含，判据无证据可用。

本文件锁死两件事：
1. 结果节点上有 ``scope_paths``（声明范围）可作证据，但不冒充 ``arg_paths`` 身份位；
2. **无证据 ⇒ 不闭合**（fail-closed）：目标不同的成功写不得抹掉被拒的失败。
"""

from __future__ import annotations

from synaptic.freshness import error_covered_by
from synaptic.graph import build_graph
from wsc._fixtures import msg_asst_use, msg_tool, msg_user


def _denied_then_other_target() -> list[dict]:
	"""被拒的写（正文无路径）+ 之后对**另一个**文件成功写。"""
	return [
		msg_user("修登录超时"),
		msg_asst_use("w1", "Write", {"path": "src/legacy.ts", "content": "x"}),
		msg_tool("w1", "Write", "write failed: path_denied", is_error=True),
		msg_asst_use("w2", "Write", {"path": "src/auth.ts", "content": "y"}),
		msg_tool("w2", "Write", "File created successfully at: src/auth.ts"),
	]


def test_denied_result_keeps_declared_scope_without_claiming_identity() -> None:
	graph = build_graph(_denied_then_other_target())
	denied = graph.node(2)
	assert denied is not None and denied.is_error, "被拒结果没被判成错误节点"
	assert denied.scope_paths, "调用声明的执行范围没进证据面（判据将无证据可用）"
	assert denied.arg_paths == (), "结果节点不得冒充卡面身份位"


def test_no_evidence_means_no_closure_across_targets() -> None:
	"""目标不相交时不得闭合：判据宁可多留一条未解错误。"""
	graph = build_graph(_denied_then_other_target())
	denied = graph.node(2)
	assert error_covered_by(graph, denied, len(graph.nodes)) is None


def _bash(command: str) -> object:
	msgs = [
		msg_user("跑契约"),
		msg_asst_use("b1", "Bash", {"command": command}),
		msg_tool("b1", "Bash", "1 failed, 43 passed in 11.06s"),
	]
	return build_graph(msgs).node(2)


def test_bash_scope_is_declared_range() -> None:
	"""命令点名的**文件**路径进声明范围（Bash 现场的证据面）。"""
	res = _bash("py -3.11 -m pytest python/tests/wsc/test_scope_paths_evidence.py -q")
	assert res is not None and res.kind == "tool_result"
	assert res.scope_paths, "Bash 命令点名的文件路径没进声明范围"


def test_bash_directory_range_is_not_yet_representable() -> None:
	"""现状钉扎（待裁，非缺陷声明）：纯目录范围抽不出路径。

	``_PATH_RE`` 只匹配带扩展名的文件型 token，``pytest python/tests/wsc`` 因此
	``scope_paths == ()``。这是既存抽取口径（``textutil.extract_paths``），
	本次改动不动它——它同时喂 refs 全域索引，放宽的爆炸半径远超本契约。
	后果：**目录级 Bash 范围当前无证据可用 ⇒ 判据 fail-closed 不闭合**。
	"""
	res = _bash("py -3.11 -m pytest python/tests/wsc -q")
	assert res is not None
	assert res.scope_paths == (), "目录范围若已可表达，请更新本契约并复核判据"


_REAL_246 = (
	"=== 归属判定：wsc 那 10 条红，关掉我的块后是否照旧 ===\n"
	"FAILED tests/wsc/test_fold_gate_coverage.py::test_compacted_state_with_empty_summary_still_passes_theta_gate\n"
	"FAILED tests/wsc/test_fold_gate_coverage.py::test_measured_cooldown_is_set_after_a_gated_fold\n"
	"10 failed, 20 passed in 2.39s\n"
	"=== 我改的 size_prune 默认是否生效 ===\n"
	"XEYO_WSC_SIZE_PRUNE enabled by default = True"
)


def _failed_then_rerun(second_text: str) -> object:
	"""同一条命令：先失败，后重跑（正文由调用方给定）。"""
	cmd = "py -3.11 -m pytest python/tests/wsc/test_fold_gate_coverage.py -q"
	msgs = [
		msg_user("跑契约"),
		msg_asst_use("b1", "Bash", {"command": cmd}),
		msg_tool("b1", "Bash", _REAL_246, is_error=True),
		msg_asst_use("b2", "Bash", {"command": cmd}),
		msg_tool("b2", "Bash", second_text),
	]
	return build_graph(msgs)


def test_failed_rerun_must_not_cover_an_earlier_failure() -> None:
	"""真实正文回归（sess_mux0q86a_ea2kv9 的 #246）。

	那条重跑的原始记录 ``is_error=False``（退出码取自**最后一段**命令），正文却是
	``10 failed, 20 passed``。``passed`` 命中成功标记 ⇒ 判据拿失败覆盖失败（#242）。
	覆盖者必须自查正文失败证据。
	"""
	graph = _failed_then_rerun(_REAL_246)
	err = graph.node(2)
	assert err is not None and err.is_error
	assert error_covered_by(graph, err, len(graph.nodes)) is None, (
		"失败重跑不得充当覆盖者（整调用 is_error 只看最后一段退出码）"
	)


def test_successful_rerun_still_covers() -> None:
	"""正控：真成功的同命令重跑仍应闭合（防判据被改成永假）。"""
	graph = _failed_then_rerun(
		"tests/wsc/test_fold_gate_coverage.py ........ 30 passed in 2.10s"
	)
	err = graph.node(2)
	assert err is not None and err.is_error
	assert error_covered_by(graph, err, len(graph.nodes)) is not None, (
		"真成功的同命令重跑应当闭合"
	)
