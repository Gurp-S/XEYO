"""同一份诊断结构输出 JSON / Markdown。不调用模型，不做加权总分。

费用一律标「按 usage 估算」：只有拿到真实账单才允许出现别的措辞。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from diagnostics import store
from diagnostics.collect import BOUNDARIES, RunEvidence
from diagnostics.fault_split import (
	OUTCOME_LABEL,
	PARTY_LABEL,
	attribute_fault,
	shown_to_model_label,
)
from diagnostics.identity import (
	CONFIRMED_FAULT,
	SCHEMA_VERSION,
	SUSPECTED_CAUSE,
	UNKNOWN,
	gap_reason_text,
	Finding,
	_s,
	request_key,
)
from diagnostics.rules import evaluate_run

_BOUNDARY_ORDER = [name for name, _label in BOUNDARIES]
_BOUNDARY_LABEL = dict(BOUNDARIES)

_STATUS_LABEL = {
	CONFIRMED_FAULT: "已确认",
	SUSPECTED_CAUSE: "疑似",
	UNKNOWN: "未定",
}


def _label(name: str) -> str:
	return _BOUNDARY_LABEL.get(name, name)


def _row_cost(row: dict[str, Any]) -> float | None:
	"""用量行的价格；缺字段/非数值一律 ``None``，不按 0 计入。"""
	raw = row.get("cost_cny")
	if raw is None or isinstance(raw, bool):
		return None
	try:
		return float(raw)
	except (TypeError, ValueError):
		return None


def usage_summary(run: RunEvidence) -> dict[str, Any]:
	"""按请求与重试汇总用量；缺账的尝试计入 unknown，不计入 0。"""
	attempts = 0
	priced: list[str] = []
	unpriced: list[str] = []
	unknown: list[str] = []
	total = 0.0
	sources: set[str] = set()
	for mr in run.model_requests:
		for att in mr.attempts:
			if _s(att.get("kind")) != "model.finished":
				continue
			key = request_key(mr.model_request_id, att.get("attempt"))
			attempts += 1
			rows = [row for row in run.usage_rows if _s(row.get("attempt_key")) == key]
			if not rows:
				unknown.append(key)
				continue
			costs = [cost for cost in (_row_cost(row) for row in rows) if cost is not None]
			for row in rows:
				source = _s(row.get("cost_source"))
				if source:
					sources.add(source)
			if not costs:
				# 有用量行却没有可依据的价：这条尝试的费用未知，合计也不含它。
				unpriced.append(key)
				continue
			total += sum(costs)
			priced.append(key)
	usage_window = run.window("usage")
	window_complete = bool(usage_window) and usage_window.complete
	window_present = bool(usage_window) and getattr(usage_window, "present", True)
	unlinked = [row for row in run.usage_rows if not _s(row.get("attempt_key"))]
	notes: list[str] = []
	if unknown:
		notes.append(
			f"{len(unknown)} 次已结束的尝试没有用量账：费用未知，未按 0 计入。"
		)
	if unpriced:
		notes.append(
			f"{len(unpriced)} 次尝试有用量行但行内没有可用价格：费用未知，未计入合计。"
		)
	if not window_present:
		notes.append("本机没有可用的用量账本文件：费用未知，未按 0 计入。")
	elif not window_complete:
		notes.append("用量账本按尾窗读取，更早的账本行未纳入本次统计。")
	if not notes:
		notes.append("已结束尝试均有用量账。")
	return {
		"finished_attempts": attempts,
		"priced_attempts": len(priced),
		"unknown_cost_attempts": len(unknown),
		"unknown_cost_keys": unknown[:20],
		"unpriced_attempts": len(unpriced),
		"unpriced_keys": unpriced[:20],
		"estimated_total_cny": round(total, 8),
		"total_is_partial": bool(unknown or unpriced) or not window_complete,
		"usage_window_complete": window_complete,
		"usage_window_present": window_present,
		"cost_basis": "按 usage 估算" if sources else "无可依据的用量",
		"cost_sources": sorted(sources),
		"unlinked_usage_rows": len(unlinked),
		"statement": "".join(notes),
	}


def attribution(run: RunEvidence, findings: list[Finding]) -> dict[str, Any]:
	"""首个已确认异常的边界，以及它之前最近一个**有记录**的边界；无证据就说无法归因。

	这里刻意不说"已确认正常"：本函数能证明的只有"这条边界上读到了记录、且规则集没在
	它上面判出已确认异常"。"没判出异常"不是"合格证"——13 条规则盖不住的部分恰恰是
	多数边界平时的状态。字段名也跟着改，免得下游拿 last_normal_* 当已确认结论继续用。
	"""
	confirmed = [f for f in findings if f.status == CONFIRMED_FAULT]
	suspected = [f for f in findings if f.status == SUSPECTED_CAUSE]
	present = {b["name"] for b in run.boundaries() if b["present"] and b["evidence_count"] > 0}
	bad = {f.boundary for f in confirmed}
	first_anomaly = next((name for name in _BOUNDARY_ORDER if name in bad), "")
	normal = ""
	if first_anomaly:
		rank = _BOUNDARY_ORDER.index(first_anomaly)
		for name in reversed(_BOUNDARY_ORDER[:rank]):
			if name in present:
				normal = name
				break
	else:
		for name in reversed(_BOUNDARY_ORDER):
			if name in present:
				normal = name
				break
	if confirmed:
		statement = (
			f"首个已确认异常边界：{_label(first_anomaly)}；"
			f"它之前最近一个有记录的边界：{_label(normal) if normal else '无（更早的边界连记录都没有）'}"
			"（有记录只说明那里读到了东西，不等于已确认正常）。"
			"已确认的是记录里的不变量被破坏，不是任务失败的全部原因。"
		)
	elif suspected:
		statement = "只有疑似信号，无已确认异常边界；不下定责结论。"
	else:
		statement = (
			"本次规则集未发现已确认异常。这不等于任务正确："
			"未采集的边界与规则覆盖不到的逻辑错误不在报告范围内。"
		)
	return {
		"first_anomaly_boundary": first_anomaly,
		"first_anomaly_label": _label(first_anomaly) if first_anomaly else "",
		"last_evidenced_boundary": normal,
		"last_evidenced_label": _label(normal) if normal else "",
		"confirmed_count": len(confirmed),
		"suspected_count": len(suspected),
		"unknown_count": len([f for f in findings if f.status == UNKNOWN]),
		"attributed": bool(first_anomaly),
		"statement": statement,
	}


def build_report(run: RunEvidence, findings: list[Finding] | None = None) -> dict[str, Any]:
	items = evaluate_run(run) if findings is None else list(findings)
	doc = run.to_dict(include_rows=False)
	doc.update(
		{
			"schema_version": SCHEMA_VERSION,
			"generated_at": round(time.time(), 3),
			"findings": [f.to_dict() for f in items],
			"attribution": attribution(run, items),
			"fault": attribute_fault(run, items),
			"usage_summary": usage_summary(run),
			"evidence_rows": len(run.events_for_turn()),
			"pin_count": len(run.pins),
		}
	)
	return doc


def report_id(doc: dict[str, Any]) -> str:
	raw = f"{_s(doc.get('session_id'))}|{_s(doc.get('turn_id'))}|{doc.get('generated_at')}"
	return "rep_" + hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


def to_json(doc: dict[str, Any]) -> str:
	return json.dumps(doc, ensure_ascii=False, indent=2)


def save_report(doc: dict[str, Any]) -> str:
	store.ensure_dirs()
	ident = report_id(doc)
	path = store.reports_dir() / f"{ident}.json"
	store.write_json(path, {"report_id": ident, **doc})
	store.enforce_quota()
	return str(path)


def load_report(ident: str) -> dict[str, Any] | None:
	return store.read_json(
		store.artifact_path(
			store.reports_dir(), _s(ident), suffix=".json", label="report_id"
		)
	)


def _window_status(window: dict[str, Any]) -> str:
	"""四种覆盖结局要分开说：读全了 / 根本没有这个来源 / 尾窗截断 / 读了但丢了行。"""
	if window.get("complete"):
		return "完整"
	if not window.get("present", True):
		return "来源缺失"
	if window.get("truncated"):
		return "尾窗截断"
	return "有行未纳入"


def _short(refs: list[dict[str, Any]], cap: int = 3, total: int | None = None) -> str:
	parts: list[str] = []
	for ref in refs[:cap]:
		detail = _s(ref.get("detail"))[:60]
		entry = f"{_s(ref.get('source'))}:{_s(ref.get('ref_id'))}"
		parts.append(f"{entry} {detail}" if detail else entry)
	full = len(refs) if total is None else max(int(total), len(refs))
	if full > cap:
		parts.append(f"…另 {full - cap} 条")
	return "；".join(parts)


def cause_evidence_text(cause: dict[str, Any]) -> str:
	"""一条原因的证据摘要：随附的指针只有前几条，总数按 ``evidence_total`` 说。

	没有证据时返回空串 —— 调用方据此不印空行（"这条没有依据"由"不能证明"那一栏说）。
	"""
	refs = cause.get("evidence") or []
	if not isinstance(refs, list) or not refs:
		return ""
	total = cause.get("evidence_total")
	return _short(refs, cap=3, total=total if isinstance(total, int) else None)


def to_markdown(doc: dict[str, Any]) -> str:
	"""人读版本：每项结论都能回到原始记录；无证据不定责。"""
	lines: list[str] = ["# XEYO 诊断报告", ""]
	versions = doc.get("versions") or {}
	lines.append(f"- 会话：`{_s(doc.get('session_id')) or '—'}`")
	lines.append(f"- 轮次：`{_s(doc.get('turn_id')) or '整会话'}`")
	lines.append(f"- 生成时间：{doc.get('generated_at')}")
	lines.append(
		"- 运行版本：`{}` @ `{}`（工作树 {}）".format(
			_s(versions.get("commit")), _s(versions.get("branch")), _s(versions.get("worktree_state"))
		)
	)
	att = doc.get("attribution") or {}
	lines += ["", "## 归因", "", att.get("statement") or "—"]
	if att.get("first_anomaly_boundary"):
		lines.append(f"- 首个已确认异常边界：{_s(att.get('first_anomaly_label'))}")
		lines.append(
			"- 它之前最近一个有记录的边界：{}（有记录不等于已确认正常）".format(
				_s(att.get("last_evidenced_label")) or "无"
			)
		)
	lines.append(
		"- 计数：已确认 {} / 疑似 {} / 未定 {}".format(
			att.get("confirmed_count", 0), att.get("suspected_count", 0), att.get("unknown_count", 0)
		)
	)
	lines += ["", "## 责任划分", ""]
	fault = doc.get("fault") or {}
	lines.append(f"- 归属：{fault.get('responsibility_label') or PARTY_LABEL.get('undetermined')}")
	lines.append(f"- 任务结局：{fault.get('task_outcome_label') or OUTCOME_LABEL.get('not_accepted')}")
	lines.append(
		f"- 约束是否进入模型实际收到的内容：{shown_to_model_label(fault.get('shown_to_model'))}"
		f"（{fault.get('shown_to_model_note')}）"
	)
	lines.append(f"- 主原因：{fault.get('primary_cause_label') or '未定'}（`{fault.get('primary_cause')}`）")
	lines.append(f"- 为什么：{fault.get('why')}")
	for cause in fault.get("causes") or []:
		lines.append(
			"  - [{}] {} —— 能证明：{}；不能证明：{}".format(
				cause.get("party"), cause.get("label"), cause.get("proves"), cause.get("does_not_prove")
			)
		)
		# 定责的那条要能回到原始记录：结论明细那行自己写着「无原始证据（因此不下定责结论）」，
		# 原因栏以前只印句子、把后端一起送来的指针丢掉了。
		cause_evidence = cause_evidence_text(cause)
		if cause_evidence:
			lines.append(f"    证据：{cause_evidence}")
	for step in fault.get("chain") or []:
		lines.append(f"  {step.get('order')}. [{step.get('party_label')}] {step.get('fact')}")
	for item in fault.get("missing_evidence") or []:
		lines.append(f"- 改判还缺：{item}")
	for item in fault.get("not_claimed") or []:
		lines.append(f"- 本报告不宣称：{item}")
	lines += ["", "## 结论明细", ""]
	findings = doc.get("findings") or []
	if not findings:
		lines.append("规则集未产生结论（不代表没有异常，只代表这些规则没看到）。")
	for item in findings:
		status = _STATUS_LABEL.get(_s(item.get("status")), "未定")
		lines.append(f"### [{status}] {item.get('phenomenon')}")
		lines.append("")
		lines.append(f"- 边界：{_s(item.get('boundary'))}　功能归属：{_s(item.get('component'))}")
		lines.append(f"- 规则：`{_s(item.get('rule_id'))}` v{item.get('rule_version')}")
		lines.append(f"- 证据：{_short(item.get('evidence') or []) or '无原始证据（因此不下定责结论）'}")
		if item.get("impact"):
			lines.append(f"- 影响：{_s(item.get('impact'))}")
		lines.append(f"- 允许结论：{_s(item.get('allowed_conclusion'))}")
		lines.append(f"- 覆盖缺口：{_s(item.get('coverage_gap'))}")
		lines.append("")
	lines += ["## 边界覆盖", "", "| 边界 | 有记录 | 证据条数 | 说明 |", "| --- | --- | --- | --- |"]
	for boundary in doc.get("boundaries") or []:
		lines.append(
			"| {} | {} | {} | {} |".format(
				_s(boundary.get("label")),
				"是" if boundary.get("present") else "否",
				boundary.get("evidence_count", 0),
				"；".join(boundary.get("notes") or []),
			)
		)
	lines += ["", "## 采集完整性", "", "| 来源 | 状态 | 条数 | 定位 | 说明 |", "| --- | --- | --- | --- | --- |"]
	for window in doc.get("windows") or []:
		lines.append(
			"| {} | {} | {} | `{}` | {} |".format(
				_s(window.get("source")),
				_window_status(window),
				window.get("rows_matched", 0),
				_s(window.get("locator")),
				_s(window.get("note")),
			)
		)
	lines += ["", "## 缺项", ""]
	gaps = doc.get("gaps") or []
	if not gaps:
		lines.append("无记录到的缺项。")
	for gap in gaps:
		lines.append(
			f"- {_s(gap.get('boundary'))}：{gap_reason_text(gap.get('reason'))} — {_s(gap.get('detail'))}"
		)
	usage = doc.get("usage_summary") or {}
	lines += ["", "## 用量", ""]
	lines.append(
		f"- 已结束尝试：{usage.get('finished_attempts', 0)}"
		f"（有价 {usage.get('priced_attempts', 0)}"
		f" · 无账 {usage.get('unknown_cost_attempts', 0)}"
		f" · 有账无价 {usage.get('unpriced_attempts', 0)}）"
	)
	priced = int(usage.get("priced_attempts", 0) or 0)
	if priced:
		partial = "，不含费用未知的尝试" if usage.get("total_is_partial") else ""
		lines.append(
			f"- 估算合计：{usage.get('estimated_total_cny', 0)}（已依据 {priced} 次尝试{partial}）"
		)
	else:
		lines.append(
			f"- 估算合计：费用未知（{usage.get('finished_attempts', 0)} 次尝试无一可依据，"
			"未按 0 计入）"
		)
	lines.append(f"- 计价口径：{_s(usage.get('cost_basis'))}，非账单实付")
	lines.append(f"- 说明：{_s(usage.get('statement'))}")
	return "\n".join(lines) + "\n"


__all__ = [
	"attribution",
	"build_report",
	"load_report",
	"report_id",
	"save_report",
	"to_json",
	"to_markdown",
	"usage_summary",
]
