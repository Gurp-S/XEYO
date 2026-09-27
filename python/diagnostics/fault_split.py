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

from diagnostics import causes as _causes
from diagnostics.collect import RunEvidence
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, EvidenceRef, Finding, _f, _s
from diagnostics.rules import (
	no_turn_records,
	permission_blocked,
	permission_outcome,
	permission_outcome_unrecorded,
	row_belongs_to_run,
	scope_word,
	source_locator,
	turn_scoped,
	_turn_projection_ids,
)
from msgtypes.notice_markers import (
	is_notice_message,
	is_synthetic_user_text,
	matches_notice_text,
	resume_user_cue,
)
# 归属判据住在 loss_chain：事实定位链（``trace_fact``）与责任划分必须用同一份，
# 两处各写一遍就是下一次"一边改了另一边没改"的入口。
from diagnostics.loss_chain import (
	_OBLIGATION_TOLERANCE_SEC,
	_emitted_projection_in_turn,
	_turn_last_ts,
)

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
	OUTCOME_NOT_ACCEPTED: "无验收记录：无法判定任务是否完成",
	OUTCOME_SELF_REPORTED: "模型自述完成，但无验收证据",
}

# 执行层错误分类（tools/error_taxonomy.py）按归属切分。
#
# INTERNAL 故意不在这里：它是 tools/base_tool.py 给"只回了 is_error + 文本"的错误
# 统一填的默认值，也是 classify_exception 什么都没匹配上时的兜底 ⇒ 它说的是"没分类"，
# 不是"引擎内部出错"。真实数据尾窗 12 000 行里非空的 error_kind 只有 INTERNAL（129 条），
# 把它算成我方引擎就等于把全部工具失败判给自己。
_ENGINE_KINDS = {
	"PERMISSION_DENIED",
	"USER_INPUT_REQUIRED",
	"FINALIZATION_RESTRICTED",
	"ACTION_OUTCOME_UNKNOWN",
	"UNKNOWN_TOOL",
	"RESERVED_CHANNEL",
}
_ENVIRONMENT_KINDS = {
	"COMMAND_NOT_FOUND",
	"TRANSIENT_INFRA",
	"TIMEOUT",
	"NOT_FOUND",
}
# ABORTED 不在这里：它由 tool_registry 的插件钩子 should_abort、或引擎"用户停止"分支写下
# （见 rules 校准注 7：Aborted 来自用户停止），两条成因都不是模型侧。没有独立的 user party，
# 又存在 engine(钩子)/非定(用户停) 两种来源，落到 UNDETERMINED 比硬判给模型诚实 ——
# 这与当初把 INTERNAL 从 _ENGINE_KINDS 摘掉同理：不把一件不是某方造成的事算到某方头上。
_MODEL_KINDS = {"INVALID_ARGUMENT"}

_ERROR_KIND_RX = re.compile(r"error_kind=([A-Z_]+)")

# 人读正文只用中文；机器枚举留在结构化字段里。把 unprovable / turn_user_message
# 这类内部状态名写进结论正文，界面就会原样投给用户，读者也无法把正文和字段对上。
_SHOWN_TEXT = {
	"shown": "已进入模型实际收到的内容",
	# 判据只是"留存的那一份发射投影里没有"：更早几枪的投影根本没落盘，说"从未进入"超出了
	# 可比范围（会话级尤其如此——一份整会话的最后一枪当整段历史的证人）。
	"not_shown": "不在留存的那一份发射投影里",
	"folded_out": "被折叠移出投影（未送达）",
	# 徽章不带原因：unprovable 背后至少两种洞（本轮投影没留存 / 整会话根本没留存发射投影），
	# 写死"缺按轮留存的最终请求体"对后者是假话。固定种子抽 70/352 会话的 59 个有约束轮次：
	# 47 条判不动里 38 条是 projection_not_in_turn、9 条是 no_retained_projection —— 后者
	# 一份发射投影都没落盘，跟"按轮"无关。原因由 shown_to_model_note 承担（界面与 Markdown 都印）。
	"unprovable": "无法证明是否送达",
	"no_obligation": "没有可比对的约束文本",
}

_OBLIGATION_SOURCE_TEXT = {
	"turn_user_message": "在场的用户原话",
	"resume_user_cue": "续跑契约里的用户追加语",
	"pin": "事后钉上的预期",
}


def shown_to_model_label(state: str) -> str:
	return _SHOWN_TEXT.get(_s(state), "无法判定")


def obligation_source_label(source: str) -> str:
	return _OBLIGATION_SOURCE_TEXT.get(_s(source), _s(source) or "未记录")

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


