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
