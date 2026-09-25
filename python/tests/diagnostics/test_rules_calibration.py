"""真实数据普查确认到的四类误归因缺陷的回归集。

对应 2026-09-25 对十条真实回合的普查（设计文档第 6 节的不对称判据）：

1. ``permission_snapshot_id`` 一个轮里出现多个取值曾被写成 ``confirmed_fault``，
   而授权增删本身就会合法地改变快照 id；
2. ``frozen_head`` 把「本轮折叠账本为空」当成「没折叠过」——折叠事件按会话写、
   行内不带轮次身份，空的折叠集合证明不了任何事；
3. 一个根本不存在的轮次会拿到 ``confirmed_fault`` + 引擎定责，证据来自同会话
   别处的 transcript 行与会话级 leftovers；
4. 真实 DENY 审计行（``tools/tool_registry.py`` 的只读门与策略 DENY）既不带
   ``approved`` 也不带 ``outcome``，被责任划分读成「没挡住」；
5. 折叠与验收的证据指针指向别的来源的文件（拿审计窗口路径冒充 usage 账本、
   拿 working.json 路径冒充 pin）；
6. 投影里 ``full output:`` 与 ``output truncated`` 两个字面量的计数不等被写成"可疑原因"，
   而 ``tools/job_tools.py`` 的 ``(earlier output truncated)`` 天生不带句柄 ⇒ 健康运行也会命中。

纠正的底线：规则要么判对，要么 ``unknown`` 并写明缺哪条记录，不得靠沉默消噪。
"""

from __future__ import annotations

from diagnostics import fault_split, rules
from diagnostics.collect import RunEvidence, Window
from diagnostics.fault_split import ENGINE, MODEL, UNDETERMINED, attribute_fault
from diagnostics.identity import (
	CONFIRMED_FAULT,
	SUSPECTED_CAUSE,
	UNKNOWN,
	Finding,
	normalize_event,
)
from diagnostics.rules import evaluate_run

AUDIT_LOCATOR = r"C:\xeyo\audit\audit.jsonl"
FOLD_LOCATOR = r"C:\xeyo\usage\fold_events.jsonl"


def _ev(line_no: int, kind: str, ts: float = 1.0, **fields):
	row = {"ts": ts, "kind": kind, "session_id": "s1", "turn_id": "t1"}
	row.update(fields)
	return normalize_event(line_no, line_no, row)


def _audit_window(rows: int = 10) -> Window:
	return Window(
		source="audit",
		locator=AUDIT_LOCATOR,
		complete=True,
		rows_scanned=rows,
		rows_matched=rows,
	)


def _fold_window(*, complete: bool = True, rows_matched: int = 0) -> Window:
	return Window(
		source="fold_events",
		locator=FOLD_LOCATOR,
		complete=complete,
		rows_scanned=rows_matched,
		rows_matched=rows_matched,
	)


def _run(events: list | None = None, *, windows: list | None = None, **over) -> RunEvidence:
	"""带采集窗口的视图：窗口在场才允许谈「本轮无记录」（手工构造的空对象不算采集过）。"""
	base = RunEvidence(session_id="s1", turn_id="t1")
	base.events = list(events or [])
	base.windows = list(windows if windows is not None else [_audit_window()])
	for key, value in over.items():
		setattr(base, key, value)
	return base


# ---------- 1. 快照标识的变化：有账可查就不报，无账可查报 unknown ----------


def _snapshot_run() -> RunEvidence:
	return _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, permission_snapshot_id="perm:aaaa"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, permission_snapshot_id="perm:bbbb"),
			_ev(3, "model.started", 3.0, model_request_id="r3", attempt=1, permission_snapshot_id="perm:cccc"),
		]
	)


def test_snapshot_change_is_no_longer_a_confirmed_fault() -> None:
	"""快照 id 变化不得再被写成已确认引擎故障：它不是不变量破坏。"""
	findings = rules.check_instruction_drift(_snapshot_run())
	drift = [f for f in findings if "permission_snapshot_id" in f.phenomenon]
	assert drift, "规则不得靠沉默消掉这条信号"
	assert all(f.status == UNKNOWN for f in drift)
	assert not [f for f in findings if f.status == CONFIRMED_FAULT]


