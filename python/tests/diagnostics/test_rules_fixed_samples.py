"""固定故障样本 + 正常对照：每条结论都能回到原始证据，正常等待不误判。"""

from __future__ import annotations

from diagnostics.fault_split import ENGINE, ENVIRONMENT, UNDETERMINED, attribute_fault
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, UNKNOWN
from diagnostics.rules import evaluate_run
from diagnostics.report import attribution, build_report, usage_summary


def _kinds(findings) -> dict[str, set[str]]:
	out: dict[str, set[str]] = {}
	for f in findings:
		out.setdefault(f.rule_id, set()).add(f.status)
	return out


# ---------- 固定故障样本 ----------


def test_model_error_is_located_at_model_boundary(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "provider": "deepseek", "model": "m"},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "failed", "error_code": "HTTP_400"},
		]
	)
	findings = evaluate_run(run)
	assert CONFIRMED_FAULT in _kinds(findings).get("provider_stream_failure", set())
	f = next(x for x in findings if x.rule_id == "provider_stream_failure")
	assert f.boundary == "model_request"
	assert f.evidence and f.evidence[0].ref_id == "L2"
	# 结论断言的是哪个 status/code，证据里就得原样带着：只写 kind 的正文等于
	# 让读者按行号自己回读才能核对这句话。
	assert "status=failed" in f.evidence[0].detail
	assert "error_code=HTTP_400" in f.evidence[0].detail
	assert attribution(run, findings)["attributed"] is True


def test_rate_limit_is_not_blamed_on_prompt(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "llm.failure", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "code": "http_429", "status": 429},
		]
	)
	f = next(x for x in evaluate_run(run) if x.rule_id == "provider_stream_failure")
	assert "429" in f.phenomenon
	assert "提示词" in f.allowed_conclusion or "限流" in f.allowed_conclusion


