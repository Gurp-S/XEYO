"""失败原因的机器可读分类：只从已核实的事实生成，每条都自带"能证明什么/不能证明什么"。

归属回答"谁的错"，本模块回答"发生了什么类型的失败"。两者分开是因为一个失败原因
可以不属于任何一方（例如"没有验收记录"），而一个归属可以由多个原因共同造成。

顺序即上游优先：越靠前的原因越能解释后面的现象，展示时不做合并、不打分。
"""

from __future__ import annotations

from typing import Any

from diagnostics.collect import RunEvidence
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, UNKNOWN, Finding, _s

# 原因码：稳定主键，标签只是展示。
CONTEXT_DROPPED = "context_dropped_constraint"
PROJECTION_BROKEN = "projection_structure_broken"
OUTPUT_DROPPED = "output_dropped_before_send"
PREFIX_CHANGED = "frozen_prefix_changed"
COLD_REF_UNREADABLE = "cold_reference_unreadable"
PERMISSION_BLOCKED = "permission_blocked_action"
TOOL_ERROR = "tool_execution_error"
PROVIDER_FAILURE = "provider_or_transport_failure"
REPEATED_ERROR = "repeated_tool_error"
ACTION_SKIPPED = "required_action_skipped"
SELF_REPORT_MISMATCH = "self_report_vs_verifier"
ACCEPT_FAILED = "acceptance_failed"
ACCEPT_ERROR = "acceptance_error"
ACCEPT_MISSING = "acceptance_missing"
DISPLAY_GAP = "display_transport_gap"
USAGE_UNACCOUNTED = "usage_unaccounted"
RUN_INCOMPLETE = "run_incomplete"
TOOL_ROUTED = "tool_action_rerouted"
CONTEXT_CHANGED_MIDTURN = "instruction_context_changed_midturn"
NOT_DETERMINED = "not_determined"
CONSTRAINT_FOLDED = "constraint_folded_out_of_projection"

CAUSE_LABEL: dict[str, str] = {
	CONTEXT_DROPPED: "该在场的约束没进最后发射的内容",
	PROJECTION_BROKEN: "投影结构不变量被破坏（tool call/result 不成对）",
	OUTPUT_DROPPED: "工具结果在发送前被护栏丢弃",
	PREFIX_CHANGED: "冻结前缀在折叠区间内变化",
	COLD_REF_UNREADABLE: "进冷层的内容回读不到",
	PERMISSION_BLOCKED: "被要求的动作由权限执行层挡下",
	TOOL_ERROR: "工具执行返回错误",
	PROVIDER_FAILURE: "模型请求在厂商/传输/解析边界失败",
	REPEATED_ERROR: "同一签名的错误重复出现",
	ACTION_SKIPPED: "被要求的动作没做，却自述完成",
	SELF_REPORT_MISMATCH: "自述与验收记录不符",
	ACCEPT_FAILED: "验收执行了且失败",
	ACCEPT_ERROR: "验收自身执行报错",
	ACCEPT_MISSING: "没跑验收，任务是否完成未知",
	DISPLAY_GAP: "引擎已完成而界面/事件流缺尾",
	USAGE_UNACCOUNTED: "部分请求没有用量账，费用未知",
	RUN_INCOMPLETE: "运行有开始记录无结束记录",
	TOOL_ROUTED: "工具调用在执行层换了另一个工具",
	CONTEXT_CHANGED_MIDTURN: "同一轮内送出的指令上下文标识变过",
	CONSTRAINT_FOLDED: "在场的约束被折叠移出投影",
	NOT_DETERMINED: "没有可核对的失败原因",
}

