"""证据合并的不变量：多义字段归一、缺项不补值、尾窗截断必须可见。"""

from __future__ import annotations

import json

from diagnostics.collect import _tail_jsonl, boundary_of, collect_run, list_runs
from diagnostics.identity import normalize_event, request_key


def test_boundary_of_maps_kind_prefixes() -> None:
	assert boundary_of("permission.pending") == "tool_permission"
	assert boundary_of("llm.failure") == "model_request"
	assert boundary_of("config.invalid") == "instruction_context"

def test_request_id_is_disambiguated_by_kind() -> None:
	"""同一个 request_id 字段在三类事件里含义不同，归一后不得互相串。"""
	tool = normalize_event(0, 1, {"kind": "tool.started", "request_id": "call_7", "session_id": "s"})
	model = normalize_event(1, 2, {"kind": "model.started", "request_id": "req_7", "session_id": "s"})
	perm = normalize_event(2, 3, {"kind": "permission.pending", "request_id": "apr_7", "session_id": "s"})
	assert tool.tool_use_id == "call_7" and tool.model_request_id == ""
	assert model.model_request_id == "req_7" and model.tool_use_id == ""
	assert perm.approval_id == "apr_7" and perm.tool_use_id == ""


def test_turn_id_falls_back_to_trace_id_only() -> None:
	"""工具行只带 trace_id 时按轮次归它；两个都在且不同时 turn_id 优先。"""
	only_trace = normalize_event(0, 1, {"kind": "tool.started", "trace_id": "t9"})
	both = normalize_event(1, 2, {"kind": "model.started", "turn_id": "t1", "trace_id": "t2"})
	none = normalize_event(2, 3, {"kind": "config.invalid"})
	assert only_trace.turn_id == "t9"
	assert both.turn_id == "t1"
	assert none.turn_id == ""


def test_attempt_key_distinguishes_retries() -> None:
	assert request_key("r1", 1) == "r1#1"
	assert request_key("r1", 2) == "r1#2"
	assert request_key("r1", None) == "r1"
	assert request_key("", 3) == ""


def test_missing_fields_stay_empty_rather_than_invented(collect) -> None:
	"""旧审计行缺 model_request_id / projection_id：留空，不写 unknown、不写 0。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read"},
		]
	)
	tool = run.tool_calls[0]
	assert tool.model_request_id == ""
	assert tool.projection_id == ""
	assert tool.finished is None and not tool.paired
	# ts 缺字段也不得变 0
	orphan = normalize_event(0, 5, {"kind": "tool.finished", "session_id": "s1"})
	assert orphan.ts is None


def test_rows_without_session_are_counted_not_silently_dropped(write_audit) -> None:
	"""缺 session_id 的旧行无法归因，必须在窗口说明里出现，而不是悄悄消失。"""
	path = write_audit(
		[
			{"ts": 1.0, "kind": "llm.failure", "code": "conn", "attempt": 1, "status": 500},
			{"ts": 1.1, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
		]
	)
	run = collect_run("s1", "t1", audit_path=path)
	window = run.window("audit")
	assert window is not None
	assert window.rows_scanned == 2 and window.rows_matched == 1
	assert "session_id 为空" in window.note


def test_tail_window_reports_truncation_and_keeps_line_numbers(tmp_path) -> None:
	path = tmp_path / "audit.jsonl"
	rows = [{"ts": float(i), "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": f"r{i}"} for i in range(60)]
	path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
	entries, _read, truncated = _tail_jsonl(path, 400)
	assert truncated
	assert entries, "尾窗必须仍能拿到行"
	last_line_no, last_row = entries[-1]
	assert last_row["model_request_id"] == "r59"
	assert last_line_no == 60, "行号必须等于物理行号，否则证据指针指向别处"

	run = collect_run("s1", "t1", audit_path=path, max_audit_bytes=400)
	assert run.window("audit").complete is False
	assert any(g.reason == "out_of_window" for g in run.gaps)


def test_full_window_is_marked_complete(collect) -> None:
	run = collect([{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}])
	assert run.window("audit").complete is True


def test_retries_keep_every_attempt(collect) -> None:
	"""多次 retry 不得被"最后一次"覆盖：尝试数、状态序列、attempt_keys 都在。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "retry"},
			{"ts": 1.2, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2},
			{"ts": 1.3, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2, "status": "ok"},
		]
	)
	mr = run.model_requests[0]
	assert mr.attempt_ids() == ["r1#1", "r1#2"]
	assert [a["status"] for a in mr.attempts if a["kind"] == "model.finished"] == ["retry", "ok"]
	doc = run.to_dict()
	assert doc["identity"]["attempt_keys"] == ["r1#1", "r1#2"]


def test_tool_call_links_to_model_request_and_permission(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"},
			{"ts": 1.1, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "model_request_id": "r1"},
			{"ts": 1.2, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "is_error": False, "action_id": "a1", "model_request_id": "r1"},
			{"ts": 1.3, "kind": "permission.pending", "session_id": "s1", "turn_id": "t1", "request_id": "apr1", "tool_name": "Bash", "tool_use_id": "c1"},
		]
	)
	tool = run.tool_calls[0]
	assert tool.paired and tool.action_id == "a1"
	assert tool.approval_ids == ["apr1"], "补口后审批必须能关联唯一原调用"
	assert run.model_requests[0].tool_use_ids == ["c1"]


def test_list_runs_groups_by_turn_and_exposes_coverage(write_audit) -> None:
	path = write_audit(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1"},
			{"ts": 2.0, "kind": "tool.finished", "session_id": "s1", "turn_id": "t2", "request_id": "c2", "tool_name": "Read"},
			{"ts": 3.0, "kind": "permission.resolved", "session_id": "s1", "turn_id": "t2", "request_id": "apr", "approved": True},
		]
	)
	runs = list_runs("s1", audit_path=path)
	assert [r["turn_id"] for r in runs] == ["t2", "t1"]
	assert runs[0]["boundaries"] == ["tool_permission"]
	assert runs[0]["tool_use_ids"] == ["c2"], "按工具调用反查轮次要靠这个字段"
	assert runs[1]["tool_use_ids"] == []
	assert runs[1]["boundaries"] == ["model_request"]


def test_other_sessions_are_not_merged(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "other", "turn_id": "t1", "model_request_id": "rx"},
			{"ts": 1.1, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1"},
		]
	)
	assert [m.model_request_id for m in run.model_requests] == ["r1"]
