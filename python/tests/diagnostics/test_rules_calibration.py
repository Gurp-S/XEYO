"""真实数据普查确认到的误归因与作用域缺陷的回归集。

对应 2026-09-25 对十条真实回合的普查（设计文档第 6 节的不对称判据）：

1. ``permission_snapshot_id`` 一个轮里出现多个取值曾被写成 ``confirmed_fault``，
   而授权增删本身就会合法地改变快照 id；进一步实测（同批 40 轮）发现它是**写入瞬间**
   的 ambient 身份 —— 27/40 轮里同一个 ``model_request_id`` 的两次写入就带着不同 id，
   于是它连"未定"都判不了，已从漂移比较里退出，改由采集层说明量具粒度。
2. ``frozen_head`` 把「本轮折叠账本为空」当成「没折叠过」——折叠事件按会话写、
   行内不带轮次身份，空的折叠集合证明不了任何事；而它衡量「本轮有几个不同投影」
   的前提本身是空的（投影 = 整份消息列表的哈希，一枪一个，28/28 命中轮次都能被
   "这一轮不止一枪"解释）。该规则已重新指向可核对的不变量。
3. 一个根本不存在的轮次会拿到 ``confirmed_fault`` + 引擎定责，证据来自同会话
   别处的 transcript 行与会话级 leftovers；
4. 真实 DENY 审计行（``tools/tool_registry.py`` 的只读门与策略 DENY）既不带
   ``approved`` 也不带 ``outcome``，被责任划分读成「没挡住」；
5. 折叠与验收的证据指针指向别的来源的文件（拿审计窗口路径冒充 usage 账本、
   拿 working.json 路径冒充 pin）；
6. 投影里 ``full output:`` 与 ``output truncated`` 两个字面量的计数不等被写成"可疑原因"，
   而 ``tools/job_tools.py`` 的 ``(earlier output truncated)`` 天生不带句柄 ⇒ 健康运行也会命中；
   先降到未定，再把上游判据换成"截断声明必须带可回读句柄"（engine/projection_manifest.py，
   #29）之后回到可疑档 —— 本文件钉的是新形状，不是旧计数；
7. ``model.finished`` 的 ``aborted`` / ``retry`` 被一律写成"已确认厂商或传输故障"——
   前者来自引擎的 Aborted 分支（用户停止），后者是设计里的下一步。
   2026-09-25 对最近 40 个真实轮次复跑：该规则 24 条"已确认"里有 9 条属于这两类。
8. 不带 ``request_id`` 的账本行被写成**本轮**结论，但账本行没有轮次身份：同会话的
   每一轮都报同一行（真实数据 37/40 轮、13 个轮次的消息字字相同）。作用域错位的
   事实改由采集缺项承担，笔数仍留在报告侧。

纠正的底线：规则要么判对，要么 ``unknown`` 并写明缺哪条记录，不得靠沉默消噪。
"""

from __future__ import annotations

import json

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


# ---------- 1. 快照标识：不是请求身份，退出漂移比较 ----------


def _snapshot_run() -> RunEvidence:
	return _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, permission_snapshot_id="perm:aaaa"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, permission_snapshot_id="perm:bbbb"),
			_ev(3, "model.started", 3.0, model_request_id="r3", attempt=1, permission_snapshot_id="perm:cccc"),
		]
	)


def test_snapshot_id_multiplicity_is_not_a_drift_finding() -> None:
	"""快照 id 不是请求级身份 ⇒ 不再进漂移比较（既不判"已确认"，也不再判"未定"）。
	实测（最近 40 个真实轮次）：32/40 轮的 model.* 行带着 ≥2 个快照 id，其中 27/40 轮
	是同一个 model_request_id 的两次写入就用了不同 id。这不是故障的形状，是量具粒度。"""
	findings = rules.check_instruction_drift(_snapshot_run())
	assert findings == []


