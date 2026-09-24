"""责任划分：引擎的错 / 模型的错 / 外部环境的错 / 判不了，以及「为什么」。

判据是**不对称**的，这是本模块唯一的硬核：

* 引擎侧的错可以由确定性不变量被破坏直接证明（配对损坏、护栏丢行、冻结头变化、
  权限把调用挡掉、执行层报错、服务端已完成而界面没收到）。
* 判「模型的错」必须同时成立三件事：约束**确实进入了模型实际收到的内容**、
  该步之前与之内**没有**引擎侧已确认异常、结果与约束**可机器判定地**矛盾。
  少任何一件 ⇒ ``undetermined``，并写明缺哪条记录。

因此"没有发现引擎异常"永远不等于"是模型的错"；约束没被送到（或无法证明被送到）
时，责任只能悬空。所有措辞是事实型，不出现概率、不出现加权总分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from diagnostics.collect import RunEvidence
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, EvidenceRef, Finding, _s

# 责任方
ENGINE = "engine"
MODEL = "model"
ENVIRONMENT = "environment"
MIXED = "mixed"
UNDETERMINED = "undetermined"

PARTY_LABEL = {
	ENGINE: "引擎侧",
	MODEL: "模型侧",
	ENVIRONMENT: "外部环境",
	MIXED: "混合（引擎与模型都脱不了）",
	UNDETERMINED: "无法归因",
}

# 任务结局：只由验收证据决定，模型自述不算验收。
OUTCOME_PASS = "accepted_pass"
OUTCOME_FAIL = "accepted_fail"
OUTCOME_VERIFIER_ERROR = "verifier_error"
OUTCOME_NOT_ACCEPTED = "not_accepted"
OUTCOME_SELF_REPORTED = "self_reported_unverified"

OUTCOME_LABEL = {
	OUTCOME_PASS: "验收通过",
	OUTCOME_FAIL: "验收失败",
	OUTCOME_VERIFIER_ERROR: "验收本身执行错误",
	OUTCOME_NOT_ACCEPTED: "未执行验收：无法判定任务是否完成",
	OUTCOME_SELF_REPORTED: "模型自述完成，但无验收证据",
}

# 执行层错误分类（tools/error_taxonomy.py）按归属切分。
_ENGINE_KINDS = {
	"PERMISSION_DENIED",
	"USER_INPUT_REQUIRED",
	"FINALIZATION_RESTRICTED",
	"ACTION_OUTCOME_UNKNOWN",
	"INTERNAL",
	"UNKNOWN_TOOL",
	"RESERVED_CHANNEL",
}
_ENVIRONMENT_KINDS = {
	"COMMAND_NOT_FOUND",
	"TRANSIENT_INFRA",
	"TIMEOUT",
	"NOT_FOUND",
}
_MODEL_KINDS = {"INVALID_ARGUMENT", "ABORTED"}

_ERROR_KIND_RX = re.compile(r"error_kind=([A-Z_]+)")

# 规则 → 归属（引擎侧的确定性缺陷）
_ENGINE_RULES = {
	"tool_pair_integrity",
	"wire_gap",
	"frozen_head",
	"cold_reference",
	"incomplete_run",
	"permission_block",
}
_ENVIRONMENT_RULES = {"provider_stream_failure"}


@dataclass
class Step:
	"""因果链上的一步：一个边界上的事实 + 它的原始证据。"""

	order: int
	boundary: str
	fact: str
	party: str
	evidence: list[EvidenceRef] = field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		return {
			"order": self.order,
			"boundary": self.boundary,
			"fact": self.fact,
			"party": self.party,
			"party_label": PARTY_LABEL.get(self.party, self.party),
			"evidence": [e.to_dict() for e in self.evidence],
		}


def _tool_error_party(detail_text: str) -> str:
	"""从证据 detail 里取 error_kind 再定归属。

	审计的 detail 形如 ``tool.finished is_error=true error_kind=TIMEOUT``，
	拿整串去比对分类表会永远落空。
	"""
	match = _ERROR_KIND_RX.search(_s(detail_text))
	kind = _s(match.group(1)) if match else ""
	if kind in _ENGINE_KINDS:
		return ENGINE
	if kind in _ENVIRONMENT_KINDS:
		return ENVIRONMENT
	if kind in _MODEL_KINDS:
		return MODEL
	return UNDETERMINED


def _transport_findings(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
	"""「引擎已完成但界面没收到」：只把已确认级用于定责，疑似级仍进因果链。"""
	confirmed: list[Finding] = []
	suspected: list[Finding] = []
	for f in findings:
		if f.boundary != "sse_gui":
			continue
		if f.status == CONFIRMED_FAULT:
			confirmed.append(f)
		elif f.status == SUSPECTED_CAUSE:
			suspected.append(f)
	return confirmed, suspected


def _engine_findings(findings: list[Finding]) -> list[Finding]:
	out: list[Finding] = []
	for f in findings:
		if f.status != CONFIRMED_FAULT:
			continue
		if f.rule_id in _ENGINE_RULES:
			out.append(f)
		elif f.rule_id == "tool_failure" and any(
			_tool_error_party(e.detail) == ENGINE for e in f.evidence
		):
			out.append(f)
	return out


def _environment_findings(findings: list[Finding]) -> list[Finding]:
	out: list[Finding] = []
	for f in findings:
		if f.status != CONFIRMED_FAULT:
			continue
		if f.rule_id == "provider_stream_failure":
			out.append(f)
		elif f.rule_id == "tool_failure" and any(
			_tool_error_party(e.detail) == ENVIRONMENT for e in f.evidence
		):
			out.append(f)
	return out


def _task_outcome(run: RunEvidence) -> tuple[str, list[EvidenceRef], str]:
	"""任务结局只看验收记录；没有验收就报"无法判定"。"""
	verifiers = [p for p in run.pins if _s(p.get("kind")) == "verifier"]
	if not verifiers:
		return OUTCOME_NOT_ACCEPTED, [], "本运行没有验收记录：既不能说通过，也不能说失败。"
	ref = [
		EvidenceRef(
			source="pin",
			locator=_s(p.get("locator")),
			ref_id=_s(p.get("pin_id")),
			detail=f"verifier {_s(p.get('name'))} exit={p.get('exit_code')}",
		)
		for p in verifiers
	]
	codes = [p.get("exit_code") for p in verifiers]
	if any(c is None for c in codes):
		return OUTCOME_NOT_ACCEPTED, ref, "有验收记录但退出码未记录：不能当作已验收。"
	if any(int(c) > 128 for c in codes if c is not None):
		return OUTCOME_VERIFIER_ERROR, ref, "验收命令自身异常退出（信号致死或超出上限）。"
	failed = [int(c) for c in codes if c is not None and int(c) != 0]
	if failed:
		return OUTCOME_FAIL, ref, f"{len(failed)} 个 verifier 退出码非 0。"
	return OUTCOME_PASS, ref, "全部 verifier 退出码 0（只证明这些检查通过）。"


def _obligation(run: RunEvidence) -> dict[str, Any]:
	"""被判"模型的错"所依据的约束：优先用户固定下来的预期，其次最后一条用户消息。"""
	for pin in run.pins:
		if _s(pin.get("kind")) != "run_mark":
			continue
		text = _s(pin.get("expected")) or _s(pin.get("note"))
		if text:
			return {
				"text": text,
				"source": "pin",
				"locator": _s(pin.get("locator")),
				"ref_id": _s(pin.get("pin_id")),
			}
	try:
		from diagnostics.loss_chain import _iter_transcript, _resolve_body

		for row in reversed(list(_iter_transcript(run.session_id, 60))):
			if _s(row.get("role")) != "user":
				continue
			body = _resolve_body(row)
			if body.strip():
				return {
					"text": body.strip()[:500],
					"source": "last_user_message",
					"locator": _s(row.get("_path")),
					"ref_id": _s(row.get("id")),
				}
	except Exception:  # noqa: BLE001 — 取不到约束就悬空，不猜
		pass
	return {"text": "", "source": "", "locator": "", "ref_id": ""}


def _shown_to_model(run: RunEvidence, needle: str) -> dict[str, Any]:
	"""约束是否确实进了模型实际收到的内容。捕获正文优先，其次上一枪实际发送的投影。"""
	if not needle:
		return {"state": "no_obligation", "evidence": [], "note": "没有可比对的约束文本"}
	try:
		from diagnostics.loss_chain import _stage_emitted, _stage_provider_body

		body_stage = _stage_provider_body(run, needle)
		if body_stage["state"] == "found":
			return {"state": "shown", "evidence": body_stage["evidence"], "note": "在适配器最终请求体里命中"}
		proj_stage = _stage_emitted(run, needle)
		if proj_stage["state"] == "found":
			return {"state": "shown", "evidence": proj_stage["evidence"], "note": "在上一枪实际发送的投影里命中"}
		if proj_stage["state"] == "absent":
			return {"state": "not_shown", "evidence": proj_stage["evidence"], "note": "发送投影里没有这段约束"}
		return {"state": "unprovable", "evidence": [], "note": proj_stage["note"]}
	except Exception as exc:  # noqa: BLE001
		return {"state": "unprovable", "evidence": [], "note": f"定位链不可用：{type(exc).__name__}"}


def _self_report_contradiction(run: RunEvidence, outcome: str) -> Finding | None:
	"""模型自述与验收不符：措辞按事实比对，不评价。"""
	if outcome not in {OUTCOME_FAIL, OUTCOME_VERIFIER_ERROR, OUTCOME_NOT_ACCEPTED}:
		return None
	texts: list[str] = []
	for row in run.transcript_rows:
		if _s(row.get("role")) != "assistant":
			continue
		content = _s(row.get("content"))
		if content:
			texts.append(content)
	joined = " ".join(texts)
	if not joined:
		return None
	hits = [w for w in ("测试通过", "已通过", "已完成", "全部通过", "验收通过") if w in joined]
	if not hits:
		return None
	return Finding(
		rule_id="self_report_vs_verifier",
		rule_version=1,
		phenomenon=f"模型自述里出现「{'、'.join(hits)}」，但验收记录显示 {OUTCOME_LABEL.get(outcome, outcome)}",
		boundary="file_verifier",
		component="结果验收 vs 回答文本",
		status=CONFIRMED_FAULT,
		evidence=[
			EvidenceRef(
				source="transcript",
				locator=_s(row.get("locator")),
				ref_id=_s(row.get("id")),
				detail=f"自述含「{hits[0]}」",
			)
			for row in run.transcript_rows[:1]
		],
		impact="自述与验收不符：以验收记录为准。",
		coverage_gap="按关键词比对回答文本，措辞变化会漏判；不评判语义等价性。",
		allowed_conclusion="可确认「说的」与「验收到的」不一致。",
	)


def _as_ref(item: Any) -> EvidenceRef | None:
	"""定位链返回的是 dict；转回 EvidenceRef，坏条目丢弃而不是编造。"""
	if isinstance(item, EvidenceRef):
		return item
	if not isinstance(item, dict):
		return None
	return EvidenceRef(
		source=_s(item.get("source")),
		locator=_s(item.get("locator")),
		ref_id=_s(item.get("ref_id")),
		detail=_s(item.get("detail")),
	)


def _obligation_step_evidence(obligation: dict[str, Any], shown: dict[str, Any]) -> list[EvidenceRef]:
	refs: list[EvidenceRef] = [
		EvidenceRef(
			source="pin" if obligation.get("source") == "pin" else "transcript",
			locator=_s(obligation.get("locator")),
			ref_id=_s(obligation.get("ref_id")),
			detail="声明的约束",
		)
	]
	for item in (shown.get("evidence") or [])[:3]:
		ref = _as_ref(item)
		if ref is not None:
			refs.append(ref)
	return refs


def attribute_fault(run: RunEvidence, findings: list[Finding]) -> dict[str, Any]:
	"""给出责任方、任务结局、因果链，以及"要改判还缺哪条记录"。"""
	engine = _engine_findings(findings)
	environment = _environment_findings(findings)
	transport, transport_suspect = _transport_findings(findings)
	outcome, outcome_refs, outcome_note = _task_outcome(run)

	tool_parties: dict[str, list[Finding]] = {}
	for f in findings:
		if f.rule_id != "tool_failure" or f.status != CONFIRMED_FAULT:
			continue
		for ev in f.evidence:
			tool_parties.setdefault(_tool_error_party(ev.detail), []).append(f)

	obligation = _obligation(run)
	shown = _shown_to_model(run, _s(obligation.get("text"))[:120])
	self_report = _self_report_contradiction(run, outcome)

	steps: list[Step] = []
	order = 0

	def _step(boundary: str, fact: str, party: str, refs: list[EvidenceRef]) -> None:
		nonlocal order
		order += 1
		steps.append(Step(order=order, boundary=boundary, fact=fact, party=party, evidence=refs))

	for f in engine:
		_step(f.boundary, f.phenomenon, ENGINE, f.evidence)
	for f in environment:
		_step(f.boundary, f.phenomenon, ENVIRONMENT, f.evidence)
	for kind, items in sorted(tool_parties.items()):
		for f in items[:1]:
			_step(f.boundary, f.phenomenon, kind if kind != UNDETERMINED else UNDETERMINED, f.evidence)
	for f in transport:
		_step("sse_gui", f.phenomenon, ENGINE, f.evidence)
	for f in transport_suspect:
		_step("sse_gui", f.phenomenon, UNDETERMINED, f.evidence)
	if self_report is not None:
		_step(self_report.boundary, self_report.phenomenon, MODEL, self_report.evidence)
	if obligation.get("text"):
		_step(
			"instruction_context",
			"约束来源={}（{}）；是否进入模型实际收到的内容={}".format(
				_s(obligation.get("source")), _s(obligation.get("ref_id"))[:16], shown["state"]
			),
			MODEL if shown["state"] == "shown" else UNDETERMINED,
			_obligation_step_evidence(obligation, shown),
		)
	constraint_lost = shown["state"] == "not_shown"
	if constraint_lost:
		_step(
			"wsc_fold",
			"用户声明的约束在源历史里存在，但不在最后发射的投影里",
			ENGINE,
			[
				EvidenceRef(
					source="working",
					locator=_s(obligation.get("locator")),
					ref_id="last_x_sent",
					detail="发射投影未命中该约束",
				)
			],
		)
	if outcome_refs:
		_step("file_verifier", outcome_note, MODEL if outcome == OUTCOME_FAIL else UNDETERMINED, outcome_refs)

	# --- 归属判定 ---
	engine_bound = bool(engine or transport or constraint_lost or ENGINE in tool_parties)
	environment_bound = bool(environment or ENVIRONMENT in tool_parties)
	model_provable = shown["state"] == "shown" and (
		self_report is not None or outcome == OUTCOME_FAIL
	)

	if model_provable and engine_bound:
		party = MIXED
		why = (
			"约束确实送到了模型、结果又与验收矛盾（模型侧成立），"
			"但同一条链上还有引擎侧已确认异常，模型不能因此被排除：两方都有份。"
		)
	elif model_provable:
		party = MODEL
		why = "约束在模型实际收到的内容里命中，且该步之前与之内没有引擎侧已确认异常；结果与验收矛盾。"
	elif engine_bound:
		party = ENGINE
		why = "引擎侧不变量被破坏或执行层把动作挡住，模型的输入已不是任务本来的输入。"
	elif environment_bound:
		party = ENVIRONMENT
		why = "失败发生在外部世界：厂商返回错误/限流、命令不存在、超时；引擎与模型都未被证明有错。"
	elif outcome == OUTCOME_PASS:
		party = UNDETERMINED
		why = "验收通过且没有已确认异常；这不构成" + PARTY_LABEL[MODEL] + "判定，也不构成任务正确判定。"
	else:
		party = UNDETERMINED
		why = "没有任何一级记录能证明约束送到了模型，或矛盾不可机器判定。"

	missing: list[str] = []
	if shown["state"] == "no_obligation":
		missing.append("没有声明的预期：用「标记这轮结果不对」写下预期结果，才能判模型侧")
	if shown["state"] == "unprovable":
		missing.append("未开启可复现记录且无上一枪投影：开 capture 后重跑才能得到最终请求体正文")
	if shown["state"] == "not_shown":
		missing.append("约束未进入发送内容：这是引擎侧丢失，需定位到具体边界")
	if outcome == OUTCOME_NOT_ACCEPTED:
		missing.append("没有 verifier 记录：任务是否完成无法判定")
	if not run.captures:
		missing.append("缺适配器最终请求体：投影之后的变换不可见")

	verdict: dict[str, Any] = {
		"responsibility": party,
		"responsibility_label": PARTY_LABEL[party],
		"why": why,
		"task_outcome": outcome,
		"task_outcome_label": OUTCOME_LABEL.get(outcome, outcome),
		"obligation": {k: v for k, v in obligation.items() if k != "text"} | {"excerpt": _s(obligation.get("text"))[:160]},
		"shown_to_model": shown["state"],
		"shown_to_model_note": shown["note"],
		"engine_confirmed": len(engine),
		"environment_confirmed": len(environment),
		"transport_gap": bool(transport),
		"chain": [s.to_dict() for s in steps],
		"missing_evidence": missing,
		"not_claimed": [
			"不宣称这是任务失败的全部原因",
			"不把「没发现引擎异常」当成模型有错",
			"不给概率或加权总分",
		],
	}
	if self_report is not None:
		verdict["self_report"] = self_report.to_dict()
	return verdict


__all__ = [
	"ENGINE",
	"ENVIRONMENT",
	"MIXED",
	"MODEL",
	"OUTCOME_LABEL",
	"PARTY_LABEL",
	"Step",
	"UNDETERMINED",
	"attribute_fault",
]