# 每条原因的"能证明 / 不能证明"，防止把相关性写成根因。
_PROVES: dict[str, tuple[str, str]] = {
	CONTEXT_DROPPED: (
		"当场在场的约束在源历史里查得到、在发射内容里查不到",
		"不能证明模型因此失败，也不能定位到候选/选择哪一级",
	),
	CONSTRAINT_FOLDED: (
		"该约束所在消息落在 compact_cursor 之前的折叠区间内",
		"不能证明折叠是错的——只能说明是折叠把它移出了投影，是否该保留需人工复核",
	),
	PROJECTION_BROKEN: ("发出的投影形状违反厂商约束", "不能解释与形状无关的那部分失败"),
	OUTPUT_DROPPED: ("这些 tool result 没有进入最终请求体", "不能证明模型本来会用它们做什么"),
	PREFIX_CHANGED: ("缓存前缀稳定性不变量被破坏", "不能证明它改变了任务结果"),
	COLD_REF_UNREADABLE: ("句柄声称可回读但实际读不到", "不能证明模型发起过取回"),
	PERMISSION_BLOCKED: ("动作是被执行层挡下的", "不能把「没做」记到模型头上"),
	TOOL_ERROR: (
		"失败发生在具体某个工具调用上",
		"不能区分工具自身的错与外部世界的错：error_kind 只有非默认值（既不是空也不是 "
		"INTERNAL）才带得出这个区分",
	),
	PROVIDER_FAILURE: ("这一枪没拿到正常响应", "不能据此评价提示词好坏（429 尤其）"),
	REPEATED_ERROR: ("同一错误签名反复出现", "不能断言死循环，也不能断言参数完全相同"),
	ACTION_SKIPPED: ("要求已送达、没被执行、没被挡，还自述完成", "不能证明模型「理解」了要求，只比对了字面"),
	SELF_REPORT_MISMATCH: ("模型说的话与验收记录不一致", "不能证明回答里其他陈述为假"),
	ACCEPT_FAILED: ("被指定的 verifier 退出码非 0", "不能证明任务整体未完成，也不能证明没有越界修改"),
	ACCEPT_ERROR: ("verifier 自身异常退出", "不能证明被验收的代码有错"),
	ACCEPT_MISSING: ("没有任何验收记录", "既不能判完成也不能判失败"),
	DISPLAY_GAP: ("服务端与界面之间存在缺口", "不能证明引擎未完成"),
	USAGE_UNACCOUNTED: ("这些请求的费用未知", "不能把它们按 0 计入合计"),
	RUN_INCOMPLETE: ("结束记录缺失", "不能证明进程已死"),
	TOOL_ROUTED: (
		"这些调用请求的是左边的工具、实际执行的是右边的（审计 tool.routed 行）",
		"不能把改道判成分发故障：它是执行层策略；也不能说这一枪每次都改道",
	),
	CONTEXT_CHANGED_MIDTURN: (
		"同一轮内的模型/工具行带着不止一个该标识",
		"不能证明变化发生在两次尝试之间，也不能判定哪一版才是预期的",
	),
	NOT_DETERMINED: ("本次记录不足以给出原因", "不等于没有失败，也不等于成功"),
}

_CAUSE_PARTY: dict[str, str] = {
	CONTEXT_DROPPED: "engine",
	CONSTRAINT_FOLDED: "engine",
	PROJECTION_BROKEN: "engine",
	OUTPUT_DROPPED: "engine",
	PREFIX_CHANGED: "engine",
	COLD_REF_UNREADABLE: "engine",
	PERMISSION_BLOCKED: "engine",
	# 工具失败先记"未定"：归属要靠 error_kind（fault_split 的 tool_parties 通路），
	# 这一栏以前根本不在表里，是 _entry 的 .get 默认值把它兜成 undetermined 的。
	TOOL_ERROR: "undetermined",
	PROVIDER_FAILURE: "environment",
	REPEATED_ERROR: "undetermined",
	ACTION_SKIPPED: "model",
	SELF_REPORT_MISMATCH: "model",
	ACCEPT_FAILED: "undetermined",
	ACCEPT_ERROR: "environment",
	ACCEPT_MISSING: "undetermined",
	DISPLAY_GAP: "engine",
	USAGE_UNACCOUNTED: "undetermined",
	RUN_INCOMPLETE: "undetermined",
	TOOL_ROUTED: "undetermined",
	CONTEXT_CHANGED_MIDTURN: "undetermined",
	NOT_DETERMINED: "undetermined",
}

# (原因码, 触发它的规则 id, 需要的状态)
_RULE_CAUSES: tuple[tuple[str, str, str], ...] = (
	(CONTEXT_CHANGED_MIDTURN, "instruction_drift", SUSPECTED_CAUSE),
	(PROJECTION_BROKEN, "tool_pair_integrity", CONFIRMED_FAULT),
	(OUTPUT_DROPPED, "wire_gap", CONFIRMED_FAULT),
	(PREFIX_CHANGED, "frozen_head", CONFIRMED_FAULT),
	(COLD_REF_UNREADABLE, "cold_reference", CONFIRMED_FAULT),
	(PERMISSION_BLOCKED, "permission_block", CONFIRMED_FAULT),
	(TOOL_ROUTED, "tool_routing", UNKNOWN),
	(PROVIDER_FAILURE, "provider_stream_failure", CONFIRMED_FAULT),
	(REPEATED_ERROR, "repeated_failure", SUSPECTED_CAUSE),
	(USAGE_UNACCOUNTED, "usage_accounting", CONFIRMED_FAULT),
	(RUN_INCOMPLETE, "incomplete_run", CONFIRMED_FAULT),
)