def test_snapshot_split_is_reported_as_a_measurement_limit(collect) -> None:
	"""事实要说，但说在采集层：缺项必须点名这个字段与它的来源，且只在真看到分裂时出现。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "permission_snapshot_id": "perm:aaaa"},
			{"ts": 1.4, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok", "permission_snapshot_id": "perm:bbbb"},
		]
	)
	gaps = [g for g in run.gaps if g.boundary == "instruction_context" and g.reason == "not_comparable"]
	assert gaps, "同一逻辑调用带着两个快照身份，必须说清这一级判不了"
	assert "permission_snapshot_id" in gaps[0].detail
	assert "写入瞬间" in gaps[0].detail


def test_single_snapshot_id_per_request_does_not_trigger_the_gap(collect) -> None:
	"""反面对照：一轮里每个逻辑调用各自一个快照身份（哪怕彼此不同）也不发这条缺项。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "permission_snapshot_id": "perm:aaaa"},
			{"ts": 2.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1, "permission_snapshot_id": "perm:bbbb"},
		]
	)
	assert [g for g in run.gaps if g.reason == "not_comparable"] == []


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


# ---------- 2. 冻结头：投影按枪数变化是常态，只有重发换面才是信号 ----------


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


def test_projection_changing_between_shots_is_not_a_signal() -> None:
	"""一枪一个投影是构造上的必然（投影 = 整份消息列表的哈希，projection_manifest:98）。
	真实数据 40 轮里旧前提命中 28 轮，而这 28 轮的不同投影数全都 ≤ 本枪数 ⇒ 前提只
	等价于"这一轮不止一枪"。所以三个不同调用各带一个新投影：不得产出任何冻结头结论。
	"折叠账本对本会话零记录"这一事实改由采集层说（见 test_collect_integrity 的 no_records）。"""
	assert rules.check_frozen_head(_projection_run([], _fold_window())) == []


def test_populated_fold_ledger_does_not_make_multi_shot_turn_suspicious() -> None:
	"""账本完整且有行也不改变结论：可疑级原先同样建立在"本轮多个投影"这个空前提上。"""
	run = _projection_run(
		[
			{"session_id": "s1", "fold": True, "reason": "worth_fold", "line_no": 3, "locator": FOLD_LOCATOR},
			{"session_id": "s1", "fold": False, "reason": "pays_back_too_slow", "line_no": 4, "locator": FOLD_LOCATOR},
		],
		_fold_window(complete=True, rows_matched=2),
	)
	assert rules.check_frozen_head(run) == []


def test_retry_that_changes_projection_is_suspected() -> None:
	"""重新指向真正的不变量：同一个逻辑调用的两次尝试换了字节面。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1"),
			_ev(2, "model.finished", 1.4, model_request_id="r1", attempt=1, status="retry", projection_id="p1"),
			_ev(3, "model.started", 2.0, model_request_id="r1", attempt=2, projection_id="p2"),
		]
	)
	findings = rules.check_frozen_head(run)
	assert len(findings) == 1
	assert findings[0].status == SUSPECTED_CAUSE
	assert "r1" in findings[0].phenomenon
	assert findings[0].evidence
	for ref in findings[0].evidence:
		assert ref.source == "audit"
		assert ref.locator == AUDIT_LOCATOR
		assert FOLD_LOCATOR not in ref.locator, "折叠账本没参与这条结论，指针不得指它"


def test_retry_with_identical_projection_is_silent() -> None:
	"""反面对照：重发同一份投影必须零结论，规则不能恒真。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1"),
			_ev(2, "model.finished", 1.4, model_request_id="r1", attempt=1, status="retry", projection_id="p1"),
			_ev(3, "model.started", 2.0, model_request_id="r1", attempt=2, projection_id="p1"),
		]
	)
	assert rules.check_frozen_head(run) == []


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