def test_tool_failure_is_grouped_and_anchored(collect) -> None:
	rows = [{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}]
	for i in range(3):
		rows.append({"ts": 2.0 + i, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": f"c{i}", "tool_name": "Bash", "model_request_id": "r1", "command_summary": "pytest x"})
		rows.append({"ts": 2.5 + i, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": f"c{i}", "tool_name": "Bash", "is_error": True, "error_kind": "EXIT_NONZERO", "model_request_id": "r1"})
	run = collect(rows)
	kinds = _kinds(evaluate_run(run))
	assert CONFIRMED_FAULT in kinds.get("tool_failure", set())
	# 同参数同错误签名重复 3 次 ⇒ 只算重复失败信号，不宣称死循环
	assert SUSPECTED_CAUSE in kinds.get("repeated_failure", set())
	rf = next(x for x in evaluate_run(run) if x.rule_id == "repeated_failure")
	assert "死循环" in rf.allowed_conclusion
	# impact 不得说"同一参数"：审计不带参数，签名里的参数位恒为空
	# （真实尾窗 tool.* 行 0 条带 command/file_path/pattern/url），而 coverage_gap
	# 本来就已经写明"签名相同不等于参数相同"。
	assert "同一参数" not in rf.impact
	assert "参数是否相同不可证" in rf.impact


def _tool_error_run(collect, error_kind: str):
	"""一条完整轮次：工具失败 + 指定的 error_kind（走真实生产者，不手写证据）。"""
	rows = [
		{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
		{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "completed"},
		{"ts": 2.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
		{"ts": 2.5, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "is_error": True, "error_kind": error_kind, "model_request_id": "r1"},
	]
	run = collect(rows)
	return evaluate_run(run), run


def test_tool_error_kind_reaches_the_attribution_layer(collect) -> None:
	"""规则写出的证据 detail 必须带 error_kind：归属表只从 detail 读这个字段。

	生产侧原先只写 `is_error=true action_id=...` ⇒ 两张归属表在真实数据上一次也没
	被读到过（尾窗 200 轮：74/74 条证据落空，全部判"未定"）。
	"""
	findings, run = _tool_error_run(collect, "NOT_FOUND")
	f = next(x for x in findings if x.rule_id == "tool_failure")
	assert "error_kind=NOT_FOUND" in f.evidence[0].detail
	assert attribute_fault(run, findings)["responsibility"] == ENVIRONMENT


def test_default_internal_kind_is_not_blamed_on_the_engine(collect) -> None:
	"""INTERNAL 是 base_tool 的兜底值，不是"引擎内部出错"的证据。

	真实数据里非空的 error_kind 只有这一个取值（尾窗 12 000 行 129/129）：把它当分类
	印出来是给读者一个不存在的区分，把它当归属依据是把全部工具失败判给我方引擎。
	"""
	findings, run = _tool_error_run(collect, "INTERNAL")
	f = next(x for x in findings if x.rule_id == "tool_failure")
	assert "error_kind=INTERNAL" in f.evidence[0].detail  # 原值仍留在证据里，可回读
	assert "未细分" in f.phenomenon
	verdict = attribute_fault(run, findings)
	assert verdict["responsibility"] == UNDETERMINED


def test_permission_wait_is_not_a_confirmed_fault(collect) -> None:
	"""正常等待审批：不得判成故障，也不得判成卡死。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "model_request_id": "r1"},
			{"ts": 1.1, "kind": "permission.pending", "session_id": "s1", "turn_id": "t1", "request_id": "apr1", "tool_name": "Bash", "tool_use_id": "c1"},
		]
	)
	findings = evaluate_run(run)
	assert all(f.status != CONFIRMED_FAULT for f in findings if f.rule_id == "permission_block")
	pb = [f for f in findings if f.rule_id == "permission_block"]
	assert pb and all(f.status == UNKNOWN for f in pb)
	assert "进程" in pb[0].coverage_gap or "重启" in pb[0].coverage_gap


def test_permission_deny_is_execution_layer_fact(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "permission.pending", "session_id": "s1", "turn_id": "t1", "request_id": "apr1", "tool_name": "Bash", "tool_use_id": "c1", "matched_rule": "bash_danger"},
			{"ts": 1.1, "kind": "permission.resolved", "session_id": "s1", "turn_id": "t1", "request_id": "apr1", "tool_name": "Bash", "tool_use_id": "c1", "approved": False, "outcome": "user_decided"},
		]
	)
	f = next(x for x in evaluate_run(run) if x.status == CONFIRMED_FAULT and x.rule_id == "permission_block")
	assert "bash_danger" in f.component + f.phenomenon + f.impact
	assert "预期内的 DENY" in f.coverage_gap


def test_wire_gap_links_drop_ledger_to_run(collect) -> None:
	import usage.ledger as ledger

	ledger.record_wire_drop(dropped_ids=["c1", "c2"], target="wire")
	run = collect(
		[
			{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
		]
	)
	findings = evaluate_run(run)
	gap = [f for f in findings if f.rule_id == "wire_gap"]
	assert gap and gap[0].status == CONFIRMED_FAULT
	assert "c1" in gap[0].evidence[0].detail


def test_missing_usage_never_becomes_zero_cost(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
		]
	)
	summary = usage_summary(run)
	assert summary["unknown_cost_attempts"] == 1
	assert summary["estimated_total_cny"] == 0.0
	assert "费用未知" in summary["statement"]
	f = next(x for x in evaluate_run(run) if x.rule_id == "usage_accounting")
	assert "不得按 0" in f.impact


def test_retried_attempt_without_usage_is_not_a_confirmed_account_fault(collect) -> None:
	"""重打／换通道那一枪常常没拿到厂商用量：账本按契约不写行，不是引擎漏记。

	生产者契约见 ``model/deepseek.py::_record_usage_safe`` 的 ``if not usage: return``。
	真实语料里 8 个报「已确认缺账」的轮次有 4 个整条都由这类尝试构成（2026-09-26 普查）。
	"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "protocol_fallback"},
			{"ts": 1.2, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1},
			{"ts": 1.3, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1, "status": "retry"},
		]
	)
	ua = [f for f in evaluate_run(run) if f.rule_id == "usage_accounting"]
	assert ua, "费用未知这件事不能消失"
	assert CONFIRMED_FAULT not in {f.status for f in ua}
	assert {f.status for f in ua} == {UNKNOWN}
	assert sum(len(f.evidence) for f in ua) == 2
	claim = ua[0]
	assert "2 次" in claim.phenomenon
	assert "不得按 0" in claim.impact  # 降级不等于按 0 计入
	assert "没拿到" in claim.coverage_gap and "没落账" in claim.coverage_gap


def test_ok_and_retried_missing_accounts_stay_two_claims(collect) -> None:
	"""同一轮里两种形状并存时不能合成一条：合并就是把未定说成已确认。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "protocol_fallback"},
			{"ts": 1.2, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1},
			{"ts": 1.3, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1, "status": "ok"},
		]
	)
	ua = [f for f in evaluate_run(run) if f.rule_id == "usage_accounting"]
	ok = [f for f in ua if f.status == CONFIRMED_FAULT]
	retried = [f for f in ua if f.status == UNKNOWN]
	assert len(ok) == len(retried) == 1
	assert ok[0].phenomenon == "1 次成功结束的模型尝试在用量账本里没有对应记录"
	assert "重打或换通道" in retried[0].phenomenon
	assert ok[0].evidence[0].ref_id == "L4"
	assert retried[0].evidence[0].ref_id == "L2"


def test_policy_deny_without_ask_is_visible_and_blames_nobody(collect) -> None:
	"""只读门与策略 DENY 不弹审批：真实审计 214 行 permission.denied 全是这一形。

	逐 id 追踪（2026-09-26）：一次拒绝在整份审计里只有这一行 —— 没有 pending 兄弟，
	也没有 tool.started / tool.finished。旧通路按 pending 配对，于是这类拦截整条看不到。
	"""
	run = collect(
		[
			{"ts": 1.0, "kind": "permission.denied", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "matched_rule": "bash_deny", "reason": "destructive_root_delete", "agent_id": "a1"},
			{"ts": 1.1, "kind": "permission.denied", "session_id": "s1", "turn_id": "t1", "request_id": "c2", "tool_name": "Read", "matched_rule": "read_deny", "reason": "path_outside_working_directory", "agent_id": "a1"},
		]
	)
	claims = [f for f in evaluate_run(run) if f.rule_id == "permission_block"]
	assert len(claims) == 1, [c.phenomenon for c in claims]
	claim = claims[0]
	assert claim.status == UNKNOWN, "策略拒绝是执行层的设计结果，不是已确认故障"
	assert "2 次工具调用没进审批等待就被执行层挡下" in claim.phenomenon
	assert "Bash 1 次" in claim.phenomenon and "Read 1 次" in claim.phenomenon
	# 机器码留在证据里供回读，现象句说人话
	details = " ".join(e.detail for e in claim.evidence)
	assert "matched_rule=read_deny" in details and "reason=path_outside_working_directory" in details
	assert attribute_fault(run, claims)["responsibility"] != ENGINE


def test_deny_with_pending_sibling_stays_on_the_ask_path(collect) -> None:
	"""有 pending 的 DENY 仍走原来的配对通路，不得被新分支重复报一条。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "permission.pending", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash"},
			{"ts": 1.1, "kind": "permission.denied", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "matched_rule": "bash_deny", "reason": "destructive_root_delete"},
		]
	)
	claims = [f for f in evaluate_run(run) if f.rule_id == "permission_block"]
	assert len(claims) == 1, [c.phenomenon for c in claims]
	assert "没进审批等待" not in claims[0].phenomenon


def test_priced_and_duplicated_usage_are_both_visible(collect) -> None:
	from usage.ledger import events_path, record_from_openai_usage

	record_from_openai_usage(
		provider="deepseek", model="deepseek-chat", api_key="sk-x",
		usage={"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
		session_id="s1", request_id="r1", attempt=1,
	)
	record_from_openai_usage(  # 同一次尝试重复入账
		provider="deepseek", model="deepseek-chat", api_key="sk-x",
		usage={"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
		session_id="s1", request_id="r1", attempt=1,
	)
	assert events_path().is_file()
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
		]
	)
	rules = _kinds(evaluate_run(run))
	assert CONFIRMED_FAULT in rules.get("usage_accounting", set())
	ua = [f for f in evaluate_run(run) if f.rule_id == "usage_accounting"]
	assert any("多笔" in f.phenomenon for f in ua)
	assert usage_summary(run)["priced_attempts"] == 1


def test_projection_structure_fault_is_confirmed_at_adapter(collect) -> None:
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"}]
	)
	run.projections.append(
		{
			"projection_id": "p1",
			"locator": "sessions/s1.working.json",
			"invariant_errors": ["orphan_tool_results:1"],
			"messages_kept": 12,
		}
	)
	findings = evaluate_run(run)
	f = next(x for x in findings if x.rule_id == "tool_pair_integrity")
	assert f.status == CONFIRMED_FAULT and f.boundary == "adapter"
	assert "任务失败的全部原因" in f.allowed_conclusion


def test_canonical_layer_hole_is_reported_but_not_blamed(collect) -> None:
	"""第四类旗标查的是完整历史，不是这一枪发出去的投影 ⇒ 只能说有洞，不能说请求形状坏。

	这条旗标由 engine/projection_manifest.py 写下，此前规则集里没有任何一条读它：
	生产者已经算出来的事实被整条丢掉，界面上就显示成"没有这类问题"。
	"""
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"}]
	)
	run.projections.append(
		{
			"projection_id": "p1",
			"locator": "sessions/s1.working.json",
			"invariant_errors": ["canonical_unpaired_tool_calls:2"],
			"messages_kept": 12,
		}
	)
	findings = evaluate_run(run)
	f = next(x for x in findings if x.rule_id == "tool_pair_integrity")
	assert f.status == UNKNOWN and f.boundary == "wsc_fold"
	assert f.evidence[0].detail == "canonical_unpaired_tool_calls:2"
	assert "不能据此判定本轮请求形状坏了" in f.allowed_conclusion


