"""失败原因分类：每条都必须自带"能证明什么/不能证明什么"，且不得合并成综合结论。

另有一道覆盖率门：规则集里每一条规则都必须能走到"可能原因"清单
（映射、专门通路，或写明理由的豁免），否则它产出的事实在这份报告上是隐形的。"""

from __future__ import annotations

import json

from diagnostics import causes as _causes
from diagnostics.causes import (
	ACCEPT_MISSING,
	CONSTRAINT_FOLDED,
	PROVIDER_FAILURE,
	SHAPE_REJECTED,
	SELF_REPORT_MISMATCH,
	ACTION_SKIPPED,
	CONTEXT_DROPPED,
	NOT_DETERMINED,
	PERMISSION_BLOCKED,
	PROJECTION_BROKEN,
	REPEATED_ERROR,
	primary,
)
from diagnostics.collect import ModelRequest, RunEvidence, ToolCall
from diagnostics.fault_split import attribute_fault
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, UNKNOWN, EvidenceRef, Finding
from session.persistence import transcript_path


def _finding(rule_id: str, boundary: str, *, detail: str = "", status: str = CONFIRMED_FAULT) -> Finding:
	return Finding(
		rule_id=rule_id,
		rule_version=1,
		phenomenon=f"{rule_id} 现象",
		boundary=boundary,
		component="测试组件",
		status=status,
		evidence=[EvidenceRef(source="audit", locator="audit.jsonl", ref_id="L7", detail=detail)],
		coverage_gap="测试夹具",
		allowed_conclusion="测试夹具",
	)


def _run(**over) -> RunEvidence:
	base = dict(session_id="s1", turn_id="t1")
	base.update(over)
	return RunEvidence(**base)


def _user_turn(text: str, shown_text: str, monkeypatch) -> None:
	transcript_path("s1").parent.mkdir(parents=True, exist_ok=True)
	transcript_path("s1").write_text(
		json.dumps({"id": "m1", "role": "user", "ts": 1.0, "content": text}, ensure_ascii=False) + "\n",
		encoding="utf-8",
	)
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": shown_text}]), "w.json"))


def _write_transcript(session_id: str, rows: list[dict]) -> None:
	path = transcript_path(session_id)
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = [json.dumps(r, ensure_ascii=False) for r in rows]
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _codes(verdict: dict) -> list[str]:
	return [c["code"] for c in verdict["causes"]]


def test_every_cause_states_its_limits() -> None:
	# 验收通过 + 无任何规则命中：这时才允许报"没有可核对的原因"
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 0, "locator": "p1.json"}])
	verdict = attribute_fault(run, [])
	assert primary(verdict["causes"])["code"] == NOT_DETERMINED
	for item in verdict["causes"]:
		assert item["proves"], item["code"]
		assert item["does_not_prove"], item["code"]
		assert item["party"] in {"engine", "model", "environment", "undetermined"}


def test_projection_break_becomes_its_own_cause() -> None:
	verdict = attribute_fault(_run(), [_finding("tool_pair_integrity", "adapter")])
	assert PROJECTION_BROKEN in _codes(verdict)
	head = primary(verdict["causes"])
	assert head["code"] == PROJECTION_BROKEN and head["party"] == "engine"
	assert head["evidence"], "原因必须能回到原始记录"
# --- 规则 → 原因 的覆盖率门 ------------------------------------------------- #

# 不经过 _RULE_CAUSES、另有专门通路的两条：写清楚，免得被当成漏映射。
_SPECIAL_PATH = {
	"tool_failure": "经 fault_split 的 tool_error_kinds 通路产出 tool_execution_error",
	"verifier": "经任务结局（accepted_fail / verifier_error）产出验收类原因",
}

# 刻意不进原因清单的规则，必须写理由。
_CAUSE_EXEMPT = {
	"no_turn_records": "本轮连自己的记录都读不出：它是缺项说明，不是一种失败类型",
}


def test_every_rule_reaches_the_cause_list_or_is_exempt_with_a_reason() -> None:
	"""新增一条规则却没人把它接进"可能原因"，等于这条规则在报告上是隐形的。"""
	from diagnostics import rules

	rule_ids = {r.rule_id for r in rules.RULES}
	mapped = {rule_id for _code, rule_id, _status in _causes._RULE_CAUSES}
	unclaimed = sorted(rule_ids - mapped - set(_SPECIAL_PATH) - set(_CAUSE_EXEMPT))
	assert unclaimed == [], f"这些规则产出的事实进不了原因清单：{unclaimed}"
	# 反向门：映射里不得有已经改名/删掉的规则 id —— 那样那条原因永远产不出。
	dangling = sorted(mapped - rule_ids)
	assert dangling == [], f"这些原因映射到已经不存在的规则：{dangling}"