def test_truncation_claim_without_handle_is_a_suspicion() -> None:
	"""旗标含义已收窄（engine 侧 #29）：只在"截断声明拿不到回读句柄"时为真。

	旧判据是两个字面量的全局计数比大小，(earlier output truncated) 与 Bash 的
	[output truncated, full at …] 天生不带 "full output:" ⇒ 真实数据 26/40 轮被误判，
	那条只能停在未定。现在它说的是原文读不回来，可以进可疑档。
"""
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
	findings = [f for f in rules.check_cold_references(run) if "回读句柄" in f.phenomenon]
	assert findings, "旗标仍要作为结论报出来，不能靠沉默消噪"
	f = findings[0]
	assert f.status == SUSPECTED_CAUSE
	assert "3 个可回读句柄" in f.phenomenon
	assert "不能据此判定是哪个工具" in f.allowed_conclusion


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


def test_unanswered_permission_wait_is_not_a_confirmed_fault() -> None:
	"""授权等待没人答复（outcome=timeout）或中止：执行层的 fail-closed 结果，不是产品故障。

	engine/permission_coordinator.py::wait 在超时那一刻自己写 approved=False +
	outcome="timeout"；aborted 来自 engine/abort.py 的停止分支。
	分层普查 57 个真实轮次里，该规则 7 条"已确认"全部是 timeout —— 与它自己
	「不得把预期拒绝计成产品故障」的口径矛盾。事实要留住（仍算被权限挡住），档位要落对。
	"""
	timeout_row = {
		"kind": "permission.resolved",
		"request_id": "apr9",
		"tool_name": "Bash",
		"approved": False,
		"outcome": "timeout",
		"user_choice": "deny",
		"reason": "timeout",
		"matched_rule": "bash_default_ask",
		"line_no": 21,
		"ts": 2.0,
	}
	assert rules.permission_outcome(timeout_row) == "timeout"
	assert rules.permission_blocked(timeout_row) is True, "事实层：这一枪确实没执行"

	run = _run(
		[],
		permissions=[
			{"kind": "permission.pending", "request_id": "apr9", "tool_name": "Bash", "matched_rule": "bash_default_ask", "line_no": 20, "ts": 1.0},
			timeout_row,
		],
	)
	findings = rules.check_permission_block(run)
	assert findings
	assert all(f.status == UNKNOWN for f in findings), [f.status for f in findings]
	text = findings[0].phenomenon + findings[0].allowed_conclusion
	assert "timeout" in text and "Bash" in text
	assert not [f for f in findings if f.status == CONFIRMED_FAULT]


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


def test_verifier_absence_is_a_gap_not_a_per_turn_finding(collect) -> None:
	"""没有 verifier 固定记录：以前每轮都产出一条 unknown（真实数据 40/40），
	把"未定"桶占满；现在它是采集缺项，不是一条待判结论。
	原意图一并保留：没有 pin 就绝不产生一条带伪证据指针的结论。"""
	run = collect([{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}])
	assert rules.check_verifier(run) == []
	assert [f for f in evaluate_run(run) if f.rule_id == "verifier"] == []
	gaps = [g for g in run.gaps if g.boundary == "file_verifier" and g.reason == "not_recorded"]
	assert gaps, "缺席事实要留在缺项清单里"
	assert "kind=verifier" in gaps[0].detail