def _environment_findings(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
	"""外部世界的事实，与"我方形状被拒后引擎降级重打"，要分开放。

	后者被拒的是我方构造的请求体，厂商为什么拒不可见；引擎那条回退判据本身还被
	证明会误判（engine/query_loop.py::_is_tool_pairing_400 记的事故），所以它没有
	资格被算成外部世界的错，但也不能就此从因果链里消失。
	"""
	out: list[Finding] = []
	shaped: list[Finding] = []
	for f in findings:
		if f.status != CONFIRMED_FAULT:
			continue
		if f.rule_id in _ENVIRONMENT_RULES:
			(shaped if _causes.is_shape_rejection(f) else out).append(f)
		elif f.rule_id == "tool_failure" and any(
			_tool_error_party(e.detail) == ENVIRONMENT for e in f.evidence
		):
			out.append(f)
	return out, shaped


def _task_outcome(run: RunEvidence) -> tuple[str, list[EvidenceRef], str]:
	"""任务结局只看验收记录；没有验收就报"无法判定"。

	"没有记录"与"自述完成但没有记录可核"是两件事，分开说：前者对本运行一无所知，
	后者至少有一条可回读的自述。合在一起的后果是这条区分在界面上永远只剩一种取值。
	"""
	verifiers = [p for p in run.pins if _s(p.get("kind")) == "verifier"]
	if not verifiers:
		claims = [
			(row, word)
			for row in _assistant_rows(run)
			if isinstance(row.get("content"), str)
			for word in _CLAIM_WORDS
			if word in str(row.get("content"))
		]
		if claims:
			row, word = claims[0]
			return (
				OUTCOME_SELF_REPORTED,
				[
					EvidenceRef(
						source="transcript",
						locator=_s(row.get("locator")),
						ref_id=_s(row.get("id")),
						detail=f"自述含「{word}」",
					)
				],
				"模型自述完成（{}），但本运行没有验收记录可核对：既不能说通过，也不能说失败。".format(
					"、".join(sorted({w for _, w in claims}))
				),
			)
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


# transcript 按会话存，行内不带轮次身份。用户消息落在回合开始的审计行之前
# （实测早 ~0.9 秒到几十分钟不等，等授权时更久），所以只能按「不晚于本轮最后
# 一条带轮次身份的记录」来界定，不能要求它落在本轮时间区间内。
_OBLIGATION_SCAN_ROWS = 2000


def _last_user_obligation(run: RunEvidence) -> dict[str, Any]:
	"""本轮用户消息里的原话约束：它在场，所以有资格作为判据。

	按轮次界定是必须的：不设上界会让被诊断的历史轮拿到会话里最后一条用户消息
	（属于好几轮之后），于是「本轮的约束」是凭空借来的。上界取本轮最后一条带
	轮次身份记录的时刻；本轮没有带时间戳的记录时不设上界（无从界定，如实记
	``ts_bound=False``）。扫描窗够不到本轮那条消息时如实报 ``outside_scan``，
	绝不退化成「这轮没提要求」。
	"""
	upper = _turn_last_ts(run)
	found: dict[str, Any] = {}
	oldest_seen: float | None = None
	notices_skipped = 0
	try:
		from diagnostics.loss_chain import _resolve_body, _transcript_locator, _transcript_window

		if not _transcript_locator(run.session_id):
			# 没有转录就没有"这一轮人说了什么"可查。报「没有声明的约束」等于把人没说话
			# 和查不到人说过话混成一件事（真实数据 155 轮里 45 轮是这种形状）。
			return {
				"text": "",
				"source": "",
				"locator": "",
				"ref_id": "",
				"created_at": None,
				"state": "no_source",
				"ts_bound": upper is not None,
			}

		rows, _scanned, _total = _transcript_window(run.session_id, _OBLIGATION_SCAN_ROWS)
		for row in reversed(rows):
			row_ts = _f(row.get("ts"))
			if row_ts is not None and (oldest_seen is None or row_ts < oldest_seen):
				oldest_seen = row_ts
			if _s(row.get("role")) != "user":
				continue
			if upper is not None:
				if row_ts is None:
					continue  # 没时间戳就分不清是不是本轮的消息，不猜
				if row_ts > upper + _OBLIGATION_TOLERANCE_SEC:
					continue
			body = _resolve_body(row)
			if not body.strip():
				continue
			cue = resume_user_cue(body) if is_synthetic_user_text(body) else ""
			if is_notice_message(row) or matches_notice_text(body) or (is_synthetic_user_text(body) and not cue):
				# 通报声道落的 role=user、以及没有人的追加语的合成人话轮：不是人的话。
				# 拿它们当"在场的约束"，后面每一步（送达、动作核对、自述比对）都在拿引擎
				# 自己写的话审模型 —— 真实数据里这类行占 role=user 的 5.8%（47/811）。
				notices_skipped += 1
				continue
			found = {
				"text": (cue or body).strip()[:500],
				"source": "resume_user_cue" if cue else "turn_user_message",
				"locator": _s(row.get("_path")),
				"ref_id": _s(row.get("id")),
				"created_at": row.get("ts"),
				"ts_bound": upper is not None,
				"state": "found",
			}
			break
	except Exception:  # noqa: BLE001 — 取不到约束就悬空，不猜
		return {"text": "", "source": "", "locator": "", "ref_id": "", "created_at": None, "state": "unreadable"}
	if found:
		return found
	if upper is not None and oldest_seen is not None and oldest_seen > upper + _OBLIGATION_TOLERANCE_SEC:
		return {
			"text": "",
			"source": "",
			"locator": "",
			"ref_id": "",
			"created_at": None,
			"state": "outside_scan",
			"ts_bound": True,
		}
	if notices_skipped:
		# 扫到的"用户条目"全是引擎写的：报「这轮没提要求」是假话 —— 那是把"没有人的话"
		# 说成"人没说话"。如实报状态，并把跳过的条数带出去。
		return {
			"text": "",
			"source": "",
			"locator": "",
			"ref_id": "",
			"created_at": None,
			"state": "notice_only",
			"notice_count": notices_skipped,
			"ts_bound": upper is not None,
		}
	return {"text": "", "source": "", "locator": "", "ref_id": "", "created_at": None, "state": ""}


def _pin_obligation(run: RunEvidence) -> dict[str, Any]:
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
				"created_at": pin.get("created_at"),
			}
	return {}


