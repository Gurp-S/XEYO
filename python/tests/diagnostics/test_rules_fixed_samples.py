"""固定故障样本 + 正常对照：每条结论都能回到原始证据，正常等待不误判。"""

from __future__ import annotations

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