def test_snapshot_change_names_the_record_it_could_not_see() -> None:
	"""unknown 必须写明缺哪条记录：授权增删行不带会话/轮次身份，进不了按会话过滤的窗口。"""
	gap = rules.check_instruction_drift(_snapshot_run())[0].coverage_gap
	assert "permission.grant.added" in gap and "permission.grant.revoked" in gap
	assert "session_id" in gap and "turn_id" in gap


def test_grant_row_in_window_explains_the_snapshot_change() -> None:
	"""窗口里有授权增删行：变化有账可查，这一条就不再作为故障上报。"""
	run = _snapshot_run()
	run.permissions = [
		{
			"kind": "permission.grant.added",
			"grant_id": "g1",
			"tool_name": "Bash",
			"line_no": 9,
			"ts": 1.5,
			"session_id": "s1",
			"turn_id": "t1",
		}
	]
	findings = rules.check_instruction_drift(run)
	assert not [f for f in findings if "permission_snapshot_id" in f.phenomenon]


def test_revocation_row_also_explains_the_snapshot_change() -> None:
	run = _snapshot_run()
	run.events.append(_ev(4, "permission.grant.revoked", 2.5, grant_id="g0"))
	findings = rules.check_instruction_drift(run)
	assert not [f for f in findings if "permission_snapshot_id" in f.phenomenon]