def _obligation(run: RunEvidence) -> dict[str, Any]:
	"""选哪句话当约束：当场在场的原话优先。

	事后钉的预期（pin 的时间晚于本轮最后事件）只能用于比对自述，不能反推
	"这一枪把约束弄丢了"——它当时压根不在场。
	"""
	in_turn = _last_user_obligation(run)
	pinned = _pin_obligation(run)
	scan_state = _s(in_turn.get("state"))
	if _s(in_turn.get("text")):
		in_turn["expected_note"] = _s(pinned.get("text"))
		return in_turn
	if pinned:
		pinned["in_turn"] = False
		if scan_state:
			pinned["in_turn_scan"] = scan_state
		return pinned
	out: dict[str, Any] = {"text": "", "source": "", "locator": "", "ref_id": "", "created_at": None}
	if scan_state:
		out["in_turn_scan"] = scan_state
	return out


def _unprovable_note(run: RunEvidence, *, retained_body: bool = False) -> str:
	""""证不出来"要说出是哪一块证据不在场：本轮用了哪个投影、留存的又是哪个。

	只写"无法判断"时，读者分不清这是引擎状态不明还是采集只留一份；把两个标识摆出来，
	这条就成了一句可以拿审计行核对的话。标识缺失时也不许编一个占位符上去。
	``retained_body`` 是调用方递给它的事实：正文确实读到了、只是两边都对不上标识 ——
	没有这个参数时兜底句会把"读到过一份正文"说成"没有留存的投影正文"。
	"""
	used = sorted(_turn_projection_ids(run))
	retained = sorted({_s(p.get("projection_id")) for p in run.projections if _s(p.get("projection_id"))})
	retained_txt = "working 那份留存投影没有可对上的标识" if retained_body else "working 里没有留存的投影正文"
	if used and retained:
		which = f"{scope_word(run)}的审计行带着投影 {'、'.join(p[:12] for p in used[:3])}，working 留存的是 {retained[-1][:12]}"
	elif used:
		which = f"{scope_word(run)}的审计行带着投影 {'、'.join(p[:12] for p in used[:3])}，{retained_txt}"
	elif retained:
		which = f"{scope_word(run)}审计行没有投影标识，无从确认模型用的是哪一份投影"
	elif retained_body:
		which = f"{scope_word(run)}审计行没有投影标识，{retained_txt}"
	else:
		which = f"{scope_word(run)}既没有投影标识也没有留存的投影正文"
	return (
		f"working 只留整会话最后一份发射投影（{which}，可能出自更晚的一轮）："
		"既不能据此说约束送到了，也不能据此说引擎把约束弄丢了"
	)