def test_canonical_layer_hole_from_other_turn_is_silent(collect) -> None:
	"""working 只存最后一份 manifest：不是本轮那一份就不许产成本轮结论。"""
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p_other"}]
	)
	run.projections.append(
		{
			"projection_id": "p1",
			"locator": "sessions/s1.working.json",
			"invariant_errors": ["canonical_unpaired_tool_calls:2"],
			"messages_kept": 12,
		}
	)
	assert [x for x in evaluate_run(run) if x.rule_id == "tool_pair_integrity"] == []


def _routed_rows(kind: str = "tool.routed") -> list[dict[str, object]]:
	return [
		{
			"ts": 2.0,
			"kind": kind,
			"session_id": "s1",
			"turn_id": "t1",
			"request_id": "call_1",
			"tool_name": "Bash",
			"routed_to": "Glob",
			"command": 'dir "doc/*"',
			"tier": "T3",
		}
	]


def test_tool_routing_reports_the_swap_but_blames_nobody(collect) -> None:
	"""tool.routed 有审计行、带完整轮次身份，此前没有任何一条规则读它。"""
	run = collect(_routed_rows())
	findings = evaluate_run(run)
	f = next(x for x in findings if x.rule_id == "tool_routing")
	assert f.status == UNKNOWN and f.boundary == "tool_permission"
	assert "Glob 1 次" in f.phenomenon
	assert f.evidence[0].detail.startswith("Bash→Glob")
	assert 'dir "doc/*"' in f.evidence[0].detail
	assert "不得据此判定分发故障" in f.allowed_conclusion