def test_other_identifier_drift_is_still_suspected() -> None:
	"""其余标识保持原判据：本次只纠正误判，不把规则一并削掉。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, tool_schema_hash="h1"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, tool_schema_hash="h2"),
		]
	)
	drift = [f for f in rules.check_instruction_drift(run) if "tool_schema_hash" in f.phenomenon]
	assert drift and drift[0].status == SUSPECTED_CAUSE


# ---------- 2. 折叠账本：空账本不能当成「没折叠过」 ----------


def _projection_run(fold_rows: list, fold_window: Window | None) -> RunEvidence:
	windows = [_audit_window()] + ([fold_window] if fold_window is not None else [])
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, projection_id="p2"),
			_ev(3, "model.started", 3.0, model_request_id="r3", attempt=1, projection_id="p3"),
		],
		windows=windows,
	)
	run.fold_rows = list(fold_rows)
	return run


def test_empty_fold_ledger_no_longer_suspects_prefix_change() -> None:
	"""折叠账本完整但对本会话零行：分不清「没折叠」与「折叠没落账」，只能 unknown。"""
	findings = [f for f in rules.check_frozen_head(_projection_run([], _fold_window())) if "投影" in f.phenomenon]
	assert findings, "这一级没记账必须说出来，不能静默通过"
	assert all(f.status == UNKNOWN for f in findings)


def test_empty_fold_ledger_coverage_gap_names_the_missing_identity() -> None:
	target = [f for f in rules.check_frozen_head(_projection_run([], _fold_window())) if f.status == UNKNOWN]
	assert "轮次身份" in target[0].coverage_gap


def test_truncated_fold_ledger_is_also_unknowable() -> None:
	"""账本没读完时同样不能推断「没折叠」：截断要在措辞里说出来。"""
	findings = [f for f in rules.check_frozen_head(_projection_run([], _fold_window(complete=False))) if f.status == UNKNOWN]
	assert findings


def test_populated_complete_fold_ledger_keeps_the_suspicion() -> None:
	"""账本完整且有行：前提成立，可疑级照旧上报（纠正误判不等于削掉规则）。"""
	run = _projection_run(
		[
			{"session_id": "s1", "fold": True, "reason": "worth_fold", "line_no": 3, "locator": FOLD_LOCATOR},
			{"session_id": "s1", "fold": False, "reason": "pays_back_too_slow", "line_no": 4, "locator": FOLD_LOCATOR},
		],
		_fold_window(complete=True, rows_matched=2),
	)
	findings = [f for f in rules.check_frozen_head(run) if f.rule_id == "frozen_head"]
	assert findings and findings[0].status == SUSPECTED_CAUSE


def test_frozen_head_evidence_points_at_the_fold_ledger() -> None:
	"""折叠证据的指针必须指折叠账本，不得借用审计窗口的路径。"""
	finding = [f for f in rules.check_frozen_head(_projection_run([], _fold_window())) if f.status == UNKNOWN][0]
	assert finding.evidence
	for ref in finding.evidence:
		assert ref.source == "usage"
		assert ref.locator == FOLD_LOCATOR, "windows[0] 是审计窗口，不得当作 usage 账本"
		assert AUDIT_LOCATOR not in ref.locator


def test_frozen_head_without_fold_window_emits_no_borrowed_locator() -> None:
	"""没有折叠账本窗口就留空定位符：宁缺勿借。"""
	finding = [f for f in rules.check_frozen_head(_projection_run([], None)) if f.status == UNKNOWN][0]
	assert all(ref.locator == "" for ref in finding.evidence)
	assert any("fold_events" in ref.detail for ref in finding.evidence)


def test_window_chain_break_is_still_a_confirmed_fault() -> None:
	"""同一折叠区间内摘要指纹变化是真不变量破坏：保持已确认级。"""
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1")])
	run.working = {
		"locator": r"C:\xeyo\sessions\s1.working.json",
		"compact_checkpoint": {
			"window_chain": [
				{"cursor": 8, "frozen_until": 3, "summary_fp": "aaaa"},
				{"cursor": 8, "frozen_until": 3, "summary_fp": "bbbb"},
			]
		},
	}
	finding = next(f for f in rules.check_frozen_head(run) if f.status == CONFIRMED_FAULT)
	assert "折叠区间" in finding.phenomenon


# ---------- 3. 本轮无记录：不得拿会话级 leftovers 定责 ----------


def test_session_scoped_cold_reference_is_not_this_turns_fault() -> None:
	"""采集器标为「不属于本运行」的冷引用不得算成本轮的已确认故障。"""
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	run.transcript_rows = [
		{
			"id": "m9",
			"role": "tool",
			"tool_call_id": "call_other_turn",
			"content_ref": "gone.json",
			"body_state": "missing_blob",
			"locator": r"C:\xeyo\sessions\s1.jsonl",
			"line_no": 4,
			"in_run": False,
		}
	]
	findings = rules.check_cold_references(run)
	assert not [f for f in findings if f.status == CONFIRMED_FAULT], "会话级 leftovers 不是本轮证据"
	assert findings and all(f.status == UNKNOWN for f in findings)
	assert "不带本轮身份" in findings[0].phenomenon


def test_run_scoped_cold_reference_is_still_a_confirmed_fault() -> None:
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	run.transcript_rows = [
		{
			"id": "m9",
			"role": "tool",
			"tool_call_id": "c1",
			"content_ref": "gone.json",
			"body_state": "missing_blob",
			"locator": r"C:\xeyo\sessions\s1.jsonl",
			"line_no": 4,
			"in_run": True,
		}
	]
	assert [f for f in rules.check_cold_references(run) if f.status == CONFIRMED_FAULT]


def test_spill_marker_count_mismatch_is_only_a_lead() -> None:
	"""上游是整串字面量计数：tools/job_tools.py 写的 (earlier output truncated) 天生不带句柄，
	任何一次读后台任务输出都会让两个计数对不上 ⇒ 这条只能是线索，不能当可疑原因。"""
	run = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)],
		projections=[
			{
				"projection_id": "p1",
				"locator": "working:projection",
				"spills": 3,
				"invariant_errors": ["spill_reference_mismatch"],
			}
		],
	)
	findings = [f for f in rules.check_cold_references(run) if "句柄数与" in f.phenomenon]
	assert findings, "旗标仍要作为线索报出来，不能靠沉默消噪"
	f = findings[0]
	assert f.status == UNKNOWN
	assert "标记侧 3 处" in f.phenomenon
	assert "(earlier output truncated)" in f.coverage_gap
	assert "不能据此判定" in f.allowed_conclusion


def test_turn_without_records_yields_only_the_no_record_finding(collect) -> None:
	"""整会话有记录、本轮一条没有：规则集只报本轮无记录，一条故障都不下。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1, "status": "ok"},
		],
		turn_id="t1",
	)
	findings = evaluate_run(run)
	assert [f.rule_id for f in findings] == ["no_turn_records"]
	assert findings[0].status == UNKNOWN
	assert not [f for f in findings if f.status == CONFIRMED_FAULT]


