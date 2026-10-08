"""段级失败证据契约：整调用 ``is_error`` 只看**最后一段**命令的退出状态。

现场（sess_mux0q86a_ea2kv9 的 row 244/246）：正文是
``FAILED …::test_x`` + ``10 failed, 20 passed``，原始记录却是 ``is_error: false``
（``cmd1; cmd2`` 里失败在**中段**）⇒ ``[UNRESOLVED]`` 对段级失败失明。

口径由影子实测背书（``python/evals/wsc_unresolved_gap.py`` 段级候选投影）：
宽口径 4 条命中含 1 条假阳，收窄为「行首独立成行」或「pytest 短摘要段头 + FAILED 行」
后 3/3 为真、假阳 0。本文件把该口径钉死，并锁住两条边界：
**只认 Bash**（其它工具常在引用失败文本）、**不撤销既有非零降格**。
"""

from __future__ import annotations

from synaptic.graph import build_graph
from wsc._fixtures import msg_asst_use, msg_tool, msg_user

_REAL_246 = (
	"=== 归属判定：wsc 那 10 条红，关掉我的块后是否照旧 ===\n"
	"FAILED tests/wsc/test_fold_gate_coverage.py::test_compacted_state_with_empty_summary_still_passes_theta_gate\n"
	"FAILED tests/wsc/test_fold_gate_coverage.py::test_measured_cooldown_is_set_after_a_gated_fold\n"
	"10 failed, 20 passed in 2.39s\n"
	"=== 我改的 size_prune 默认是否生效 ===\n"
	"XEYO_WSC_SIZE_PRUNE enabled by default = True"
)


def _result_nodes(name: str, text: str, *, command: str = "py -3.11 -m pytest x -q") -> object:
	"""一条 Bash/其它工具调用及其结果（``is_error`` 一律缺省为 ``False``，即原始记录口径）。"""
	msgs = [
		msg_user("跑契约"),
		msg_asst_use("t1", name, {"command": command}),
		msg_tool("t1", name, text, is_error=False),
	]
	return build_graph(msgs).node(2)


def test_segment_failure_is_recognised_by_the_engine() -> None:
	"""中段失败 + 末尾成功汇总：结果节点必须判成错误节点。"""
	res = _result_nodes("Bash", _REAL_246)
	assert res is not None and res.kind == "tool_result"
	assert res.is_error, "段级失败（10 failed, 20 passed）被整调用 is_error 掩盖了"


def test_true_success_stays_non_error() -> None:
	"""正控：真成功汇总不得被改装成永真判错。"""
	res = _result_nodes("Bash", "tests/wsc/test_fold_gate_coverage.py ........ 30 passed in 2.10s")
	assert res is not None and not res.is_error


def test_inline_mention_is_not_evidence() -> None:
	"""假阳防护：失败的**探针**把计数打印在行中，不算段级失败证据。

	这正是宽口径被否掉的那条影子命中。
	"""
	res = _result_nodes("Bash", "probe: baseline had 10 failed, 20 passed before my block")
	assert res is not None and not res.is_error


def test_summary_header_without_failed_item_is_not_evidence() -> None:
	"""有短摘要段头但没有 ``FAILED <nodeid>`` 行 ⇒ 不算证据。"""
	res = _result_nodes("Bash", "short test summary info\n2 errors in 0.31s")
	assert res is not None and not res.is_error


def test_non_bash_quoting_a_failure_is_not_evidence() -> None:
	"""口径只在 Bash：其它工具的结果正文常在**引用**失败文本。"""
	res = _result_nodes("Edit", "short test summary info\nFAILED x.py::test_y\n10 failed, 20 passed")
	assert res is not None and not res.is_error


def test_normal_nonzero_demotion_survives() -> None:
	"""既有非零降格不被新分支破坏：``git diff`` 退出码 1 + diff 正文仍是正常结果。"""
	res = _result_nodes(
		"Bash",
		"Chunk ID: 1\nWall time: 0.1s\n退出码 1\nOutput:\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b",
		command="git diff -- x.py",
	)
	assert res is not None and not res.is_error
