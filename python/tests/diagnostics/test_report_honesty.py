"""用量口径的诚实性：有账无价、无账、尾窗截断都不能写成确定的合计。

回归的是真实数据普查里的一类缺陷：``float(row.get("cost_cny") or 0.0)``
把「这条尝试没有价格」悄悄算成 0 元并计入 priced，导出的 Markdown 于是写
「已结束尝试均有用量账 / 估算合计：1.44」，而那 1.44 已经少了几笔。
"""

from __future__ import annotations

from diagnostics.report import build_report, to_markdown, usage_summary
from diagnostics.rules import evaluate_run

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


def test_version_line_does_not_claim_the_version_that_produced_the_records(collect) -> None:
	"""版本那行只能说"出报告的进程"：记录行里没有版本字段，跨构建时后者无从证明。

	真实背景（#66）：release 构建跑的是打包资源里的引擎快照，盘上那份是 09-05 的，
	而报告里的 commit 来自当前树 —— 写"运行版本"就是给读者一个会对错的号。
	"""
	run = collect(_FINISHED)
	markdown = to_markdown(build_report(run))
	assert "运行版本" not in markdown
	assert "代码版本（出这份报告的进程）" in markdown
	assert "不能当成产生这些记录的引擎版本" in markdown


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


def test_no_sentence_promises_transcript_readback_when_it_is_absent(collect) -> None:
	"""把 09-27 的负结果变成长期门：没有转录的那份报告里，凡许诺"去 transcript 回读"的句子都得是拒绝句。

	抽样 55 个真实会话、81 条提到转录的句子：指向不存在转录的肯定句 0 条，
	21 条命中全是否定句（#74 的缺项措辞 + #85 的 impact 分支）。这个形状不能只靠一次普查守住——
	#85 之前那句 impact 是常量「结果正文按需在 transcript 里回读。」，对 36% 的失败行都是假话。
	"""
	import re

	NEG = ("不可", "无法", "不存在", "没有", "未取回", "无从", "读不出")
	MENTIONS = re.compile(r"transcript|转录")
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash"},
			{"ts": 1.2, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "is_error": True, "error_kind": "INTERNAL"},
		]
	)
	tr = run.window("transcript")
	assert tr is not None and tr.present is False, "夹具没造出「转录不存在」的形状，这条门在空转"
	said = [("gap:" + g.reason, g.detail) for g in run.gaps]
	for f in evaluate_run(run):
		said += [(f"finding.{fld}:{f.rule_id}", getattr(f, fld)) for fld in ("phenomenon", "impact", "coverage_gap", "allowed_conclusion")]
	said += [("markdown", line) for line in to_markdown(build_report(run)).splitlines()]
	mentioned = [(w, t) for w, t in said if t and MENTIONS.search(t)]
	assert mentioned, "一条提到 transcript 的句子都没有 —— 这条门在空转"
	bad = [(w, t) for w, t in mentioned if not any(n in t for n in NEG)]
	assert not bad, f"这些句子许诺去转录回读，可这份报告没有转录：{bad[:4]}"


def test_diagnostics_strings_cite_design_doc_sections_or_hardcoded_chain_lengths() -> None:
	"""GUI 侧那条"正文不许引用设计稿编号 / 不许写死定位链级数"的门，后端也得有。

	读者能看到的句子有一半是 python 拼出来的（Markdown 导出、CLI 输出、缺项正文）。
	只在界面扫等于给这条纪律留了一扇没锁的门。用 ast 走字符串字面量而不是正则扫源码：
	注释与 docstring 里的 § 会误报，而注释不是读者看到的句子。
	"""
	import ast
	import re
	from pathlib import Path

	root = Path(__file__).resolve().parents[2] / "diagnostics"
	pattern = re.compile(r"§|(?:七|六|八|九|十|[1-9])\s*级")
	files = sorted(root.glob("*.py"))
	assert len(files) > 8, files
	seen_strings = 0
	seen_docstrings = 0
	for path in files:
		tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
		for node in ast.walk(tree):
			if isinstance(node, ast.Constant) and isinstance(node.value, str):
				if len(node.value) > 40:
					seen_docstrings += 1
				seen_strings += 1
				hit = pattern.search(node.value)
				assert not hit, f"{path.name}:{node.lineno} 读者可见正文里出现 {hit.group(0)!r}：…{node.value[:80]}…"
	# 反空转： walker 没读到足够多的字符串 = 这条门什么都没看
	assert seen_strings > 400, seen_strings
	assert seen_docstrings > 60, seen_docstrings