def _shown_to_model(run: RunEvidence, needle: str, *, obligation_state: str = "") -> dict[str, Any]:
	"""约束是否确实进了模型实际收到的内容。捕获正文优先，其次上一枪实际发送的投影。

	轮次级：两级都必须是本轮的记录（captures 按轮次取，投影按 ``_emitted_projection_in_turn``
	核对）。拿更晚一轮的投影命中／落空来判本轮的送达，就是凭空造出引擎侧故障。

	会话级留一条不对称，因为两个方向的证据强度本来就不同：
	- 命中是真的 —— 留存正文里带着这段用户原话，说明发这具正文时那句话已经存在，它必然晚于约束；
	- 落空不是 —— working 只留整会话最后一枪，更早几枪没落盘，"不在这一份里"分不清
	  "从未进入"与"这一份本来就早于它"。
	真实数据：385 个"审计尾窗没盖到"的会话里 302 个属于前者，7 个被后者判成了引擎丢约束
	（原因条目还带着空证据）。
	"""
	if not needle:
		if obligation_state in {"no_source", "unreadable"}:
			# 约束文本拿不到是因为**没有可查的来源**，不是因为人没说话：徽章必须是"判不动"，
			# 不能是"没有声明的约束"。
			note = (
				f"该会话没有 transcript 文件：{scope_word(run)}用户说过什么无从查起"
				if obligation_state == "no_source"
				else f"transcript 读不出来：{scope_word(run)}用户说过什么无从查起"
			)
			return {"state": "unprovable", "hole": "obligation_source_unavailable", "evidence": [], "note": note}
		return {"state": "no_obligation", "evidence": [], "note": "没有可比对的约束文本"}
	try:
		from diagnostics.loss_chain import _stage_emitted, _stage_provider_body

		body_stage = _stage_provider_body(run, needle)
		if body_stage["state"] == "found":
			return {"state": "shown", "hole": "", "evidence": body_stage["evidence"], "note": "在适配器最终请求体里命中"}
		bound = _emitted_projection_in_turn(run)
		proj_stage = _stage_emitted(run, needle)
		state = _s(proj_stage["state"])
		if state not in {"found", "absent", "folded_out"}:
			# 连可比对的留存正文都没有：这句话说的是"没有记录"，不是"没送到"。
			return {"state": "unprovable", "hole": "no_retained_projection", "evidence": [], "note": proj_stage["note"]}
		if state == "found":
			# 命中本身就是证据：正文里带着这段原话，说明发这具正文时那句话已经存在。
			# 轮次级还要求这份投影属于本轮，否则那是更晚一枪的内容（#13 的裁定）。
			if bound or not _s(run.turn_id):
				return {
					"state": "shown",
					"hole": "",
					"evidence": proj_stage["evidence"],
					"note": "在上一枪实际发送的投影里命中",
				}
			return {
				"state": "unprovable",
				"hole": "projection_not_in_turn",
				"evidence": [],
				"note": _unprovable_note(run, retained_body=True),
			}
		if not bound:
			if _s(run.turn_id):
				# 轮次级：这条洞的名字是"这一枪的投影没留下"，两个标识都要摆出来。
				return {
					"state": "unprovable",
					"hole": "projection_not_in_turn",
					"evidence": [],
					"note": _unprovable_note(run, retained_body=True),
				}
			size = next((_s(e.get("detail")) for e in proj_stage["evidence"]), "")
			return {
				"state": "unprovable",
				"hole": "projection_not_in_turn",
				"evidence": [],
				"note": "working 只留整会话最后一份发射投影（{}），更早几枪没有留存：这段约束不在这一份里，"
				"既不能据此说它从未送达，也不能据此说引擎把它弄丢了".format(size or "字符数未记录"),
			}
		if state == "folded_out":
			return {"state": "folded_out", "hole": "", "evidence": proj_stage["evidence"], "note": proj_stage["note"]}
		return {"state": "not_shown", "hole": "", "evidence": proj_stage["evidence"], "note": "发送投影里没有这段约束"}
	except Exception as exc:  # noqa: BLE001
		return {"state": "unprovable", "hole": "", "evidence": [], "note": f"定位链不可用：{type(exc).__name__}"}


_CLAIM_WORDS = ("测试通过", "已通过", "已完成", "全部通过", "验收通过", "done", "all tests pass")


def _assistant_rows(run: RunEvidence) -> list[dict[str, Any]]:
	"""本轮可归属的 assistant 行：采集器标为「不属于本运行」的行不得算到本轮头上。"""
	return [row for row in run.transcript_rows if row_belongs_to_run(row) and _s(row.get("role")) == "assistant"]


def _assistant_text(run: RunEvidence) -> str:
	parts: list[str] = []
	for row in _assistant_rows(run):
		if isinstance(row.get("content"), str):
			parts.append(row["content"])
	return " ".join(parts)


def _self_report_contradiction(run: RunEvidence, outcome: str) -> Finding | None:
	"""模型自述与验收不符：措辞按事实比对，不评价。

	只在**确有验收记录且记录说了相反的话**时下这条结论。``not_accepted`` 的含义是
	"本运行一条验收记录都没有"，拿它当"验收记录显示…"来指控自述不符，是在凭空造
	一份不存在的记录 —— 自述没有证据支撑是另一件事，由任务结局那一栏说。
	"""
	if outcome not in {OUTCOME_FAIL, OUTCOME_VERIFIER_ERROR}:
		return None
	joined = _assistant_text(run)
	if not joined:
		return None
	hits = [w for w in _CLAIM_WORDS if w in joined]
	if not hits:
		return None
	# 证据指针只指真的写了那句自述的行，且必须是本轮可归属的行。
	sources = [
		row
		for row in _assistant_rows(run)
		if isinstance(row.get("content"), str) and any(w in row["content"] for w in hits)
	] or _assistant_rows(run)[:1]
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
			for row in sources[:5]
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


_ACTION_MARKERS = (
	"pytest", "vitest", "npm test", "npm run test", "npx vitest", "tsc", "jest",
	"go test", "cargo test", "测试", "验收", "跑一遍",
)