def test_routed_observed_is_not_reported_as_a_swap(collect) -> None:
	"""Phase 0 观测只说明"计划命中"，执行层没有拦截：报成改道就是说假话。"""
	run = collect(_routed_rows("tool.routed_observed"))
	assert [x for x in evaluate_run(run) if x.rule_id == "tool_routing"] == []


def test_tool_routing_ignores_other_turns_swaps() -> None:
	"""规则层自己按轮次筛：采集层今天会丢掉别轮的行，但那层一旦放宽就是越轮归因。"""
	from diagnostics.collect import RunEvidence
	from diagnostics.identity import normalize_event
	from diagnostics.rules import check_tool_routing

	run = RunEvidence(
		session_id="s1",
		turn_id="t1",
		events=[
			normalize_event(
				0,
				7,
				{"ts": 1.0, "kind": "tool.routed", "session_id": "s1", "turn_id": "t_other", "request_id": "c2", "tool_name": "Bash", "routed_to": "Read"},
			)
		],
	)
	assert check_tool_routing(run) == []
	run.events.append(
		normalize_event(
			1,
			8,
			{"ts": 2.0, "kind": "tool.routed", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "routed_to": "Glob"},
		)
	)
	assert [f.phenomenon for f in check_tool_routing(run)] == ["1 次工具调用在执行层换了工具：Glob 1 次"]
	run.turn_id = ""  # 会话级报告（诊断端点允许空 turn_id）：措辞不得把行数说成"这一轮"
	session_level = check_tool_routing(run)
	assert len(session_level) == 1
	assert "这一轮" not in session_level[0].phenomenon


