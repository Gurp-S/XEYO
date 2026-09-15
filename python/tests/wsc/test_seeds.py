"""种子提取测试：目标 / 约束 / TODO 当前态 / 未解决错误 / PIN 路径。"""

from __future__ import annotations

from synaptic.filestate import build_file_states
from synaptic.graph import build_graph
from synaptic.seeds import (
	_unresolved_error_nodes,
	collect_seeds,
	extract_constraints,
	harvest_needles,
)
from wsc._fixtures import (
	CONSTRAINT,
	msg_asst_text,
	msg_asst_use,
	msg_tool,
	msg_user,
	synth_session,
)


def _seeds(msgs):
	g = build_graph(msgs)
	return g, collect_seeds(g, msgs, build_file_states(g, msgs))


def test_extract_constraints_keeps_original_sentence():
	cs = extract_constraints("先看代码。不能修改 API 协议，必须保持 v1 兼容。然后跑测试。")
	# 约束句按句末标点切分，句内逗号不切——原句必须整句保留
	assert any("不能修改 API 协议" in c and "必须保持 v1 兼容" in c for c in cs)
	assert not any("先看代码" in c for c in cs)
	assert not any("然后跑测试" in c for c in cs)


def test_goal_and_constraint_reach_seeds():
	g, s = _seeds(synth_session(turns=6))
	assert s.original_task.startswith("修复登录超时")
	assert any(CONSTRAINT in c and "不能修改 API 协议" in c for c in s.constraints)


def test_engine_injected_resume_is_not_treated_as_user_intent():
	msgs = [
		msg_user("修复登录超时"),
		msg_asst_text("ok"),
		msg_user("[Resume] The user asked to continue an interrupted turn. Continue the unfinished work."),
		msg_asst_text("继续"),
	]
	_, s = _seeds(msgs)
	assert s.original_task.startswith("修复登录超时")
	# 引擎注入文本不得被读成目标或约束（规则 1 后它们在热层里没有任何位置）
	assert not any("[Resume]" in c for c in s.constraints)
	assert "[Resume]" not in s.goal


def test_only_latest_todo_state_counts():
	msgs = [msg_user("go")]
	msgs.append(msg_asst_use("t1", "TodoWrite", {"todos": [{"content": "旧任务A", "status": "pending"}]}))
	msgs.append(msg_tool("t1", "TodoWrite", "ok"))
	msgs.append(msg_asst_text("progress"))
	msgs.append(
		msg_asst_use("t2", "TodoWrite", {"todos": [{"content": "新任务B", "status": "pending"}]})
	)
	msgs.append(msg_tool("t2", "TodoWrite", "ok"))
	_, s = _seeds(msgs)
	assert any("新任务B" in t for t in s.todos)
	assert not any("旧任务A" in t for t in s.todos), "历史 TodoWrite 快照被当成现存任务"


def test_unresolved_error_survives_an_unrelated_later_success():
	"""一条 grep 提到同一文件，不等于那个失败的测试已经过了。"""
	g = build_graph(synth_session(turns=8, error_turn=4))
	unresolved = _unresolved_error_nodes(g)
	assert unresolved, "失败测试被「同文件成功结果」误判为已解决"
	assert any(g.nodes[i].is_error for i in unresolved)


def test_error_is_resolved_by_explicit_success_evidence():
	msgs = [
		msg_user("修超时"),
		msg_asst_use("b1", "Bash", {"command": "npm test -- src/auth.ts"}),
		msg_tool("b1", "Bash", "FAILED: 1 failed", is_error=True),
		msg_asst_use("b2", "Bash", {"command": "npm test -- src/auth.ts"}),
		msg_tool("b2", "Bash", "10 passed, 0 failed"),
	]
	g = build_graph(msgs)
	assert _unresolved_error_nodes(g) == [], "出现明确成功标记后仍判为未解决"


def test_error_without_success_marker_stays_unresolved():
	msgs = [
		msg_user("修超时"),
		msg_asst_use("b1", "Bash", {"command": "npm test -- src/auth.ts"}),
		msg_tool("b1", "Bash", "FAILED: 1 failed", is_error=True),
		msg_asst_use("b2", "Bash", {"command": "npm test -- src/auth.ts"}),
		msg_tool("b2", "Bash", "no output"),
	]
	g = build_graph(msgs)
	assert _unresolved_error_nodes(g), "缺少成功证据却判为已解决"


def test_needles_harvested_from_region_only():
	"""region_end 必须真的裁剪 —— 否则尾部逐字保留的信息会虚高存活率。"""
	g = build_graph(synth_session(turns=8, error_turn=4))
	full = harvest_needles(g, {})
	tiny = harvest_needles(g, {}, region_end=1)
	assert len(full["error_sig"]) >= 1
	assert tiny["error_sig"] == (), "区域裁剪没生效，尾部错误针仍被收割"
	# 目标在 idx 0，两种口径都必须包含它
	assert tiny["user"] == full["user"]


def test_pin_paths_include_stale_and_error_sites():
	g, s = _seeds(synth_session(turns=5, error_turn=4))
	assert s.pin_paths, "没有任何 PIN 路径"
	assert any("auth" in p for p in s.pin_paths)
	assert any(t["kind"] == "pin_path" for t in s.trace)


def test_seed_trace_explains_every_seed():
	_, s = _seeds(synth_session(turns=6, error_turn=3))
	kinds = {t["kind"] for t in s.trace}
	assert {"goal", "constraint", "unresolved_error"}.issubset(kinds), kinds