def _required_action_unmet(run: RunEvidence, obligation_text: str) -> dict[str, Any]:
	"""「被要求跑测试/调用工具，本轮没做，也没被权限挡住」——可机器核对的那一条。

	判据全部来自既有记录：约束正文的关键词、本轮工具调用参数与 command_summary、
	权限结果、以及回答里的自述完成词。任何一环缺记录都退回 unknown。

	权限结果按 rules.permission_outcome 的读法判定：真实的 DENY 行（只读门与策略
	DENY 写的 permission.denied）既不带 approved 也不带 outcome，只有
	permission_action / permission_reason_code，按「没挡住」读会把执行层的拒绝算到
	模型头上。
	"""
	text = _s(obligation_text)
	low = text.lower()
	markers = [m for m in _ACTION_MARKERS if m in low or m in text]
	if not markers:
		return {"state": "no_action_required", "evidence": [], "note": "约束里没有可核对的动作要求"}
	own_permissions = turn_scoped(run.permissions, run.turn_id)
	blocked = [p for p in own_permissions if permission_blocked(p)]
	own_tools = turn_scoped(run.tool_calls, run.turn_id)
	seen_cmds: list[str] = []
	for tool in own_tools:
		for source in (tool.started, tool.finished):
			if isinstance(source, dict):
				cmd = _s(source.get("command_summary")) or _s(source.get("command"))
				if cmd:
					seen_cmds.append(cmd)
		for row in run.transcript_rows:
			if row.get("tool_call_id") == tool.tool_use_id and isinstance(row.get("content"), str):
				seen_cmds.append(row["content"])
		if tool.tool_name in {"Bash", "job_run"}:
			seen_cmds.append(tool.tool_name)
	joined = " ".join(seen_cmds).lower()
	done = [m for m in markers if m in joined]
	if done:
		return {"state": "action_present", "evidence": [], "note": f"{scope_word(run)}已见动作标记：{', '.join(done)}"}
	if blocked:
		return {
			"state": "blocked_by_permission",
			"evidence": [
				EvidenceRef(
					source="audit",
					locator=source_locator(run, "audit"),
					ref_id=f"L{_s(p.get('line_no'))}",
					detail=f"{_s(p.get('kind'))} 结果={permission_outcome(p)}",
				)
				for p in blocked[:3]
			],
			"note": "该动作被执行层挡下：不能算模型没做",
		}
	unrecorded = [p for p in own_permissions if permission_outcome_unrecorded(p)]
	if unrecorded:
		return {
			"state": "permission_outcome_unrecorded",
			"evidence": [
				EvidenceRef(
					source="audit",
					locator=source_locator(run, "audit"),
					ref_id=f"L{_s(p.get('line_no'))}",
					detail=f"{_s(p.get('kind'))} 未记录 approved / outcome / permission_action",
				)
				for p in unrecorded[:3]
			],
			"note": "权限行没有落审批结果：分不清是放行了还是根本没记录，不能据此判动作没做",
		}
	if not own_tools and not seen_cmds:
		return {"state": "no_tool_records", "evidence": [], "note": f"{scope_word(run)}没有任何工具记录：分不清是没调用还是没采集"}
	if not seen_cmds:
		# 命令正文没落账就不许下"没跑"的结论：真实审计里 tool.* 行不带 command /
		# command_summary（入参摘要只写在 permission.* 行上，见待批 #36），
		# "N 次调用里没有一项含该标记"这句话没有依据。
		return {
			"state": "commands_unrecorded",
			"evidence": [
				EvidenceRef(
					source="audit",
					locator=source_locator(run, "audit"),
					ref_id=f"L{_s((t.started or {}).get('line_no'))}",
					detail=f"{t.tool_name} 未记录命令正文",
				)
				for t in own_tools[:3]
			],
			"note": f"{scope_word(run)} {len(own_tools)} 次工具调用没有落下命令正文：分不清是没跑还是没记",
		}
	claims = [w for w in _CLAIM_WORDS if w in _assistant_text(run)]
	if not claims:
		return {"state": "not_claimed_done", "evidence": [], "note": "回答没有自述完成：动作没做也不能据此判模型的错"}
	return {
		"state": "action_missing",
		"evidence": [
			EvidenceRef(
				source="transcript",
				locator=source_locator(run, "transcript"),
				ref_id="",
				detail=f"要求动作标记：{', '.join(markers[:3])}",
			)
		],
		"note": f"约束要求 {', '.join(markers[:3])}，{scope_word(run)} {len(own_tools)} 次工具调用里没有一项含该标记，且未被权限挡住",
	}


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


def _no_records_verdict(run: RunEvidence) -> dict[str, Any]:
	"""本轮无记录的裁决：不指责任何一方，也不把会话级 leftovers 当成本轮证据。

	「无记录」不等于「没发生」——采集都是尾窗，窗口可能压根没覆盖这一轮。
	"""
	gap = (
		f"本轮无记录：采集窗口内没有一条带 turn_id={_s(run.turn_id)} 的记录，"
		"责任划分与因果链都无据可建。"
	)
	return {
		"responsibility": UNDETERMINED,
		"responsibility_label": PARTY_LABEL[UNDETERMINED],
		"why": (
			"本轮无记录：窗口里没有属于这一轮的任何一条记录，因此既不能判引擎有错，"
			"也不能判模型有错。无记录不等于没发生——审计与各账本都按尾窗采集，"
			"窗口可能没覆盖到这一轮；不得把同会话别处的记录算给本轮。"
		),
		"primary_cause": _causes.NOT_DETERMINED,
		"primary_cause_label": _causes.CAUSE_LABEL[_causes.NOT_DETERMINED],
		"cause_statement": "本轮无记录：只能报采集缺口，不能报原因。",
		"causes": [
			{
				"code": _causes.NOT_DETERMINED,
				"label": _causes.CAUSE_LABEL[_causes.NOT_DETERMINED],
				"party": UNDETERMINED,
				"proves": "本轮没有一条带自己身份的记录：这是采集缺口，不是执行结果",
				"does_not_prove": "不等于没有失败，也不等于成功；无记录只说明记录里没有",
				"evidence": [],
				"evidence_total": 0,
			}
		],
		"task_outcome": OUTCOME_NOT_ACCEPTED,
		"task_outcome_label": OUTCOME_LABEL[OUTCOME_NOT_ACCEPTED],
		"obligation": {
			"source": "",
			"locator": "",
			"ref_id": "",
			"created_at": None,
			"excerpt": "",
		},
		"shown_to_model": "unprovable",
		"shown_to_model_note": gap,
		"engine_confirmed": 0,
		"environment_confirmed": 0,
		"transport_gap": False,
		"chain": [],
		"missing_evidence": [
			gap,
			"本轮无记录不等于没发生：先扩大审计/账本的采集窗口，或给记录补上轮次身份，再谈归因",
			"没有 verifier 记录：任务是否完成无法判定",
		],
		"not_claimed": [
			"不宣称本轮正常：规则集本轮没有可核对的记录",
			"不把会话级记录（transcript / working / usage）算给本轮",
			"不给概率或加权总分",
		],
		"no_turn_records": True,
	}