def test_unlinked_usage_rows_are_a_session_gap_not_a_per_turn_finding(collect) -> None:
	"""账本行不带 request_id ⇒ 行内没有轮次身份，归属只到"会话 + 尾窗"。
	以前它被写成一条本轮结论，同会话每一轮都报同一行（真实数据 37/40 轮、
	其中 sess_mu9 的 13 个轮次报的都是同一 line_no）。事实不删，换个正确的层级说。"""
	from diagnostics.report import usage_summary
	from usage.ledger import events_path, record_from_openai_usage

	record_from_openai_usage(  # 旁路调用：没有 _meta_request_id ⇒ 行里不写 request_id
		provider="deepseek",
		model="deepseek-chat",
		api_key="sk-x",
		usage={"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
		session_id="s1",
	)
	row = json.loads(events_path().read_text(encoding="utf-8").splitlines()[-1])
	assert "request_id" not in row, "样本必须是真正的无归属行"
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}]
	)
	assert run.usage_rows, "无归属行仍要被采集，否则后面都是空谈"
	assert [f for f in evaluate_run(run) if f.rule_id == "usage_accounting"] == []
	gaps = [g for g in run.gaps if g.boundary == "model_request" and g.reason == "unattributed_rows"]
	assert gaps, "笔数要留在缺项清单里"
	assert "1 笔" in gaps[0].detail
	assert "无法归轮" in gaps[0].detail, "措辞必须点明作用域只到会话"
	assert usage_summary(run)["unlinked_usage_rows"] == 1, "报告侧的笔数不能一起丢掉"


def test_audit_evidence_still_points_at_the_audit_window() -> None:
	"""防过度修正：审计类结论的指针仍要能回到审计文件。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, tool_schema_hash="h1"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, tool_schema_hash="h2"),
		]
	)
	findings = rules.check_instruction_drift(run)
	assert findings
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


# ---------- 7. 中止与重试不是厂商故障 ----------


def _attempt_rows(*statuses: str) -> list[dict]:
	"""按 (started, finished) 成对造审计行；statuses[i] 是第 i+1 次尝试的结束状态。"""
	rows: list[dict] = []
	ts = 1.0
	for i, st in enumerate(statuses, start=1):
		rows.append({"ts": ts, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": i})
		ts += 0.1
		if st:
			rows.append({"ts": ts, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": i, "status": st})
			ts += 0.1
	return rows


def _psf(run) -> list:
	return [f for f in rules.check_provider_stream(run) if f.rule_id == "provider_stream_failure"]


def test_user_abort_is_not_a_confirmed_provider_fault(collect) -> None:
	"""engine/query_loop.py 的 except Aborted 分支写 status=aborted：那是用户停止，
	定责到厂商或传输边界就是误归因（真实数据里 40 轮出现 7 次）。"""
	run = collect(_attempt_rows("ok", "aborted"))
	findings = _psf(run)
	assert len(findings) == 1
	f = findings[0]
	assert f.status == UNKNOWN
	assert "Aborted" in f.coverage_gap
	assert "不能据此判定模型或引擎出错" in f.allowed_conclusion


def test_retry_with_a_later_attempt_leaves_no_finding(collect) -> None:
	"""重试是设计里的下一步：后面还有尝试在跑时，中间那条 retry 不该留下"已确认故障"。"""
	run = collect(_attempt_rows("retry", "ok"))
	assert _psf(run) == []


def test_retry_as_the_last_attempt_is_undetermined(collect) -> None:
	run = collect(_attempt_rows("retry"))
	findings = _psf(run)
	assert len(findings) == 1
	assert findings[0].status == UNKNOWN
	assert "没有后续尝试记录" in findings[0].phenomenon
	assert "不能据此判定请求失败" in findings[0].allowed_conclusion


def test_protocol_fallback_stays_confirmed_but_not_blaming_prompt(collect) -> None:
	"""请求形状被厂商拒过、引擎降级重打：这确实是适配器边界的故障（白多一次请求），
	但不能读成提示词内容错误。"""
	run = collect(_attempt_rows("protocol_fallback"))
	findings = _psf(run)
	assert len(findings) == 1
	f = findings[0]
	assert f.status == CONFIRMED_FAULT
	assert "白多一次请求" in f.allowed_conclusion
	assert "不能据此判定提示词内容错误" in f.allowed_conclusion


def test_plain_failure_is_still_confirmed(collect) -> None:
	"""正向守卫：status=failed 不许被一起放宽掉。"""
	run = collect(_attempt_rows("failed"))
	findings = _psf(run)
	assert len(findings) == 1
	assert findings[0].status == CONFIRMED_FAULT