def test_every_cause_code_is_fully_described() -> None:
	"""新增原因码时三张表都要齐：漏一条就会在报告里渲染成半句话。"""
	for code in _causes.CAUSE_LABEL:
		assert code in _causes._PROVES, code
		assert code in _causes._CAUSE_PARTY, code
		proves, not_proves = _causes._PROVES[code]
		assert proves and not_proves, code
	assert set(_causes.CAUSE_LABEL) == set(_causes._PROVES) == set(_causes._CAUSE_PARTY)


def test_rerouted_tool_call_becomes_its_own_cause() -> None:
	"""改道是执行层事实：它进原因清单，但不把责任判给任何一方。"""
	f = _finding("tool_routing", "tool_permission", detail="Bash→Glob dir doc/", status=UNKNOWN)
	verdict = attribute_fault(_run(), [f])
	entry = next((c for c in verdict["causes"] if c["code"] == "tool_action_rerouted"), None)
	assert entry is not None, verdict["causes"]
	assert entry["party"] == "undetermined"
	assert entry["evidence"][0]["detail"] == "Bash→Glob dir doc/"
	assert "不能把改道判成分发故障" in entry["does_not_prove"]


def test_repeated_error_cause_does_not_claim_a_shared_signature() -> None:
	"""原因句也不能说"同一错误签名反复出现"。

	与规则侧同一族（test_rules_calibration 第 18 条）：真实数据 58 条重复失败里 55 条的
	错误分类位是空的，审计也不带参数 ⇒ 那一组真正相同的只有工具名，把"读不出"写成
	一个签名取值就是凭空造区分。
	"""
	f = _finding("repeated_failure", "tool_permission", status=SUSPECTED_CAUSE)
	verdict = attribute_fault(_run(), [f])
	entry = next((c for c in verdict["causes"] if c["code"] == REPEATED_ERROR), None)
	assert entry is not None, verdict["causes"]
	assert "同一工具在窗口内反复失败" in entry["proves"]
	assert "只按工具名" in entry["proves"], "分类位为空这一形必须留在原因的说法里"
	assert "同一错误签名" not in entry["proves"]
	assert "死循环" in entry["does_not_prove"]
	assert "不能断言参数相同" in entry["does_not_prove"]

def test_confirmed_cause_survives_an_unknown_sibling_of_the_same_rule() -> None:
	"""同一条规则一边已确认、一边未定时，已确认那条原因不得被邻居顶掉。

	真实形状：tool_pair_integrity 既会报「投影结构坏了」（已确认、引擎定责），
	也会报「工作记忆里存着不成对的 tool_use」（未定）。规则集把已确认排在前面，
	旧实现按规则只记最后一个状态 ⇒ 未定的邻居把原因整条抹掉，
	而未定那条的证据还会挂到已确认的原因上。
	"""
	confirmed = _finding("tool_pair_integrity", "adapter", detail="invariant_errors:orphan_tool_results:1")
	sibling = _finding("tool_pair_integrity", "wsc_fold", detail="canonical_unpaired_tool_calls:2", status=UNKNOWN)
	verdict = attribute_fault(_run(), [confirmed, sibling])
	assert PROJECTION_BROKEN in _codes(verdict), verdict["causes"]
	entry = next(c for c in verdict["causes"] if c["code"] == PROJECTION_BROKEN)
	assert [e["detail"] for e in entry["evidence"]] == ["invariant_errors:orphan_tool_results:1"], (
		"未定邻居的证据不得挂到已确认的原因上"
	)

def test_unknown_only_rule_does_not_invent_a_confirmed_cause() -> None:
	"""反向：只有未定项时不得替这条规则产出已确认原因。"""
	sibling = _finding("tool_pair_integrity", "wsc_fold", detail="canonical_unpaired_tool_calls:2", status=UNKNOWN)
	verdict = attribute_fault(_run(), [sibling])
	assert PROJECTION_BROKEN not in _codes(verdict), verdict["causes"]



def test_constraint_loss_is_the_upstream_cause(monkeypatch) -> None:
	_user_turn("改完必须跑 pytest", "别的内容", monkeypatch)
	verdict = attribute_fault(
		_run(events=[]),
		[_finding("tool_pair_integrity", "adapter")],
	)
	# 上下文丢失排在结构破坏之前：越上游越能解释后面的现象
	assert _codes(verdict)[0] == CONTEXT_DROPPED
	assert verdict["responsibility"] == "engine"