def test_no_record_finding_says_window_may_not_cover_it() -> None:
	"""无记录不等于没发生：措辞必须留下「窗口可能没覆盖」这条事实。"""
	finding = rules.no_turn_records_finding(_run([]))
	assert finding.status == UNKNOWN
	assert "无记录不等于没发生" in finding.coverage_gap


def test_no_record_verdict_blames_nobody_and_shows_no_borrowed_obligation(collect) -> None:
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1}],
		turn_id="t1",
	)
	verdict = attribute_fault(run, evaluate_run(run))
	assert verdict["responsibility"] == UNDETERMINED
	assert verdict["no_turn_records"] is True
	assert verdict["chain"] == [], "无记录的轮次不得有因果链"
	assert verdict["engine_confirmed"] == 0
	assert verdict["environment_confirmed"] == 0
	assert verdict["transport_gap"] is False
	assert verdict["primary_cause"] == "not_determined"
	assert verdict["obligation"]["excerpt"] == "", "不得从会话里借一条用户原话当本轮约束"
	assert "无记录不等于没发生" in verdict["why"]


def test_no_record_verdict_keeps_the_public_shape(collect) -> None:
	"""路由器与界面依赖的键必须一个不少。"""
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1}],
		turn_id="t1",
	)
	verdict = attribute_fault(run, evaluate_run(run))
	for key in (
		"responsibility",
		"responsibility_label",
		"why",
		"primary_cause",
		"primary_cause_label",
		"cause_statement",
		"causes",
		"task_outcome",
		"task_outcome_label",
		"obligation",
		"shown_to_model",
		"shown_to_model_note",
		"engine_confirmed",
		"environment_confirmed",
		"transport_gap",
		"chain",
		"missing_evidence",
		"not_claimed",
	):
		assert key in verdict, key


def test_hand_built_view_is_not_reported_as_no_records() -> None:
	"""没跑过采集的空对象不适用「本轮无记录」：判据是窗口在场而本轮无记录。"""
	run = RunEvidence(session_id="s1", turn_id="t1")
	assert rules.collection_attempted(run) is False
	assert fault_split.no_turn_records(run) is False
	assert attribute_fault(run, [])["no_turn_records"] is False


def test_turn_scoping_drops_rows_attributed_to_another_turn() -> None:
	"""带别的轮次身份的行必须被剔除；不带轮次身份的旧行保留（不削规则）。"""
	kept, foreign, legacy = {"turn_id": "t1"}, {"turn_id": "t2"}, {}
	assert rules.turn_scoped([kept, foreign, legacy], "t1") == [kept, legacy]
	assert rules.turn_scoped([kept, foreign], "") == [kept, foreign]


def test_later_turns_user_message_is_not_this_turns_obligation(tmp_path, monkeypatch) -> None:
	"""被诊断的历史轮不得拿会话里最后一条用户消息当自己的约束。"""
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = [
		'{"id": "m1", "role": "user", "ts": 1.0, "content": "本轮的原话约束"}',
		'{"id": "m2", "role": "assistant", "ts": 2.0, "content": "回话"}',
		'{"id": "m3", "role": "user", "ts": 900.0, "content": "更晚一轮的原话"}',
	]
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	run = _run([_ev(1, "model.started", 10.0, model_request_id="r1", attempt=1)])
	obligation = fault_split._last_user_obligation(run)
	assert obligation["text"] == "本轮的原话约束"
	assert obligation["ts_bound"] is True