def _entry(code: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
	proves, not_proves = _PROVES.get(code, ("", ""))
	return {
		"code": code,
		"label": CAUSE_LABEL.get(code, code),
		"party": _CAUSE_PARTY.get(code, "undetermined"),
		"proves": proves,
		"does_not_prove": not_proves,
		"evidence": evidence[:6],
	}


def derive(
	*,
	findings: list[Finding],
	constraint_lost: bool,
	constraint_mode: str = "",
	permission_blocked: bool,
	action_skipped: bool,
	self_report: Finding | None,
	outcome: str,
	tool_error_kinds: dict[str, list[dict[str, Any]]],
	display_gap: bool = False,
) -> list[dict[str, Any]]:
	"""按上游优先顺序产出原因列表。一个失败可以同时挂多条原因，不做合并。"""
	by_rule: dict[str, list[Finding]] = {}
	for f in findings:
		by_rule.setdefault(f.rule_id, []).append(f)
	out: list[dict[str, Any]] = []
	if constraint_lost:
		entry = _entry(CONTEXT_DROPPED, [])
		if constraint_mode == "folded_out":
			entry["code"] = CONSTRAINT_FOLDED
			entry["label"] = CAUSE_LABEL[CONSTRAINT_FOLDED]
			entry["proves"], entry["does_not_prove"] = _PROVES[CONSTRAINT_FOLDED]
		out.append(entry)
	for code, rule_id, want_status in _RULE_CAUSES:
		# 同一条规则可以一边产出"已确认"一边产出"未定"（例：投影结构坏了 + 工作记忆里
		# 存着不成对的 tool_use）。过去这里只记每条规则的**最后**一个状态，而规则集把
		# 已确认排在前面 ⇒ 邻居那条未定会把已确认的原因顶掉，原因列表里就此看不见它；
		# 证据又是按规则合并的，未定那半的证据还会挂到已确认的原因上。按状态各取各的。
		matched = [
			f
			for f in by_rule.get(rule_id) or []
			if f.status == want_status or code == REPEATED_ERROR
		]
		if not matched:
			continue
		out.append(_entry(code, [e.to_dict() for f in matched for e in f.evidence]))
	for kind, refs in sorted(tool_error_kinds.items()):
		entry = _entry(TOOL_ERROR, refs)
		entry["detail_kind"] = kind
		out.append(entry)
	if permission_blocked and not any(x["code"] == PERMISSION_BLOCKED for x in out):
		out.append(_entry(PERMISSION_BLOCKED, []))
	if display_gap:
		out.append(_entry(DISPLAY_GAP, []))
	if action_skipped:
		out.append(_entry(ACTION_SKIPPED, []))
	if self_report is not None:
		out.append(_entry(SELF_REPORT_MISMATCH, [e.to_dict() for e in self_report.evidence]))
	if outcome == "accepted_fail":
		out.append(_entry(ACCEPT_FAILED, []))
	elif outcome == "verifier_error":
		out.append(_entry(ACCEPT_ERROR, []))
	elif outcome == "not_accepted":
		out.append(_entry(ACCEPT_MISSING, []))
	if not out:
		out.append(_entry(NOT_DETERMINED, []))
	return out


def primary(causes: list[dict[str, Any]]) -> dict[str, Any]:
	"""主原因＝最上游那条；并列时保留全部，不合成一条"综合结论"。"""
	for item in causes:
		if item["code"] != USAGE_UNACCOUNTED:
			return item
	return causes[0] if causes else _entry(NOT_DETERMINED, [])


def statement(causes: list[dict[str, Any]], run: RunEvidence) -> str:
	head = primary(causes)
	if head["code"] == NOT_DETERMINED:
		return "没有可核对的失败原因记录：本次只能报边界缺项，不能报原因。"
	others = len(causes) - 1
	return "主原因：{}。{}".format(
		head["label"],
		f"另有 {others} 条同时可见的原因，逐条列出、不合并成一条综合结论。" if others else "",
	)


__all__ = [
	"ACCEPT_ERROR",
	"ACCEPT_FAILED",
	"ACCEPT_MISSING",
	"ACTION_SKIPPED",
	"CAUSE_LABEL",
	"CONTEXT_DROPPED",
	"NOT_DETERMINED",
	"PERMISSION_BLOCKED",
	"PROVIDER_FAILURE",
	"SELF_REPORT_MISMATCH",
	"TOOL_ERROR",
	"derive",
	"primary",
	"statement",
]