def test_frozen_head_change_inside_same_interval_is_confirmed(collect) -> None:
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"}]
	)
	run.working["compact_checkpoint"] = {
		"anchor_cursor": 4,
		"anchor_frozen_until": 0,
		"window_chain": [
			{"cursor": 8, "frozen_until": 3, "summary_fp": "aaaa"},
			{"cursor": 8, "frozen_until": 3, "summary_fp": "bbbb"},
		],
	}
	f = next(x for x in evaluate_run(run) if x.rule_id == "frozen_head")
	assert f.status == CONFIRMED_FAULT
	assert "缓存" in f.impact or "前缀" in f.impact


def test_drift_within_turn_reports_which_field_changed(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "tool_schema_hash": "h1", "permission_snapshot_id": "s_a"},
			{"ts": 1.1, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1, "tool_schema_hash": "h2", "permission_snapshot_id": "s_a"},
		]
	)
	drift = [f for f in evaluate_run(run) if f.rule_id == "instruction_drift"]
	assert len(drift) == 1
	assert "tool_schema_hash" in drift[0].phenomenon
	assert "变坏" in drift[0].allowed_conclusion


def test_missing_cold_reference_is_recoverability_fault(collect) -> None:
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}]
	)
	run.transcript_rows.append(
		{"id": "m1", "role": "tool", "tool_call_id": "c1", "content_ref": "gone.json", "body_state": "resolve_failed", "locator": "sessions/s1.jsonl"}
	)
	f = next(x for x in evaluate_run(run) if x.rule_id == "cold_reference")
	assert f.status == CONFIRMED_FAULT
	assert f.boundary == "wsc_fold"


def test_verdict_without_pin_says_not_run(collect) -> None:
	"""没有验收记录时，"无法判定结局"这句话必须还在 —— 只是不再由一条逐轮恒真的
	unknown 结论承担（真实数据 40/40 轮都产出一条），而由责任划分承担。"""
	from diagnostics.fault_split import attribute_fault

	run = collect([{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}])
	assert [f for f in evaluate_run(run) if f.rule_id == "verifier"] == []
	verdict = attribute_fault(run, evaluate_run(run))
	assert verdict["task_outcome"] == "not_accepted"
	assert "验收" in verdict["task_outcome_label"]


# ---------- 正常对照 ----------


def test_healthy_run_yields_no_confirmed_fault_but_still_disclaims(collect) -> None:
	from usage.ledger import record_from_openai_usage

	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-chat",
		api_key="sk-x",
		usage={"prompt_tokens": 40, "completion_tokens": 6, "total_tokens": 46},
		session_id="s1",
		request_id="r1",
		attempt=1,
	)
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok", "projection_id": "p1"},
			{"ts": 1.2, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
			{"ts": 1.3, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "is_error": False, "model_request_id": "r1"},
		]
	)
	findings = evaluate_run(run)
	assert not [f for f in findings if f.status == CONFIRMED_FAULT]
	att = attribution(run, findings)
	assert att["attributed"] is False
	assert "不等于任务正确" in att["statement"]


def test_old_rows_with_missing_fields_still_render(collect) -> None:
	"""旧审计缺 attempt / turn_id / projection_id：不补值、不报错、仍能出图。"""
	run = collect([{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "request_id": "c1", "tool_name": "Read"}])
	doc = run.to_dict()
	tool = doc["tool_calls"][0]
	assert tool["turn_id"] == "" and tool["model_request_id"] == ""
	assert doc["identity"]["attempt_keys"] == []
	report = build_report(run)
	assert report["schema_version"] == 1