def test_obligation_beyond_the_scan_window_says_so(monkeypatch) -> None:
	"""扫描窗够不到本轮那条用户消息时如实报窗口不足，不退化成「这轮没提要求」。"""
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = ['{"id": "m%d", "role": "assistant", "ts": %d, "content": "x"}' % (i, 5000 + i) for i in range(4)]
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	assert fault_split._last_user_obligation(run)["state"] == "outside_scan"


def test_projection_from_a_later_turn_cannot_prove_delivery() -> None:
	"""working 只留整会话最后一份投影：它不属于本轮时既不能说送到也不能说丢了。"""
	run = _run([_ev(1, "model.started", 10.0, model_request_id="r1", attempt=1)])
	run.projections = [{"projection_id": "p9", "created_at": 900.0}]
	assert fault_split._emitted_projection_in_turn(run) is False
	run.projections = [{"projection_id": "p1", "created_at": 9.0}]
	assert fault_split._emitted_projection_in_turn(run) is True
	run.projections = []
	assert fault_split._emitted_projection_in_turn(run) is False


# ---------- 4. 权限结果行的唯一读法 ----------

REAL_READONLY_DENY = {
	"kind": "permission.denied",
	"session_id": "s1",
	"turn_id": "t1",
	"request_id": "call_1",
	"tool_name": "Write",
	"reason": "readonly_mode",
	"permission_action": "deny",
	"permission_rule_id": "agent_mode.readonly",
	"permission_reason_code": "READONLY_MODE",
	"line_no": 7,
}

LEGACY_DENY_WITHOUT_FIELDS = {
	"kind": "permission.denied",
	"session_id": "s1",
	"turn_id": "t1",
	"request_id": "call_2",
	"tool_name": "XeyoUI",
	"reason": "ui_missing_path",
	"matched_rule": "ui_missing_path",
	"line_no": 8,
}


def test_real_deny_rows_count_as_blocked() -> None:
	"""真实 DENY 行既无 approved 也无 outcome：按 kind 与 permission_action 读成挡住。"""
	for row in (REAL_READONLY_DENY, LEGACY_DENY_WITHOUT_FIELDS):
		assert rules.permission_outcome(row) == "denied"
		assert rules.permission_blocked(row) is True
		assert rules.permission_outcome_unrecorded(row) is False


def test_resolved_rows_keep_their_documented_vocabulary() -> None:
	"""取值来自 permissions/store.py 与 engine/permission_coordinator.py，不发明新值。"""
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": True, "outcome": "user_decided"}) == "allowed"
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": False, "outcome": "timeout"}) == "timeout"
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": False, "outcome": "aborted"}) == "aborted"
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": False, "outcome": "user_decided"}) == "denied"
	assert rules.permission_outcome({"kind": "permission.pending", "tool_name": "Write"}) == "unrecorded"
	assert rules.permission_outcome_unrecorded({"kind": "permission.pending"}) is False


def test_row_recording_no_outcome_is_unrecorded_not_allowed() -> None:
	"""结果行什么都不记时只能报未记录，不得读成「已通过」也不得读成「已拒绝」。"""
	bare = {"kind": "permission.resolved", "request_id": "apr1", "tool_name": "Bash", "line_no": 12}
	assert rules.permission_outcome(bare) == "unrecorded"
	assert rules.permission_blocked(bare) is False
	assert rules.permission_outcome_unrecorded(bare) is True


def test_fault_split_uses_the_same_reading_function() -> None:
	"""两侧必须是同一个读法，否则会对同一行得出相反结论。"""
	assert fault_split.permission_outcome is rules.permission_outcome
	assert fault_split.permission_blocked is rules.permission_blocked


def test_rule_reading_and_fault_split_agree_on_a_real_deny_row() -> None:
	"""同一个 DENY 行：规则报挡住，责任划分也报挡住——不再互相矛盾。"""
	run = _run(
		[],
		permissions=[
			{"kind": "permission.pending", "request_id": "apr1", "tool_name": "Bash", "matched_rule": "bash_confirm_ask", "line_no": 6, "ts": 1.0},
			dict(REAL_READONLY_DENY, request_id="apr1"),
		],
	)
	assert [f for f in rules.check_permission_block(run) if f.status == CONFIRMED_FAULT], "拒绝行必须被读成挡住"
	unmet = fault_split._required_action_unmet(run, "改完必须跑 pytest")
	assert unmet["state"] == "blocked_by_permission"
	assert unmet["evidence"]


