"""责任划分的验收：四类失败必须落到不同归属，且判"模型的错"要有送达证据。"""

from __future__ import annotations

import json

import pytest

from diagnostics.collect import ModelRequest, RunEvidence, ToolCall
from diagnostics.fault_split import (
	ENGINE,
	ENVIRONMENT,
	MIXED,
	MODEL,
	OUTCOME_FAIL,
	OUTCOME_NOT_ACCEPTED,
	OUTCOME_PASS,
	UNDETERMINED,
	attribute_fault,
)
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, EvidenceRef, Finding
from session.persistence import transcript_path


def _finding(rule_id: str, boundary: str, *, status: str = CONFIRMED_FAULT, detail: str = "") -> Finding:
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


def _write_transcript(session_id: str, rows: list[dict]) -> None:
	path = transcript_path(session_id)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# ---------- 四类失败：各归各方 ----------


def test_permission_block_is_engine_not_model() -> None:
	"""权限把调用挡下来：执行层事实，不能算模型没干活。"""
	run = _run()
	verdict = attribute_fault(run, [_finding("permission_block", "tool_permission", detail="tool_use_id=c1")])
	assert verdict["responsibility"] == ENGINE
	assert verdict["engine_confirmed"] >= 1
	assert "输入已不是任务本来的输入" in verdict["why"]


def test_tool_failure_with_missing_command_is_environment() -> None:
	"""命令不存在：外部世界的事实，引擎与模型都未被证明有错。"""
	run = _run()
	verdict = attribute_fault(run, [_finding("tool_failure", "tool_permission", detail="tool.finished is_error=true error_kind=COMMAND_NOT_FOUND")])
	assert verdict["responsibility"] == ENVIRONMENT


def test_engine_error_kind_inside_tool_failure_is_engine() -> None:
	run = _run()
	verdict = attribute_fault(run, [_finding("tool_failure", "tool_permission", detail="tool.finished is_error=true error_kind=PERMISSION_DENIED")])
	assert verdict["responsibility"] == ENGINE


def test_transport_gap_is_engine_side_not_model() -> None:
	"""引擎已完成但界面没收到：责任在传输/显示边界，与模型无关。"""
	run = _run()
	verdict = attribute_fault(run, [_finding("wire_gap", "sse_gui", status=SUSPECTED_CAUSE)])
	# 疑似级传输缺口不足以定责
	assert verdict["responsibility"] == UNDETERMINED
	run2 = _run()
	verdict2 = attribute_fault(run2, [_finding("wire_gap", "sse_gui", status=CONFIRMED_FAULT)])
	assert verdict2["responsibility"] == ENGINE
	assert verdict2["transport_gap"] is True


# ---------- 判"模型的错"必须有送达证据 ----------


def test_model_fault_requires_constraint_shown(monkeypatch) -> None:
	constraint = "改完必须跑 pytest tests/diagnostics 才算完成"
	_write_transcript("s1", [
		{"id": "m1", "role": "user", "ts": 1.0, "content": constraint},
		{"id": "m2", "role": "assistant", "ts": 2.0, "content": "测试通过，任务已完成"},
	])
	sent = json.dumps([{"role": "user", "content": constraint}], ensure_ascii=False)

	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (sent, "working.json"))
	run = _run(
		pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "pins/p1.json"}],
		transcript_rows=[
			{"id": "m1", "role": "user", "content": constraint, "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "测试通过，任务已完成", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "shown"
	assert verdict["responsibility"] == MODEL
	assert verdict["task_outcome"] == OUTCOME_FAIL
	assert "self_report" in verdict


def test_post_hoc_pin_cannot_claim_context_loss_but_can_name_requirement(monkeypatch) -> None:
	"""两条判据分开：当场在场的原话才判"上下文丢了它"；事后声明只当要求来源。"""
	constraint = "改完必须跑 pytest"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	# 投影里带着该约束 ⇒ 不成立"引擎丢了约束"
	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		pins=[
			{"kind": "run_mark", "pin_id": "p0", "expected": constraint, "created_at": 999.0, "locator": "p0.json"},
			{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "p1.json"},
		],
		events=[_ev(1.0, "model.started"), _ev(2.0, "model.finished")],
	)
	verdict = attribute_fault(run, [])
	assert not any("源历史里存在，但不在最后发射的投影里" in s["fact"] for s in verdict["chain"])
	assert verdict["task_outcome"] == "accepted_fail"


def test_required_test_skipped_is_a_model_fault_without_a_verifier(monkeypatch) -> None:
	"""没有验收记录也能判：约束送达 + 要求跑测试 + 本轮没跑 + 没被挡 + 自述完成。"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		transcript_rows=[
			{"id": "m1", "role": "user", "content": constraint, "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "已完成，测试通过", "locator": "t.jsonl", "line_no": 2},
		],
		model_requests=[ModelRequest(model_request_id="r1", attempts=[{"attempt": 1, "kind": "model.finished", "status": "ok"}])],
		tool_calls=[
			ToolCall(
				tool_use_id="c1",
				tool_name="Read",
				started={"line_no": 3},
				finished={"line_no": 4, "command_summary": "read config"},
			)
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "shown"
	assert verdict["responsibility"] == MODEL
	assert any("要求动作" in s["fact"] and s["party"] == "model" for s in verdict["chain"])


def test_blocked_action_is_not_a_model_fault(monkeypatch) -> None:
	"""同样要求跑测试，但被权限挡下：归引擎，不归模型。"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		permissions=[
			{"request_id": "apr1", "kind": "permission.resolved", "tool_name": "Bash", "approved": False, "outcome": "user_decided", "line_no": 9}
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] == ENGINE
	assert any(s["party"] == "engine" and "执行层" in s["fact"] for s in verdict["chain"])