def test_blocked_action_is_not_counted_as_skipped(monkeypatch) -> None:
	_user_turn("改完必须跑 pytest 再说完成", "改完必须跑 pytest 再说完成", monkeypatch)
	run = _run(
		permissions=[
			{"request_id": "apr", "kind": "permission.resolved", "tool_name": "Bash", "approved": False, "outcome": "user_decided", "line_no": 9}
		],
		transcript_rows=[
			{"id": "m2", "role": "assistant", "content": "已完成，测试通过", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [])
	codes = _codes(verdict)
	assert PERMISSION_BLOCKED in codes
	assert ACTION_SKIPPED not in codes, "被挡下不能同时算『没做』"
	# 引擎挡下动作是执行层事实；模型那句"测试通过"没有验收记录可对，
	# 就构不成"与验收不符"——没有记录就没有矛盾，只剩引擎这一方。
	assert verdict["responsibility"] == "engine"
	assert SELF_REPORT_MISMATCH not in codes, "无验收记录不得算成自述与验收不符"


def test_missing_verifier_is_a_cause_but_blames_nobody(monkeypatch) -> None:
	_user_turn("随便改点什么", "随便改点什么", monkeypatch)
	# 执行面得有记录，"没有可判定的验收记录"才是一句关于某次执行的话（零记录见下一条）
	run = _run(model_requests=[ModelRequest(model_request_id="r1", turn_id="t1")])
	verdict = attribute_fault(run, [])
	assert ACCEPT_MISSING in _codes(verdict)
	item = next(c for c in verdict["causes"] if c["code"] == ACCEPT_MISSING)
	assert item["party"] == "undetermined"
	assert "既不能判完成也不能判失败" in item["does_not_prove"]


def test_nothing_observed_is_not_called_missing_acceptance(monkeypatch) -> None:
	"""执行面上一条记录都没有时，主原因只能是"记录不足"，不能是一条关于验收的话。

	现场：只剩转录文件、审计里零行的会话 —— 真实数据 404 个会话里有 383 个是这个形状
	（审计尾窗没盖到；测试残渣 s1 也算一个，见 #61）。它们此前每一份都写
	「主原因：没跑验收…」，而同一份报告的缺项栏正在说 instruction_context/model_request
	超出采集窗口 —— 把"什么都没观察到"讲成了一个原因，还和自家缺项打架。
	轮次视图对同一件事早有裁定（「本轮无记录：只能报采集缺口，不能报原因」），这里补齐会话级。
	"""
	_user_turn("随便改点什么", "随便改点什么", monkeypatch)
	verdict = attribute_fault(
		_run(turn_id="", transcript_rows=[{"id": "m1", "role": "user", "content": "随便改点什么"}]),
		[],
	)
	assert primary(verdict["causes"])["code"] == NOT_DETERMINED
	assert ACCEPT_MISSING not in _codes(verdict)
	assert "只能报边界缺项，不能报原因" in verdict["cause_statement"]


def test_acceptance_cause_says_record_not_action() -> None:
	"""原因措辞说的是记录本，不是模型做没做：验收条目只由 CLI / 界面提交。

	diagnostics/pins.py::record_verifier 的调用方只有 __main__ 与 server 路由，引擎跑测试
	不会写这里 —— 「没跑验收」是把"没有条目"读成"没做"。
	"""
	item = _causes._entry(ACCEPT_MISSING, [])
	assert "没跑" not in item["label"] and "未执行" not in item["label"]
	assert "条目" in item["proves"]
	assert "不等于没跑验收" in item["does_not_prove"]
	# 同一句 overreach 在结局栏里也有一份：not_accepted 说的是记录栏，不是"模型没跑测试"
	from diagnostics.fault_split import OUTCOME_LABEL, OUTCOME_NOT_ACCEPTED

	assert "未执行" not in OUTCOME_LABEL[OUTCOME_NOT_ACCEPTED]
	assert "记录" in OUTCOME_LABEL[OUTCOME_NOT_ACCEPTED]


def test_self_reported_without_a_verifier_still_lacks_acceptance(monkeypatch) -> None:
	"""自述完成 + 零验收：缺的还是"可核对的验收记录"，而不是多出一条矛盾。"""
	_user_turn("随便改点什么", "随便改点什么", monkeypatch)
	run = _run(
		model_requests=[ModelRequest(model_request_id="r1", turn_id="t1")],
		transcript_rows=[
			{"id": "m2", "role": "assistant", "content": "已完成，测试通过", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [])
	codes = _codes(verdict)
	assert verdict["task_outcome"] == "self_reported_unverified"
	assert ACCEPT_MISSING in codes, "换了结局取值就不能顺手丢掉那条原因"
	assert SELF_REPORT_MISMATCH not in codes


def test_fallback_4xx_gets_its_own_cause_not_the_provider_one() -> None:
	"""被拒后降级重打要与 429/5xx 分成两个码：同一条规则下的两种形状，归属不同。"""
	verdict = attribute_fault(_run(), [
		_finding(
			"provider_stream_failure",
			"model_request",
			detail="model.finished status=protocol_fallback error_code=HTTP_400 attempt=1",
		)
	])
	codes = _codes(verdict)
	assert SHAPE_REJECTED in codes
	assert PROVIDER_FAILURE not in codes
	item = next(c for c in verdict["causes"] if c["code"] == SHAPE_REJECTED)
	assert item["party"] == "undetermined"
	# 措辞里必须带上这台量具的盲区：frozen_head 看不见换通道重打，读者才不会把它的
	# 沉默当成"前缀没变"（真实 2,086 个逻辑调用的 projection_id 全部只有一个取值）。
	assert "冻结前缀" in item["does_not_prove"]
	# 同一轮里既有 429 又有回退时，两个码要各留各的证据，不得合并成一条。
	both = attribute_fault(_run(), [
		_finding("provider_stream_failure", "model_request", detail="llm.failure status=429 attempt=1"),
		_finding("provider_stream_failure", "model_request", detail="model.finished status=protocol_fallback attempt=2"),
	])
	assert PROVIDER_FAILURE in _codes(both) and SHAPE_REJECTED in _codes(both)


def test_folded_out_gets_its_own_cause_and_a_different_next_step(monkeypatch) -> None:
	"""折叠移出要单独成码：下一步是复核这条该不该保留，不是去找别的边界。"""
	constraint = "改完必须跑 pytest"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": "无关"}]), "w.json"))
	run = _run(
		transcript_rows=[{"id": "m1", "role": "user", "line_no": 2, "content": constraint, "locator": "t.jsonl"}],
		working={"compact_cursor": 5, "locator": "w.json"},
	)
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "folded_out"
	assert verdict["responsibility"] == "engine"
	codes = _codes(verdict)
	assert CONSTRAINT_FOLDED in codes and CONTEXT_DROPPED not in codes
	item = next(c for c in verdict["causes"] if c["code"] == CONSTRAINT_FOLDED)
	assert "折叠是错的" not in item["proves"] and "复核" in item["does_not_prove"]
	assert any("是否该被保留" in m for m in verdict["missing_evidence"])


def test_engine_finished_but_gui_missing_gets_its_own_cause() -> None:
	"""原始诉求里的第四类：引擎已完成而界面没收到，既不是模型错也不是任务失败。"""
	verdict = attribute_fault(
		_run(),
		[Finding(
			rule_id="wire_gap", rule_version=1, phenomenon="事件流出现缺口通知",
			boundary="sse_gui", component="SSE 传输 / 界面", status=CONFIRMED_FAULT,
			evidence=[EvidenceRef(source="audit", locator="audit.jsonl", ref_id="L21", detail="stream_gap")],
			impact="界面缺尾部而服务端可能已完成。", coverage_gap="客户端 ack 游标不持久化。",
			allowed_conclusion="可确认传输或显示边界存在缺口。",
		)],
	)
	codes = _codes(verdict)
	assert "display_transport_gap" in codes
	item = next(c for c in verdict["causes"] if c["code"] == "display_transport_gap")
	assert item["party"] == "engine"
	assert "不能证明引擎未完成" in item["does_not_prove"]
	assert verdict["responsibility"] == "engine"


def test_causes_are_listed_not_merged(monkeypatch) -> None:
	_user_turn("改完必须跑 pytest", "别的内容", monkeypatch)
	run = _run(
		tool_calls=[
			ToolCall(
				tool_use_id="c1",
				tool_name="Bash",
				started={"line_no": 3},
				finished={"line_no": 4, "error_kind": "COMMAND_NOT_FOUND", "command_summary": "pytest"},
				is_error=True,
				error_kind="COMMAND_NOT_FOUND",
			)
		],
		model_requests=[ModelRequest(model_request_id="r1", attempts=[{"attempt": 1, "kind": "model.finished", "status": "ok"}])],
	)
	verdict = attribute_fault(run, [_finding("tool_failure", "tool_permission", detail="tool.finished is_error=true error_kind=COMMAND_NOT_FOUND")])
	codes = _codes(verdict)
	assert len(codes) > len(set(codes)) or len(codes) >= 2
	assert "tool_execution_error" in codes
	# 多原因并存时不做综合结论
	assert "不合并" in verdict["cause_statement"] or len(codes) == 1
