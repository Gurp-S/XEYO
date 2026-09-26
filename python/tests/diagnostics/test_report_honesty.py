"""用量口径的诚实性：有账无价、无账、尾窗截断都不能写成确定的合计。

回归的是真实数据普查里的一类缺陷：``float(row.get("cost_cny") or 0.0)``
把「这条尝试没有价格」悄悄算成 0 元并计入 priced，导出的 Markdown 于是写
「已结束尝试均有用量账 / 估算合计：1.44」，而那 1.44 已经少了几笔。
"""

from __future__ import annotations

from diagnostics.report import build_report, to_markdown, usage_summary

_FINISHED = [
	{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
	{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
]


def _usage_window(run):
	return next((w for w in run.windows if w.source == "usage"), None)


def test_usage_row_without_price_is_not_priced(collect) -> None:
	run = collect(_FINISHED)
	run.usage_rows = [{"attempt_key": "r1#1", "cost_source": "estimate"}]
	summary = usage_summary(run)
	assert summary["priced_attempts"] == 0
	assert summary["unpriced_attempts"] == 1
	assert summary["unknown_cost_attempts"] == 0
	assert summary["estimated_total_cny"] == 0.0
	assert summary["total_is_partial"] is True
	assert "费用未知" in summary["statement"]


def test_non_numeric_price_is_not_counted_as_zero(collect) -> None:
	run = collect(_FINISHED)
	run.usage_rows = [{"attempt_key": "r1#1", "cost_cny": "", "cost_source": "estimate"}]
	summary = usage_summary(run)
	assert summary["priced_attempts"] == 0
	assert summary["unpriced_attempts"] == 1
	assert "未计入合计" in summary["statement"]


def test_markdown_cites_the_evidence_behind_a_cause(collect) -> None:
	"""定责的原因在导出里也要指回原始记录：指针只留在结构体里等于没给读者。

	同文件的 Markdown 自己写着「无原始证据（因此不下定责结论）」，原因栏此前只印句子。
	总数按 ``evidence_total`` 说：随附的指针只有前 6 条，写"共 6 条"就是把截断说成完整。
	"""
	from diagnostics.identity import CONFIRMED_FAULT, EvidenceRef, Finding

	refs = [EvidenceRef(source="audit", locator="audit.jsonl", ref_id=f"L{i}", detail="tool.finished") for i in range(1, 10)]
	finding = Finding(
		rule_id="tool_failure",
		rule_version=1,
		phenomenon="工具 Bash 返回错误（error_kind=INTERNAL，共 9 次）",
		boundary="tool_permission",
		component="工具执行：Bash",
		status=CONFIRMED_FAULT,
		evidence=refs,
		impact="失败步骤已定位。",
		coverage_gap="审计不含 stderr。",
		allowed_conclusion="可确认工具在这一步失败。",
	)
	run = collect(_FINISHED)
	markdown = to_markdown(build_report(run, [finding]))
	lines = markdown.splitlines()
	# 断言必须钉在"这一条原因下面那一行"上：只查整篇里有没有「证据：」「另 N 条」，
	# 结论明细那一段本来就印证据，门会替导出把空位填上（我第一版就是这么假绿的）。
	at = next(i for i, ln in enumerate(lines) if ln.strip().startswith("- [") and "工具执行返回错误" in ln)
	cited = lines[at + 1]
	assert cited.startswith("    证据：audit:L1 "), cited
	assert "另 6 条" in cited, "总数要说 9 条里的另 6 条，不是随附的 6 条样本"


def test_partial_price_in_a_multi_row_attempt_still_counts_the_priced_part(collect) -> None:
	run = collect(_FINISHED)
	run.usage_rows = [
		{"attempt_key": "r1#1", "cost_cny": 0.25, "cost_source": "estimate"},
		{"attempt_key": "r1#1", "cost_source": "estimate"},
	]
	summary = usage_summary(run)
	assert summary["priced_attempts"] == 1
	assert summary["estimated_total_cny"] == 0.25


def test_truncated_usage_window_says_so(collect) -> None:
	run = collect(_FINISHED)
	run.usage_rows = [{"attempt_key": "r1#1", "cost_cny": 0.25, "cost_source": "estimate"}]
	window = _usage_window(run)
	assert window is not None
	# 账本文件根本不在：说「没有用量账本」，不是说尾窗截断。
	window.present = False
	window.complete = False
	absent = usage_summary(run)
	assert absent["usage_window_present"] is False
	assert "没有可用的用量账本" in absent["statement"]
	assert "尾窗" not in absent["statement"]
	window.present = True
	window.complete = True
	baseline = usage_summary(run)
	assert baseline["statement"] == "已结束尝试均有用量账。"
	assert baseline["usage_window_complete"] is True
	assert baseline["total_is_partial"] is False
	window.complete = False
	truncated = usage_summary(run)
	assert truncated["usage_window_complete"] is False
	assert truncated["total_is_partial"] is True
	assert "尾窗" in truncated["statement"]


def test_markdown_total_reads_as_unknown_when_nothing_is_priced(collect) -> None:
	run = collect(_FINISHED)
	run.usage_rows = [{"attempt_key": "r1#1", "cost_source": "estimate"}]
	doc = build_report(run)
	md = to_markdown(doc)
	assert "估算合计：费用未知" in md
	assert "有账无价 1" in md
	assert "估算合计：0.0" not in md


def test_markdown_states_how_many_attempts_back_the_total(collect) -> None:
	run = collect(_FINISHED)
	run.usage_rows = [{"attempt_key": "r1#1", "cost_cny": 0.25, "cost_source": "estimate"}]
	window = _usage_window(run)
	window.present = True
	window.complete = True
	md = to_markdown(build_report(run))
	assert "估算合计：0.25（已依据 1 次尝试）" in md
	assert "计价口径：按 usage 估算" in md
	assert "有价 1 · 无账 0 · 有账无价 0" in md


def test_attribution_never_calls_a_boundary_confirmed_normal(collect) -> None:
	"""边界只有"这里读到了记录"这一个事实，规则集证明不了它正常。

	旧措辞把 present && evidence_count>0 写成「最后一个已确认正常边界」，与本模块顶部
	那条纪律（不得把「没发现异常」读成「没有异常」）自相矛盾：13 条规则没有一条能给
	某条边界发"正常"合格证。机器键名一并改掉 —— 叫 last_normal_* 会被下游当成
	已确认的结论继续用。
	"""
	from diagnostics.identity import CONFIRMED_FAULT, EvidenceRef, Finding
	from diagnostics.report import attribution

	run = collect(_FINISHED)
	finding = Finding(
		rule_id="tool_failure",
		rule_version=1,
		phenomenon="工具失败",
		boundary="tool_permission",
		component="测试组件",
		status=CONFIRMED_FAULT,
		evidence=[EvidenceRef(source="audit", locator="audit.jsonl", ref_id="L4", detail="tool.finished is_error=true")],
		coverage_gap="测试夹具",
		allowed_conclusion="测试夹具",
	)
	att = attribution(run, [finding])
	assert att["first_anomaly_boundary"] == "tool_permission"
	assert att["last_evidenced_boundary"] == "model_request"
	assert "last_normal_boundary" not in att and "last_normal_label" not in att
	# 旧断言写成 "已确认正常" not in statement 会自我打脸：新句子里带着
	# "不等于已确认正常"这句限定。要禁的是"把它当结论"的那种说法。
	assert "已确认正常边界" not in att["statement"]
	assert "不等于已确认正常" in att["statement"]
	assert "有记录" in att["statement"]
	assert "已确认正常" not in att["last_evidenced_label"]
	md = to_markdown(build_report(run, [finding]))
	assert "已确认正常边界" not in md
	assert "最近一个有记录的边界" in md
	assert "有记录不等于已确认正常" in md
