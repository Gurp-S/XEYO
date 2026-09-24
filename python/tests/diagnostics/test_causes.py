"""失败原因分类：每条都必须自带"能证明什么/不能证明什么"，且不得合并成综合结论。"""

from __future__ import annotations

import json

from diagnostics.causes import (
	ACCEPT_MISSING,
	SELF_REPORT_MISMATCH,
	ACTION_SKIPPED,
	CONTEXT_DROPPED,
	NOT_DETERMINED,
	PERMISSION_BLOCKED,
	PROJECTION_BROKEN,
	primary,
)
from diagnostics.collect import ModelRequest, RunEvidence, ToolCall
from diagnostics.fault_split import attribute_fault
from diagnostics.identity import CONFIRMED_FAULT, EvidenceRef, Finding
from session.persistence import transcript_path


def _finding(rule_id: str, boundary: str, *, detail: str = "") -> Finding:
	return Finding(
		rule_id=rule_id,
		rule_version=1,
		phenomenon=f"{rule_id} 现象",
		boundary=boundary,
		component="测试组件",
		status=CONFIRMED_FAULT,
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
	# 引擎挡了动作、模型又断言"测试通过"而没有任何验收：两方各自成立
	assert verdict["responsibility"] == "mixed"
	assert SELF_REPORT_MISMATCH in codes


def test_missing_verifier_is_a_cause_but_blames_nobody(monkeypatch) -> None:
	_user_turn("随便改点什么", "随便改点什么", monkeypatch)
	verdict = attribute_fault(_run(), [])
	assert ACCEPT_MISSING in _codes(verdict)
	item = next(c for c in verdict["causes"] if c["code"] == ACCEPT_MISSING)
	assert item["party"] == "undetermined"
	assert "既不能判完成也不能判失败" in item["does_not_prove"]


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