def _ev(ts: float, kind: str):
	from diagnostics.identity import normalize_event

	return normalize_event(0, 1, {"ts": ts, "kind": kind, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1"})


def test_no_capture_and_no_projection_cannot_blame_model(monkeypatch) -> None:
	constraint = "改完必须跑测试"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: ("", ""))
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "pins/p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "unprovable"
	assert verdict["responsibility"] == UNDETERMINED
	assert any("可复现记录" in m for m in verdict["missing_evidence"])


def test_constraint_not_sent_is_engine_loss(monkeypatch) -> None:
	constraint = "禁止改 gui/ 下的文件"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"role": "user", "content": "别的内容"}]), "working.json"))
	verdict = attribute_fault(_run(), [])
	assert verdict["shown_to_model"] == "not_shown"
	assert verdict["responsibility"] == ENGINE


def test_engine_and_model_both_holds_is_mixed(monkeypatch) -> None:
	constraint = "必须跑测试"
	_write_transcript("s1", [
		{"id": "m1", "role": "user", "ts": 1.0, "content": constraint},
		{"id": "m2", "role": "assistant", "ts": 2.0, "content": "测试通过"},
	])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		pins=[
			{"kind": "run_mark", "pin_id": "p0", "expected": constraint, "note": "结果不对", "locator": "pins/p0.json"},
			{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "pins/p1.json"},
		],
		transcript_rows=[
			{"id": "m2", "role": "assistant", "content": "测试通过", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [_finding("frozen_head", "wsc_fold")])
	assert verdict["responsibility"] == MIXED
	assert verdict["engine_confirmed"] >= 1


# ---------- 任务结局 ----------


def test_no_verifier_means_outcome_undetermined() -> None:
	verdict = attribute_fault(_run(), [])
	assert verdict["task_outcome"] == OUTCOME_NOT_ACCEPTED
	assert "无法判定" in verdict["task_outcome_label"]
	assert any("verifier" in m for m in verdict["missing_evidence"])


def test_bare_acceptance_failure_does_not_blame_model(monkeypatch) -> None:
	"""验收失败单独一条不够判模型：本轮开始前的红测长得一样。"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "shown"
	assert verdict["task_outcome"] == "accepted_fail"
	assert verdict["responsibility"] == UNDETERMINED
	assert any("先于本轮存在" in m for m in verdict["missing_evidence"])
	# 原因照实列出：责任未定不等于原因没有
	assert "acceptance_failed" in [c["code"] for c in verdict["causes"]]


def test_green_verifier_does_not_become_model_fault() -> None:
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 0, "locator": "pins/p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["task_outcome"] == OUTCOME_PASS
	assert verdict["responsibility"] == UNDETERMINED


def test_verifier_exit_above_128_is_verifier_error() -> None:
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 137, "locator": "pins/p1.json"}])
	assert attribute_fault(run, [])["task_outcome"] == "verifier_error"


def test_missing_exit_code_is_not_treated_as_zero() -> None:
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": None, "locator": "pins/p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["task_outcome"] == OUTCOME_NOT_ACCEPTED


# ---------- 纪律 ----------


def test_verdict_always_states_what_it_does_not_claim() -> None:
	verdict = attribute_fault(_run(), [])
	assert verdict["not_claimed"]
	assert any("概率" in s for s in verdict["not_claimed"])
	for step in verdict["chain"]:
		assert step["evidence"], "因果链上每一步都必须能回到原始记录"
		assert step["party"] in {ENGINE, MODEL, ENVIRONMENT, UNDETERMINED}


def test_report_and_markdown_carry_the_verdict(collect) -> None:
	from diagnostics.report import build_report, to_markdown

	run = collect([
		{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
		{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
	])
	doc = build_report(run)
	assert doc["fault"]["responsibility"] in {ENGINE, MODEL, ENVIRONMENT, MIXED, UNDETERMINED}
	md = to_markdown(doc)
	assert "## 责任划分" in md
	assert "本报告不宣称" in md