def test_missing_permission_outcome_is_not_read_as_passed() -> None:
	"""结果行没有结果字段：本轮动作判不了，退回 unknown 而不是「已通过」。"""
	unmet = fault_split._required_action_unmet(
		_run(
			[],
			permissions=[
				{"kind": "permission.resolved", "request_id": "apr1", "tool_name": "Bash", "line_no": 12, "ts": 1.0},
			],
		),
		"改完必须跑 pytest",
	)
	assert unmet["state"] == "permission_outcome_unrecorded"
	assert unmet["evidence"]


def test_unrecorded_permission_outcome_blames_nobody() -> None:
	"""未记录审批结果时不得判模型的错。"""
	run = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)],
		permissions=[{"kind": "permission.resolved", "request_id": "apr1", "tool_name": "Bash", "line_no": 12, "ts": 1.0}],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] != MODEL
	assert any("未记录" in m for m in [verdict["why"], *verdict["missing_evidence"]])


def test_blocked_real_deny_row_is_engine_not_model(monkeypatch) -> None:
	"""只读门的 DENY：归执行层，不归模型没干活。"""
	constraint = "改完必须跑 pytest 再说完成"
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		'{"id": "m1", "role": "user", "ts": 0.5, "content": "%s"}\n' % constraint,
		encoding="utf-8",
	)
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: ('{"c": "%s"}' % constraint, "working.json"))
	run = RunEvidence(
		session_id="s1",
		turn_id="t1",
		windows=[_audit_window()],
		events=[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)],
		permissions=[dict(REAL_READONLY_DENY)],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] == ENGINE
	assert any(s["party"] == ENGINE for s in verdict["chain"])


# ---------- 5. 证据指针与不削规则 ----------


def test_verifier_absence_does_not_borrow_the_working_locator() -> None:
	"""没有 verifier 固定记录时，证据指针不得拿 working.json 冒充 pin。"""
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	run.working = {"locator": r"C:\xeyo\sessions\s1.working.json"}
	finding = next(f for f in rules.check_verifier(run) if f.rule_id == "verifier")
	assert finding.status == UNKNOWN
	assert all(ref.locator == "" for ref in finding.evidence)
	assert all(ref.source == "pin" for ref in finding.evidence)


def test_audit_evidence_still_points_at_the_audit_window() -> None:
	"""防过度修正：审计类结论的指针仍要能回到审计文件。"""
	findings = rules.check_instruction_drift(_snapshot_run())
	assert findings[0].evidence
	assert all(ref.locator == AUDIT_LOCATOR for ref in findings[0].evidence)


def test_no_confirmed_fault_and_no_engine_blame_on_an_ordinary_turn() -> None:
	"""一轮干净的模型请求：不得有任何已确认故障，也不得定责引擎。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1", permission_snapshot_id="perm:a"),
			_ev(2, "model.finished", 1.5, model_request_id="r1", attempt=1, status="ok", projection_id="p1", permission_snapshot_id="perm:a"),
		]
	)
	items = evaluate_run(run)
	assert [f for f in items if f.status == CONFIRMED_FAULT] == []
	verdict = attribute_fault(run, items)
	assert verdict["responsibility"] == UNDETERMINED
	assert verdict["engine_confirmed"] == 0


def test_rules_never_emit_directive_wording() -> None:
	"""模型可见文本纪律：只报事实，不出现「应该 / 建议 / 不要再」。"""
	banned = ("应该", "建议你", "请优先", "不要再")
	probe_runs = (_snapshot_run(), _projection_run([], _fold_window()), _run([]))
	for rule in rules.RULES:
		for probe in probe_runs:
			for finding in rule.check(probe):
				assert isinstance(finding, Finding)
				blob = " ".join((finding.phenomenon, finding.impact, finding.coverage_gap, finding.allowed_conclusion))
				assert not any(word in blob for word in banned), (rule.rule_id, blob)