def test_broken_rule_becomes_visible_unknown_instead_of_silence(collect, monkeypatch) -> None:
	import diagnostics.rules as rules_mod

	def _boom(_run):
		raise RuntimeError("规则内部故障")

	monkeypatch.setattr(rules_mod, "RULES", (rules_mod.Rule("boom", _boom),))
	findings = rules_mod.evaluate_run(collect([{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1"}]))
	assert len(findings) == 1
	assert findings[0].status == UNKNOWN
	assert "没发现异常" in findings[0].allowed_conclusion


def test_stream_gap_audit_row_is_a_suspected_transport_gap(collect) -> None:
	"""引擎发出缺口帧时必须落审计行，否则 sse_gui 边界没有任何可读的缺口证据。

	这一支原先读 notice.channel 上一个从未被写过的 kind_detail 字段 ⇒ 规则永不命中，
	而界面仍按"该边界有规则覆盖"展示（2026-09-25 生产者普查确认）。
	"""
	run = collect(
		[
			{"ts": 1.0, "kind": "stream.gap", "session_id": "s1", "turn_id": "t1", "dropped_through_event_id": 12, "first_available_event_id": 41},
		]
	)
	gaps = [f for f in evaluate_run(run) if f.rule_id == "wire_gap"]
	assert gaps, "stream.gap 行必须被读成传输缺口"
	assert gaps[0].status == SUSPECTED_CAUSE and gaps[0].boundary == "sse_gui"
	assert "12" in gaps[0].phenomenon and "41" in gaps[0].phenomenon


def test_llm_failure_phenomenon_carries_the_code_the_writer_actually_writes(collect) -> None:
	"""llm.failure 的错误码在 `code` 字段上，不在 model.* 那套 `error_code` 里。

	采集只读后者的话，现象里的 code= 恒为空 —— 看着像"厂商没给码"，其实是字段名错位。
	"""
	run = collect(
		[
			{"ts": 1.0, "kind": "llm.failure", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "code": "http_429", "status": 429},
		]
	)
	f = next(x for x in evaluate_run(run) if x.rule_id == "provider_stream_failure")
	assert "code=http_429" in f.phenomenon


def test_orphan_started_after_a_clean_call_is_still_reported(collect) -> None:
	"""前一个调用干净结束，不能把"只开了头且其后什么记录都没有"的调用一起吞掉。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
			{"ts": 1.1, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "is_error": False, "model_request_id": "r1"},
			{"ts": 1.2, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c2", "tool_name": "Bash", "model_request_id": "r1"},
		]
	)
	orphans = [f for f in evaluate_run(run) if f.rule_id == "tool_pair_integrity" and f.status == UNKNOWN]
	assert orphans, "c2 有开始无结束且其后无任何记录：这条事实被整轮判据吞掉了"
	assert "1 个工具调用" in orphans[0].phenomenon
	# 措辞要说清参照范围只有本运行的行：同一会话更晚轮次不算"其后"，
	# 否则读者会把"没有别的行可参照"读成"这个会话之后再无记录"。
	assert "本轮记录里" in orphans[0].phenomenon
	assert "更晚轮次" in orphans[0].coverage_gap
	assert [e.ref_id for e in orphans[0].evidence] == ["L3"]


def test_no_later_activity_claim_when_records_follow(collect) -> None:
	"""整轮没有 tool.finished，但孤儿行之后还有别的记录：不能说"其后无更晚活动可参照"。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
			{"ts": 1.1, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1},
		]
	)
	assert not [f for f in evaluate_run(run) if f.rule_id == "tool_pair_integrity"]


def test_started_row_without_line_number_is_not_claimed_orphaned() -> None:
	"""行号拿不到就无从判断前后：不得把"不知位置"报成"其后无更晚活动"。"""
	from diagnostics.collect import RunEvidence, ToolCall
	from diagnostics.rules import check_tool_pair_integrity

	run = RunEvidence(session_id="s1", turn_id="t1")
	run.tool_calls.append(
		ToolCall(tool_use_id="c1", tool_name="Read", turn_id="t1", started={"kind": "tool.started"})
	)
	orphans = [f for f in check_tool_pair_integrity(run) if f.rule_id == "tool_pair_integrity"]
	assert not orphans


def test_unattributed_rows_count_as_later_activity(collect) -> None:
	"""不带轮次身份的行同样算"更晚活动"：参照口径必须与挑出调用的口径一致。

	``turn_scoped`` 保留不带 turn_id 的旧行（无从排除），所以"其后还有没有记录"
	也得看见这些行；只看归属本轮的行，就会在一堆未归属记录之后报出
	"其后无更晚活动可参照"。
	"""
	run = collect(
		[
			{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
			{"ts": 1.1, "kind": "permission.pending", "session_id": "s1", "request_id": "apr1", "tool_name": "Read", "tool_use_id": "c1"},
		]
	)
	assert not [f for f in evaluate_run(run) if f.rule_id == "tool_pair_integrity"]