def attribute_fault(run: RunEvidence, findings: list[Finding]) -> dict[str, Any]:
	"""给出责任方、任务结局、因果链，以及"要改判还缺哪条记录"。"""
	if no_turn_records(run):
		return _no_records_verdict(run)
	# 本轮没有一条属于自己的记录：不指责任何一方，也不得把会话级 leftovers 当证据。
	own_tools = turn_scoped(run.tool_calls, run.turn_id)
	engine = _engine_findings(findings)
	environment, shape_rejected = _environment_findings(findings)
	transport, transport_suspect = _transport_findings(findings)
	outcome, outcome_refs, outcome_note = _task_outcome(run)

	tool_parties: dict[str, list[Finding]] = {}
	for f in findings:
		if f.rule_id != "tool_failure" or f.status != CONFIRMED_FAULT:
			continue
		for ev in f.evidence:
			tool_parties.setdefault(_tool_error_party(ev.detail), []).append(f)

	obligation = _obligation(run)
	shown = _shown_to_model(run, _s(obligation.get("text"))[:120], obligation_state=_s(obligation.get("in_turn_scan")))
	self_report = _self_report_contradiction(run, outcome)
	# 要求来源可以是当场原话，也可以是事后钉上的预期（人证）；
	# 但"引擎把约束弄丢了"这一条只认当场原话。
	requirement_text = " ".join(
		x for x in (_s(obligation.get("text")), _s(obligation.get("expected_note"))) if x
	)
	unmet = _required_action_unmet(run, requirement_text)

	# 事后才钉的预期没有资格指控"这一枪把约束弄丢了"：它当时压根不在场。
	# 只有"当场在场"的约束才有资格指控上下文丢了它。
	after_the_fact = bool(obligation.get("text")) and obligation.get("in_turn") is False
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
	for f in shape_rejected:
		_step(
			f.boundary,
			f.phenomenon + "；被拒的是我方提交的形状，降级重打至少多一次请求，厂商为什么拒不可见",
			UNDETERMINED,
			f.evidence,
		)
	for kind, items in sorted(tool_parties.items()):
		for f in items[:1]:
			_step(f.boundary, f.phenomenon, kind if kind != UNDETERMINED else UNDETERMINED, f.evidence)
	for f in transport:
		_step("sse_gui", f.phenomenon, ENGINE, f.evidence)
	for f in transport_suspect:
		_step("sse_gui", f.phenomenon, UNDETERMINED, f.evidence)
	if self_report is not None:
		_step(self_report.boundary, self_report.phenomenon, MODEL, self_report.evidence)
	if unmet["state"] == "action_missing":
		# 把"没做"算到模型头上，前提是那句要求确实送达过：shown 证不出来时
		# 只能说动作没有对应记录，指责任何一方都是凭空。
		delivered = shown["state"] == "shown"
		_step(
			"tool_permission",
			f"要求动作 {'、'.join(sorted({m for m in _ACTION_MARKERS if m in requirement_text.lower() or m in requirement_text}))}，"
			f"{scope_word(run)} {len(own_tools)} 次工具调用里没有一项对应，且未被权限挡住；回答仍自述完成"
			+ ("" if delivered else "；该要求是否送达无法证明，不指责任何一方"),
			MODEL if delivered else UNDETERMINED,
			unmet["evidence"],
		)
	elif unmet["state"] == "blocked_by_permission":
		_step("tool_permission", "被要求的动作由执行层挡下", ENGINE, unmet["evidence"])
	elif unmet["state"] == "permission_outcome_unrecorded":
		_step(
			"tool_permission",
			"权限行未落审批结果：这一枪到底放没放行没有记录，动作没做的归属判不了",
			UNDETERMINED,
			unmet["evidence"],
		)
	elif unmet["state"] == "commands_unrecorded":
		_step(
			"tool_permission",
			f"{scope_word(run)}工具调用没有落下命令正文：被要求的动作做没做无从核对",
			UNDETERMINED,
			unmet["evidence"],
		)
	if obligation.get("text") and not after_the_fact:
		_step(
			"instruction_context",
			"约束来源={}（{}）；是否进入模型实际收到的内容={}".format(
				obligation_source_label(obligation.get("source")),
				_s(obligation.get("ref_id"))[:16],
				shown_to_model_label(shown["state"]),
			),
			MODEL if shown["state"] == "shown" else UNDETERMINED,
			_obligation_step_evidence(obligation, shown),
		)
	# 折叠移出与从未进入都是"该在场却没送到"，只是前者能定位到具体一级。
	constraint_lost = shown["state"] in {"not_shown", "folded_out"} and not after_the_fact
	if constraint_lost:
		_step(
			"wsc_fold",
			"用户声明的约束在源历史里存在，但不在最后发射的投影里",
			ENGINE,
			# 指针指约束自己的那条记录（transcript / pin）与发射级证据，
			# 不把 transcript 路径标成 working：每个来源都得说清自己是谁。
			_obligation_step_evidence(obligation, shown),
		)
	if outcome_refs:
		# 验收只说明"任务没完成"，不指责任何一方：归责要靠送达证据或自述矛盾。
		_step("file_verifier", outcome_note, UNDETERMINED, outcome_refs)

	# --- 失败原因（机器可读；与归属分开，一个原因可以不属于任何一方）---
	tool_error_kinds: dict[str, list[dict[str, Any]]] = {}
	for f_item in findings:
		if f_item.rule_id != "tool_failure" or f_item.status != CONFIRMED_FAULT:
			continue
		for ev in f_item.evidence:
			import re as _re

			match = _re.search(r"error_kind=([A-Z_]+)", ev.detail)
			kind = match.group(1) if match else "UNCLASSIFIED"
			tool_error_kinds.setdefault(kind, []).append(ev.to_dict())
	flag_evidence: dict[str, list[dict[str, Any]]] = {}
	if constraint_lost:
		# 指针指约束自己的那条记录（transcript / pin）与发射级证据：每条原因都得能回到原始记录，
		# 界面才会出现"复制定位"而不是只有一句断言。
		flag_evidence[
			_causes.CONSTRAINT_FOLDED if shown["state"] == "folded_out" else _causes.CONTEXT_DROPPED
		] = [r.to_dict() for r in _obligation_step_evidence(obligation, shown)]
	if unmet["state"] == "blocked_by_permission":
		flag_evidence[_causes.PERMISSION_BLOCKED] = [e.to_dict() for e in unmet["evidence"]]
	if unmet["state"] == "action_missing":
		flag_evidence[_causes.ACTION_SKIPPED] = [e.to_dict() for e in unmet["evidence"]]
	if outcome_refs:
		flag_evidence[
			_causes.ACCEPT_FAILED if outcome == OUTCOME_FAIL else _causes.ACCEPT_ERROR
		] = [e.to_dict() for e in outcome_refs]
	if transport:
		flag_evidence[_causes.DISPLAY_GAP] = [e.to_dict() for f_item in transport for e in f_item.evidence]
	cause_list = _causes.derive(
		findings=findings,
		constraint_lost=constraint_lost,
		constraint_mode=_s(shown["state"]),
		permission_blocked=(
			unmet["state"] == "blocked_by_permission"
			or any(f_item.rule_id == "permission_block" and f_item.status == CONFIRMED_FAULT for f_item in findings)
		),
		action_skipped=(unmet["state"] == "action_missing" and shown["state"] == "shown"),
		self_report=self_report,
		outcome=outcome,
		tool_error_kinds=tool_error_kinds,
		display_gap=bool(transport or transport_suspect),
		# 执行面上一条记录都没有时，"没有可判定的验收记录"不是一条关于这次执行的原因，
		# 只是什么都没观察到 —— 与轮次视图的「本轮无记录」同一裁定（fault_split::_no_records_verdict）。
		# 判据与主原因措辞共用 causes.execution_observed，不留第二份口径。
		observed=_causes.execution_observed(run),
		flag_evidence=flag_evidence,
	)
	cause_head = _causes.primary(cause_list)

	# --- 归属判定 ---
	# 被要求的动作由执行层挡下，本身就是引擎侧事实，不依赖调用方传没传 findings。
	engine_bound = bool(
		engine or transport or constraint_lost or ENGINE in tool_parties
		or unmet["state"] == "blocked_by_permission"
	)
	environment_bound = bool(environment or ENVIRONMENT in tool_parties)
	# 光"验收失败"不足以判模型的错：本轮开始前的红测看起来一模一样。
	# 只有能归到本轮行为上的矛盾才算：自述与验收不符，或被要求的动作确实没做。
	contradiction = self_report is not None or unmet["state"] == "action_missing"
	model_provable = shown["state"] == "shown" and bool(contradiction)

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
		if after_the_fact:
			why = (
				"预期是在这一枪之后才钉上的，无法证明它当时送到了模型；"
				"验收失败只说明任务没完成，不足以指责任何一方。"
			)
		elif not obligation.get("text"):
			why = "没有可核对的约束声明：只能报任务结局，不能判是谁的错。"
		elif shown["state"] == "shown":
			if outcome == OUTCOME_FAIL:
				why = (
					f"约束确实送到了模型，验收也失败了，但{scope_word(run)}没有可归到模型行为上的矛盾"
					"（既没抓到「自述完成 vs 验收不符」，也没抓到「要求的动作没做」）："
					f"{scope_word(run)}之前的红测会呈现完全一样的形状，所以只能报任务结局，不指责任何一方。"
				)
			else:
				why = (
					"约束确实送到了模型，但没有可机器判定的矛盾"
					"（没有验收记录，也没抓到「自述完成 vs 要求动作缺失」）："
					"只能报任务结局，不指责任何一方。"
				)
		else:
			why = "没有任何一级记录能证明约束送到了模型，或矛盾不可机器判定。"

	missing: list[str] = []
	# 审批结果没落账这件事本身要可见——即使本轮没有可核对的动作要求，
	# 「这一枪放没放行」未知也是取证缺口，不是没有问题。
	silent_permissions = [
		p for p in turn_scoped(run.permissions, run.turn_id) if permission_outcome_unrecorded(p)
	]
	if shown["state"] == "no_obligation":
		if _s(obligation.get("in_turn_scan")) == "outside_scan":
			missing.append(
				f"{scope_word(run)}的用户原话在 transcript 扫描窗（最近 {_OBLIGATION_SCAN_ROWS} 行）之外：没有约束正文可比对，"
				"不能据此说这轮没提要求"
			)
		elif _s(obligation.get("in_turn_scan")) == "notice_only":
			missing.append(
				f"{obligation.get('notice_count', 0)} 条「用户条目」是引擎写的（通报 / 后台完成通知 / 续跑指令），不是人打的话："
				f"{scope_word(run)}没有可比对的用户原话，但这不等于{scope_word(run)}没提要求"
			)
		else:
			missing.append("没有声明的预期：用「标记这轮结果不对」写下预期结果，才能判模型侧")
	if obligation.get("text") and not obligation.get("ts_bound"):
		missing.append(f"{scope_word(run)}没有带时间戳的记录：无法界定这条用户原话属不属于这一范围")
	if unmet["state"] == "permission_outcome_unrecorded" or silent_permissions:
		missing.append(
			f"{len(silent_permissions)} 条权限结束行未记录 approved / outcome / permission_action："
			"这一枪放行还是拦下没有记录，不能据此判动作没做"
		)
	if shown["state"] == "unprovable":
		if _s(shown.get("hole")) == "obligation_source_unavailable":
			missing.append(
				f"该会话没有 transcript 文件（或读不出来）：{scope_word(run)}的用户原话无从查起，"
				f"所以既不能说{scope_word(run)}没提要求，也不能说约束没送到模型"
			)
		elif _s(shown.get("hole")) == "projection_not_in_turn":
			missing.append(
				"working 只留整会话最后一份发射投影，且无法核对它属不属于这次运行：要判约束送没送到，"
				"需要开 capture 按轮留住适配器最终请求体"
			)
		else:
			missing.append("未开启可复现记录且无上一枪投影：开 capture 后重跑才能得到最终请求体正文")
	if outcome in {OUTCOME_NOT_ACCEPTED, OUTCOME_SELF_REPORTED} and shown["state"] == "shown":
		missing.append("没有验收记录：补一条 verifier（或让模型跑被要求的测试）才能判完没完成")
	if constraint_lost and shown["state"] == "not_shown":
		missing.append("约束未进入发送内容：还需候选/选择两级的账本才能定位到具体一级")
	if constraint_lost and shown["state"] == "folded_out":
		missing.append("约束落在折叠区间内：需复核这条是否该被保留，而不是找别的边界")
	if after_the_fact:
		missing.append("预期是事后钉上的：不能据此判这一枪丢了约束；要判需在下一枪前就固定预期")
	if outcome in {OUTCOME_NOT_ACCEPTED, OUTCOME_SELF_REPORTED}:
		missing.append("没有 verifier 记录：任务是否完成无法判定")
	if outcome == OUTCOME_FAIL and contradiction is False:
		missing.append(
			f"只有「验收失败」这一条：需要{scope_word(run)}的自述或动作证据，否则红测可能先于{scope_word(run)}存在"
		)
	if not run.captures:
		missing.append("缺适配器最终请求体：投影之后的变换不可见")

	verdict: dict[str, Any] = {
		"responsibility": party,
		"responsibility_label": PARTY_LABEL[party],
		"why": why,
		"primary_cause": cause_head["code"],
		"primary_cause_label": cause_head["label"],
		"cause_statement": _causes.statement(cause_list, run),
		"causes": cause_list,
		"task_outcome": outcome,
		"task_outcome_label": OUTCOME_LABEL.get(outcome, outcome),
		"obligation": {k: v for k, v in obligation.items() if k != "text"} | {"excerpt": _s(obligation.get("text"))[:160]},
		"shown_to_model": shown["state"],
		"shown_to_model_note": shown["note"],
		"engine_confirmed": len(engine),
		"environment_confirmed": len(environment),
		"transport_gap": bool(transport),
		"no_turn_records": False,
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
