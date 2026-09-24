"""确定性诊断规则：每条只允许下它能证明的结论。

写作纪律（设计文档第 6 节）：

* 现象用事实型措辞，不含"应该 / 优先 / 不要再"。
* ``confirmed_fault`` 只在记录的不变量被证明破坏时使用。
* 结束记录缺失、进程未上报、正文未采集，一律 ``unknown`` + 写明覆盖缺口。
* 证据引用指回原始记录（审计行号 / transcript 行 / usage 行 / manifest 字段）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from diagnostics.collect import RunEvidence
from diagnostics.identity import (
	CONFIRMED_FAULT,
	SUSPECTED_CAUSE,
	UNKNOWN,
	EvidenceRef,
	Finding,
	_s,
)

RULESET_VERSION = 1

# model.finished 里这些状态属于"已确认的尝试结果"，不自动等于任务失败。
_OK_MODEL_STATUSES = {"ok", "started", ""}
_FAILED_MODEL_STATUSES = {"failed", "aborted", "protocol_fallback", "retry"}


def _loc(run: RunEvidence) -> str:
	window = run.window("audit")
	return window.locator if window else "audit:unavailable"


def _event_ref(run: RunEvidence, event: Any, detail: str = "") -> EvidenceRef:
	return event.ref(_loc(run), detail)


def _kv(event: Any, key: str) -> str:
	return _s(event.row.get(key))


def _sig(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


# ---------- 权限结果的唯一读法（rules 与 fault_split 共用）----------
#
# 真实审计里权限行有三类写法（写入方：engine/permission_coordinator.py、
# permissions/store.py、tools/tool_registry.py）：
#
# * ``permission.resolved``：带 ``approved``（bool）与 ``outcome``
#   （``user_decided`` / ``timeout`` / ``aborted``）。
# * 只读门与策略 DENY 写的 ``permission.denied``：既没有 ``approved`` 也没有
#   ``outcome``，只有 ``permission_action``（``allow`` / ``deny`` / ``ask``，取自
#   ``PermissionDecision`` 的值）、``permission_rule_id``、``permission_reason_code``。
# * 旧记录：两个结果字段都没有。
#
# 把「没有 approved」读成「没被挡住」会让真实 DENY 行被判成放行；把它读成
# 「被挡住」又会把「没记录结果」判成故障。所以两侧共用下面这一个函数。

_DENY_ACTIONS = {"deny", "denied"}
_BLOCKED_OUTCOMES = {"denied", "timeout", "aborted"}

OUTCOME_DENIED = "denied"
OUTCOME_ALLOWED = "allowed"
OUTCOME_UNRECORDED = "unrecorded"


def permission_outcome(row: dict[str, Any]) -> str:
	"""一条权限审计行的读数：``denied`` / ``allowed`` / ``timeout`` / ``aborted`` / ``unrecorded``。"""
	kind = _s(row.get("kind"))
	if kind.startswith("permission.denied"):
		return OUTCOME_DENIED
	if _s(row.get("permission_action")).strip().lower() in _DENY_ACTIONS:
		return OUTCOME_DENIED
	outcome = _s(row.get("outcome")).strip().lower()
	if outcome in _BLOCKED_OUTCOMES:
		return outcome
	approved = row.get("approved")
	if approved is True:
		return OUTCOME_ALLOWED
	if approved is False:
		return OUTCOME_DENIED
	return OUTCOME_UNRECORDED


def permission_blocked(row: dict[str, Any]) -> bool:
	"""执行层把动作挡住了吗（拒绝 / 超时 / 中止都算）。"""
	return permission_outcome(row) in _BLOCKED_OUTCOMES


def permission_outcome_unrecorded(row: dict[str, Any]) -> bool:
	"""只在「这应当是一条结果行、却没记下任何结果」时为真。

	``permission.pending`` 与 ``permission.grant.*`` 本来就不带审批结果，
	把它们算成未记录会造出满屏假缺口。
	"""
	kind = _s(row.get("kind"))
	if kind.startswith(("permission.pending", "permission.grant.")):
		return False
	return permission_outcome(row) == OUTCOME_UNRECORDED


# ---------- 轮次界定：会话级记录不得算到本轮头上 ----------


def row_belongs_to_run(row: dict[str, Any]) -> bool:
	"""transcript 行的轮次归属。

	transcript 行本身不带轮次身份，采集器按本运行的 tool_use_id 锚定：锚不上的
	显式标 ``in_run=False``（那是同会话别的轮次的记录），没标的采集器没判定过。
	只有 ``in_run=False`` 是确定的反证，必须排除；其余按原样交给规则。
	"""
	return row.get("in_run") is not False


def collection_attempted(run: RunEvidence) -> bool:
	"""windows 非空说明采集真的跑过并看过这个会话；手工构造的视图不适用「本轮无记录」。"""
	return bool(run.windows)


def turn_has_records(run: RunEvidence) -> bool:
	"""本轮有没有属于自己的一条记录（只看带轮次身份的东西）。"""
	if not run.turn_id:
		return True
	if run.events_for_turn():
		return True
	tid = run.turn_id
	for mr in run.model_requests:
		if _s(mr.turn_id) == tid:
			return True
	for tc in run.tool_calls:
		if _s(tc.turn_id) == tid:
			return True
	for bucket in (run.permissions, run.pins, run.captures, run.fold_rows, run.jobs, run.usage_rows):
		for row in bucket:
			if _s(row.get("turn_id")) == tid:
				return True
	for row in run.transcript_rows:
		if row.get("in_run") is True:
			return True
	return False


def no_turn_records(run: RunEvidence) -> bool:
	"""「采集确实跑过，但这个轮子没有任何属于自己的记录」。"""
	return bool(run.turn_id) and collection_attempted(run) and not turn_has_records(run)


def source_locator(run: RunEvidence, source: str) -> str:
	"""按来源名取窗口定位符；取不到就返回空串，绝不拿别的来源凑数。"""
	window = run.window(source)
	return _s(window.locator) if window else ""


def turn_scoped(rows: list[Any], turn_id: str, *, key: str = "turn_id") -> list[Any]:
	"""排除带 *别的* 轮次身份的记录；不带轮次身份的行保留。

	审计按会话采集，跨轮落账的 permission 行与不带 turn_id 的旧行会混进合并结果。
	把它们算给本轮就是误归因；没有身份信息时无从排除，只能保留并由规则的
	coverage_gap 说清这一步判不了。
	"""
	tid = _s(turn_id)
	if not tid:
		return list(rows)
	out: list[Any] = []
	for row in rows:
		value = _s(row.get(key)) if isinstance(row, dict) else _s(getattr(row, key, ""))
		if value and value != tid:
			continue
		out.append(row)
	return out


# ---------- R1 工具调用 / 结果不成对 ----------


def check_tool_pair_integrity(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	refs: list[EvidenceRef] = []
	for manifest in run.projections:
		for err in manifest.get("invariant_errors") or []:
			name = _s(err)
			if not (name.startswith("unresolved_tool_calls") or name.startswith("orphan_tool_results")):
				continue
			refs.append(
				EvidenceRef(
					source="projection",
					locator=_s(manifest.get("locator")),
					ref_id=_s(manifest.get("projection_id")),
					detail=f"invariant_errors:{name}",
				)
			)
	if refs:
		findings.append(
			Finding(
				rule_id="tool_pair_integrity",
				rule_version=RULESET_VERSION,
				phenomenon="投影结构检查报错：发射出的投影里 tool call 与 tool result 不成对",
				boundary="adapter",
				component="上下文组装（projection manifest 结构不变量）",
				status=CONFIRMED_FAULT,
				evidence=refs,
				impact="该形状会被厂商直接拒（400），后续每条消息都可能带着同一个坏形状重发。",
				coverage_gap="manifest 只保存最后一份；本运行更早的投影只能靠审计里的 projection_id 关联。",
				allowed_conclusion="可确认某个边界上配对被破坏；不足以解释本轮任务失败的全部原因。",
			)
		)

	# 审计侧：有 started 无 finished 的工具调用。
	scoped = run.events_for_turn()
	started_only = [t for t in turn_scoped(run.tool_calls, run.turn_id) if t.started and not t.finished]
	if started_only and not _run_has_later_activity(scoped):
		# 没有更晚的活动可参照，无法区分"还在跑"和"没了结束记录"。
		findings.append(
			Finding(
				rule_id="tool_pair_integrity",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(started_only)} 个工具调用有开始记录、无结束记录，且其后无更晚活动可参照",
				boundary="tool_permission",
				component="工具分发",
				status=UNKNOWN,
				evidence=[
					EvidenceRef(
						source="audit",
						locator=_loc(run),
						ref_id=f"L{_s((t.started or {}).get('line_no'))}",
						detail=f"tool.started {t.tool_name}",
					)
					for t in started_only
				],
				impact="无法判断工具仍在执行还是结束记录缺失。",
				coverage_gap="结束记录缺失本身不证明进程已死；正常长任务会命中同一形状。",
				allowed_conclusion="只能说记录不完整，不能说执行失败。",
			)
		)
	return findings


def _run_has_later_activity(events: list[Any]) -> bool:
	kinds = {e.kind for e in events}
	return bool(kinds & {"model.started", "model.finished", "tool.finished"}) and "tool.finished" in kinds


# ---------- R2 指令 / 配置漂移 ----------

# 快照 id 是 (session_id, cwd, mode, revision, runtime_profile_id) 的哈希（见
# permissions/trace.py）：授权的增删会让它合法变化，所以「一个轮里出现多个值」
# 本身不是不变量破坏。只有窗口里找不到这些增删行时，才需要说"判不了"。
_SNAPSHOT_EXPLAINING_KINDS = ("permission.grant.added", "permission.grant.revoked")


def _snapshot_explainers(run: RunEvidence) -> list[dict[str, Any]]:
	"""本轮采集窗口里的授权增删行：它们在场，快照 id 变化就有账可查。"""
	seen: set[str] = set()
	out: list[dict[str, Any]] = []
	candidates: list[dict[str, Any]] = [row for row in run.permissions if _s(row.get("kind")).startswith(_SNAPSHOT_EXPLAINING_KINDS)]
	candidates += [e.row for e in run.events if _s(e.kind).startswith(_SNAPSHOT_EXPLAINING_KINDS)]
	for row in candidates:
		key = f"{_s(row.get('kind'))}|{_s(row.get('line_no'))}|{_s(row.get('grant_id'))}"
		if key in seen:
			continue
		seen.add(key)
		out.append(row)
	return out


def check_instruction_drift(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	scoped = [e for e in run.events_for_turn() if e.kind.startswith(("model.", "tool."))]
	hashes: dict[str, list[str]] = {}
	for event in scoped:
		for field in ("tool_schema_hash", "tool_surface_id", "permission_snapshot_id", "runtime_profile_id"):
			value = _kv(event, field)
			if value:
				hashes.setdefault(field, []).append(value)
	for field, values in hashes.items():
		uniq = sorted(set(values))
		if len(uniq) <= 1:
			continue
		is_snapshot = field == "permission_snapshot_id"
		if is_snapshot and _snapshot_explainers(run):
			# 窗口里有授权增删行：变化有账可查，不作为故障上报。
			continue
		status = UNKNOWN if is_snapshot else SUSPECTED_CAUSE
		if is_snapshot:
			gap = (
				"授权增删行（permission.grant.added / permission.grant.revoked）不带 session_id / turn_id，"
				"不会进入按会话过滤的审计窗口，因此本轮无法判断快照变化是否有账可查；"
				"快照 id 也由 cwd 与 mode 参与计算，这两项不在审计行里。"
			)
			allowed = "只能说这一轮里快照标识不止一个且窗口内没有解释它的记录；不能据此判定权限层出了故障。"
		else:
			gap = "轮内可见；跨轮的指令正文变化不在本规则范围，由 A0 静态差异负责。"
			allowed = "可确认哪一段标识变了；不能据此判定变好或变坏。"
		findings.append(
			Finding(
				rule_id="instruction_drift",
				rule_version=RULESET_VERSION,
				phenomenon=f"同一轮内 {field} 出现 {len(uniq)} 个不同取值",
				boundary="instruction_context",
				component=f"上下文组装（{field}）",
				status=status,
				evidence=[
					_event_ref(run, e, f"{field}={_kv(e, field)}")
					for e in scoped
					if _kv(e, field)
				][:20],
				impact=f"变化值：{', '.join(v[:12] for v in uniq)}（只报事实，不评价哪一版更好）。",
				coverage_gap=gap,
				allowed_conclusion=allowed,
			)
		)
	return findings


# ---------- R3 冷引用 / 可回读性 ----------


def check_cold_references(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	broken_all = [
		row
		for row in run.transcript_rows
		if row.get("body_state") in {"missing_blob", "resolve_failed", "absent"} and row.get("content_ref")
	]
	# 只把本轮的记录算成本轮的证据：transcript 按会话采集，锚不到本运行的行属于别的轮次。
	broken = [row for row in broken_all if row_belongs_to_run(row)]
	foreign = [row for row in broken_all if not row_belongs_to_run(row)]
	refs = [
		EvidenceRef(
			source="transcript",
			locator=_s(row.get("locator")),
			ref_id=_s(row.get("id")) or f"L{_s(row.get('line_no'))}",
			detail=f"body_state={_s(row.get('body_state'))} ref={_s(row.get('content_ref'))}",
		)
		for row in broken
	]
	for spill in [e for e in run.events_for_turn() if e.kind == "tool.spill"]:
		path = _kv(spill, "path")
		if path:
			from pathlib import Path

			if not Path(path).is_file():
				refs.append(spill.ref(_loc(run), f"spill 文件缺失: {path}"))
				broken.append({"spill": path})
	if refs:
		findings.append(
			Finding(
				rule_id="cold_reference",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(refs)} 处冷层引用不可回读（正文 blob 解引用失败或 spill 路径已不存在）",
				boundary="wsc_fold",
				component="可恢复性（transcript blob / 输出预算 spill）",
				status=CONFIRMED_FAULT,
				evidence=refs,
				impact="进冷层的内容声称可回读但实际读不到；原文已不可恢复。",
				coverage_gap="只能验证句柄存在与可解引用，无法验证模型是否真的尝试回读。",
				allowed_conclusion="可确认恢复性故障；定位到生成该句柄的步骤。",
			)
		)
	elif foreign:
		findings.append(
			Finding(
				rule_id="cold_reference",
				rule_version=RULESET_VERSION,
				phenomenon=f"本会话窗口里有 {len(foreign)} 处不可回读的冷层引用，但都不带本轮身份",
				boundary="wsc_fold",
				component="可恢复性（transcript blob / 输出预算 spill）",
				status=UNKNOWN,
				evidence=[
					EvidenceRef(
						source="transcript",
						locator=_s(row.get("locator")),
						ref_id=_s(row.get("id")) or f"L{_s(row.get('line_no'))}",
						detail=f"body_state={_s(row.get('body_state'))} 不属于本运行的工具调用",
					)
					for row in foreign[:10]
				],
				impact="这些引用属于同会话的别处：既不能记到本轮，也不能据此说本轮干净。",
				coverage_gap="transcript 行不带轮次身份，采集器只按本运行的 tool_use_id 锚定；锚不上的行无法归轮。",
				allowed_conclusion="只能说本轮没有可归属的冷引用，不能说本轮的恢复性没问题。",
			)
		)
	for manifest in run.projections:
		if "spill_reference_mismatch" in (manifest.get("invariant_errors") or []):
			findings.append(
				Finding(
					rule_id="cold_reference",
					rule_version=RULESET_VERSION,
					phenomenon="投影内 'full output:' 引用数与 'output truncated' 标记数不一致",
					boundary="wsc_fold",
					component="输出预算 / 折叠",
					status=SUSPECTED_CAUSE,
					evidence=[
						EvidenceRef(
							source="projection",
							locator=_s(manifest.get("locator")),
							ref_id=_s(manifest.get("projection_id")),
							detail="spill_reference_mismatch",
						)
					],
					impact="存在被截断却没留句柄、或留了句柄却没截断标记的消息。",
					coverage_gap="按字符串计数，措辞改动会让该规则失效。",
					allowed_conclusion="可疑信号，需人工展开原始投影确认。",
				)
			)
	return findings


# ---------- R4 冻结前缀稳定性 ----------


def check_frozen_head(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	chain = (run.working.get("compact_checkpoint") or {}).get("window_chain") or []
	prev: dict[str, Any] | None = None
	for entry in chain:
		if not isinstance(entry, dict):
			continue
		if prev is not None:
			same_interval = int(entry.get("cursor") or 0) == int(prev.get("cursor") or 0) and int(
				entry.get("frozen_until") or 0
			) == int(prev.get("frozen_until") or 0)
			if same_interval and _s(entry.get("summary_fp")) != _s(prev.get("summary_fp")):
				findings.append(
					Finding(
						rule_id="frozen_head",
						rule_version=RULESET_VERSION,
						phenomenon="同一折叠区间内冻结摘要指纹发生变化",
						boundary="wsc_fold",
						component="前缀冻结不变量",
						status=CONFIRMED_FAULT,
						evidence=[
							EvidenceRef(
								source="working",
								locator=_s(run.working.get("locator")),
								ref_id="compact_checkpoint.window_chain",
								detail=f"cursor={entry.get('cursor')} fp {prev.get('summary_fp')}→{entry.get('summary_fp')}",
							)
						],
						impact="两次折叠之间前缀必须逐字不变；变化会让缓存命中作废并使对比实验失配。",
						coverage_gap="window_chain 只记折叠边界，不记每次发射的头内容。",
						allowed_conclusion="可确认前缀稳定性不变量失败。",
					)
				)
		prev = entry
	# 折叠账本里没有合法折叠事件却出现 projection_id 变化 ⇒ 头意外变化。
	#
	# 前提必须能证明才行：fold_events 按会话写入、不带轮次身份（见
	# usage/ledger.py::record_fold_event），所以「本轮没拿到折叠行」既可能是
	# 真没折叠、也可能是折叠没落账 / 账本窗口没覆盖 —— 两者在账面上同形。
	proj_ids: list[str] = []
	for event in run.events_for_turn():
		if event.kind.startswith("model.") and event.projection_id:
			if not proj_ids or proj_ids[-1] != event.projection_id:
				proj_ids.append(event.projection_id)
	if len(proj_ids) <= 1:
		return findings
	fold_window = run.window("fold_events")
	ledger_covered = bool(fold_window and fold_window.complete and run.fold_rows)
	fold_locator = source_locator(run, "fold_events")
	if run.fold_rows:
		fold_refs = [
			EvidenceRef(
				source="usage",
				locator=_s(fold.get("locator")) or fold_locator,
				ref_id=f"L{_s(fold.get('line_no'))}",
				detail=f"fold={_s(fold.get('fold'))} reason={_s(fold.get('reason'))}",
			)
			for fold in run.fold_rows[:5]
		]
	elif fold_window is not None:
		fold_refs = [
			EvidenceRef(
				source="usage",
				locator=fold_locator,
				ref_id="",
				detail="fold_events 对本会话没有记录行" if not fold_window.rows_matched else "fold_events 窗口已截断",
			)
		]
	else:
		# 拿不到折叠账本窗口就不给定位符：绝不借别的来源的路径来填。
		fold_refs = [EvidenceRef(source="usage", locator="", ref_id="", detail="无 fold_events 采集窗口：折叠账本位置未记录")]
	if ledger_covered:
		findings.append(
			Finding(
				rule_id="frozen_head",
				rule_version=RULESET_VERSION,
				phenomenon=f"折叠账本完整且有 {len(run.fold_rows)} 条记录，本轮却出现 {len(proj_ids)} 个不同投影而无对应折叠事件",
				boundary="wsc_fold",
				component="前缀冻结不变量",
				status=SUSPECTED_CAUSE,
				evidence=fold_refs,
				impact=f"投影序列：{', '.join(p[:10] for p in proj_ids[:6])}",
				coverage_gap="fold_events 按会话写入、不带轮次身份，与本轮投影的先后关系只能按时间近似。",
				allowed_conclusion="可疑：账本在场且完整，却没有解释这些投影变化的折叠事件。",
			)
		)
		return findings
	if fold_window is None:
		gap_detail = "没有 fold_events 采集窗口：折叠账本位置未记录"
	elif not fold_window.present:
		gap_detail = "折叠账本文件不存在"
	elif fold_window.complete:
		gap_detail = "本会话在折叠账本里没有一行记录"
	else:
		gap_detail = f"折叠账本窗口没读完（{fold_window.note or '尾窗截断'}）"
	findings.append(
		Finding(
			rule_id="frozen_head",
			rule_version=RULESET_VERSION,
			phenomenon=f"本轮出现 {len(proj_ids)} 个不同投影，折叠账本无法核对（{gap_detail}）",
			boundary="wsc_fold",
			component="前缀冻结不变量",
			status=UNKNOWN,
			evidence=fold_refs,
			impact=f"投影序列：{', '.join(p[:10] for p in proj_ids[:6])}",
			coverage_gap=(
				"折叠账本按会话写入、行内不带轮次身份，所以空的折叠集合证明不了「没发生过折叠」，"
				"也证明不了「发生过」：这一级没有可核对的记录。"
			),
			allowed_conclusion="只能说折叠账本不足以判断这些投影变化是否合法，不能判前缀冻结失败，也不能判它正常。",
		)
	)
	return findings


# ---------- R5 Provider / 流解析失败 ----------


def check_provider_stream(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	for mr in turn_scoped(run.model_requests, run.turn_id):
		for att in mr.attempts:
			status = _s(att.get("status"))
			kind = _s(att.get("kind"))
			if kind != "llm.failure" and status not in _FAILED_MODEL_STATUSES:
				continue
			http = att.get("http_status")
			evidence = [
				EvidenceRef(source="audit", locator=_loc(run), ref_id=f"L{_s(att.get('line_no'))}", detail=kind or status)
			]
			if kind == "llm.failure":
				phen = f"模型请求失败（attempt={att.get('attempt')}，status={_s(http)}，code={_s(att.get('error_code'))}）"
			else:
				phen = f"模型尝试以 status={status} 结束（attempt={att.get('attempt')}）"
			component = "模型适配器 / 传输"
			gap = "厂商内部处理输入不可见；只能定位到适配器提交边界。"
			allowed = "可确认请求失败发生在厂商返回或传输或解析边界。"
			if _s(http) == "429" or status == "retry":
				allowed = "限流/重试是传输层结果，不能据此判定提示词错误。"
			findings.append(
				Finding(
					rule_id="provider_stream_failure",
					rule_version=RULESET_VERSION,
					phenomenon=phen,
					boundary="model_request",
					component=component,
					status=CONFIRMED_FAULT,
					evidence=evidence,
					impact=f"逻辑调用 {mr.model_request_id} 的第 {att.get('attempt')} 次尝试未产出正常结果。",
					coverage_gap=gap,
					allowed_conclusion=allowed,
				)
			)
	return findings


# ---------- R6 权限等待 / 拒绝 ----------


def check_permission_block(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	by_approval: dict[str, list[dict[str, Any]]] = {}
	for row in turn_scoped(run.permissions, run.turn_id):
		by_approval.setdefault(_s(row.get("request_id")), []).append(row)
	scoped_kinds = {e.kind for e in run.events_for_turn()}
	for approval_id, rows in by_approval.items():
		rows.sort(key=lambda r: float(r.get("ts") or 0))
		pending = [r for r in rows if str(r.get("kind", "")).startswith("permission.pending")]
		resolved = [r for r in rows if str(r.get("kind", "")).startswith(("permission.resolved", "permission.denied"))]
		if not pending:
			continue
		if not resolved:
			findings.append(
				Finding(
					rule_id="permission_block",
					rule_version=RULESET_VERSION,
					phenomenon=f"权限请求 {approval_id} 有 ASK、无结束记录",
					boundary="tool_permission",
					component="权限协调器",
					status=UNKNOWN,
					evidence=[
						EvidenceRef(source="audit", locator=_loc(run), ref_id=f"L{_s(pending[0].get('line_no'))}", detail="permission.pending")
					],
					impact="本轮可能停在等待用户，而不是卡死。",
					coverage_gap="pending 存储是纯内存进程状态，服务重启后无法判断当时是否仍在等待。",
					allowed_conclusion="等待与中断两种可能都未被排除。",
				)
			)
			continue
		last = resolved[-1]
		outcome = permission_outcome(last)
		if outcome in _BLOCKED_OUTCOMES:
			findings.append(
				Finding(
					rule_id="permission_block",
					rule_version=RULESET_VERSION,
					phenomenon=f"工具 {_s(pending[0].get('tool_name'))} 被权限层挡住（结果={outcome}，规则={_s(pending[0].get('matched_rule'))}）",
					boundary="tool_permission",
					component="权限执行层（DENY / 超时）",
					status=CONFIRMED_FAULT,
					evidence=[
						EvidenceRef(source="audit", locator=_loc(run), ref_id=f"L{_s(r.get('line_no'))}", detail=str(r.get("kind")))
						for r in rows
					],
					impact="该工具的调用未执行，模型看到的是执行层的拒绝结果。",
					coverage_gap="预期内的 DENY 与意外 DENY 在账面上同形；本规则不区分，需人工核对规则意图。",
					allowed_conclusion="可确认执行被哪条实际权限结果阻断；不得把预期拒绝计成产品故障。",
				)
			)
		elif outcome == OUTCOME_UNRECORDED:
			findings.append(
				Finding(
					rule_id="permission_block",
					rule_version=RULESET_VERSION,
					phenomenon=f"权限请求 {approval_id} 的结束行既无 approved 也无 outcome / permission_action：审批结果未记录",
					boundary="tool_permission",
					component="权限协调器（结果落账）",
					status=UNKNOWN,
					evidence=[
						EvidenceRef(source="audit", locator=_loc(run), ref_id=f"L{_s(r.get('line_no'))}", detail=str(r.get("kind")))
						for r in rows
					],
					impact="这一行说不上放行还是拦下：把「没记结果」读成「已通过」或「已拒绝」都会造出假结论。",
					coverage_gap="permission.resolved 的三个结果字段（approved / outcome / permission_action）任缺其一就无法核对；旧审计不补写。",
					allowed_conclusion="只能报审批结果未记录，不能报这一枪通过或失败。",
				)
			)
	own_permissions = turn_scoped(run.permissions, run.turn_id)
	if own_permissions and not any(
		_s(r.get("tool_use_id"))
		or _s(r.get("model_request_id"))
		# 只读门与策略 DENY 写的 permission.denied 不落 tool_use_id，但 request_id 就是
		# tool_use id（见 identity.normalize_event 与 tools/tool_registry.py 的 DENY 分支）。
		or (_s(r.get("kind")).startswith("permission.denied") and _s(r.get("request_id")))
		for r in own_permissions
	):
		findings.append(
			Finding(
				rule_id="permission_block",
				rule_version=RULESET_VERSION,
				phenomenon="权限记录不带 tool_use_id / model_request_id（旧审计格式）",
				boundary="tool_permission",
				component="审计关联字段",
				status=UNKNOWN,
				evidence=[
					EvidenceRef(source="audit", locator=_loc(run), ref_id=f"L{_s(r.get('line_no'))}", detail="缺关联字段")
					for r in own_permissions[:10]
				],
				impact="审批只能按时间顺序与工具调用近似对应。",
				coverage_gap="旧记录无法补出关联字段；补口只对新事件生效。",
				allowed_conclusion="不得把近似对应写成精确关联。",
			)
		)
	_ = scoped_kinds
	return findings


# ---------- R7 工具 / 进程失败 ----------


def check_tool_failure(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	failed = [t for t in turn_scoped(run.tool_calls, run.turn_id) if t.finished and t.is_error]
	if not failed:
		return findings
	grouped: dict[tuple[str, str], list[Any]] = {}
	for tool in failed:
		grouped.setdefault((tool.tool_name, tool.error_kind), []).append(tool)
	for (name, error_kind), items in sorted(grouped.items()):
		findings.append(
			Finding(
				rule_id="tool_failure",
				rule_version=RULESET_VERSION,
				phenomenon=f"工具 {name} 返回错误（error_kind={error_kind or '未记录'}，共 {len(items)} 次）",
				boundary="tool_permission",
				component=f"工具执行：{name}",
				status=CONFIRMED_FAULT,
				evidence=[
					EvidenceRef(
						source="audit",
						locator=_loc(run),
						ref_id=f"L{_s((t.finished or {}).get('line_no'))}",
						detail=f"tool.finished is_error=true action_id={_s(t.action_id)}",
					)
					for t in items
				][:20],
				impact="失败步骤已定位到工具与 action_id；结果正文按需在 transcript 里回读。",
				coverage_gap="审计不含退出码与 stderr 正文；「测试失败」与「测试无法运行」不在本规则区分范围内（见 verifier）。",
				allowed_conclusion="可确认工具在这一步失败。",
			)
		)
	return findings


# ---------- R8 发射链缺口 ----------


def check_wire_gap(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	hits = run.wire_drops
	if hits:
		total = sum(int(h.get("dropped") or 0) for h in hits)
		findings.append(
			Finding(
				rule_id="wire_gap",
				rule_version=RULESET_VERSION,
				phenomenon=f"最后一公里丢行账本命中本运行的工具调用（{len(hits)} 次，累计 {total} 行）",
				boundary="adapter",
				component="发射链（wire 出口护栏）",
				status=CONFIRMED_FAULT,
				evidence=[
					EvidenceRef(
						source="usage",
						locator=_s(h.get("locator")),
						ref_id=f"L{_s(h.get('line_no'))}",
						detail=f"dropped={h.get('dropped')} matched={','.join(h.get('matched_ids') or [])[:60]}",
					)
					for h in hits
				],
				impact="结果被护栏丢弃而非发送：模型看不到这条工具结果。",
				coverage_gap="账本不带 session_id，只能按 tool_use id 求交；交集为空不等于没丢过。",
				allowed_conclusion="可确认这些 tool result 未进入最终请求体。",
			)
		)
	for event in run.events_for_turn():
		if event.kind == "notice.channel" and "gap" in _kv(event, "kind_detail").lower():
			findings.append(
				Finding(
					rule_id="wire_gap",
					rule_version=RULESET_VERSION,
					phenomenon="事件流出现缺口通知",
					boundary="sse_gui",
					component="SSE 传输 / 界面",
					status=SUSPECTED_CAUSE,
					evidence=[_event_ref(run, event, "stream_gap")],
					impact="界面缺尾部而服务端可能已完成：显示边界与执行边界要分开判。",
					coverage_gap="客户端 ack 游标不持久化，跨进程无法核对。",
					allowed_conclusion="可确认传输或显示边界存在缺口；不能据此判定引擎未完成。",
				)
			)
	return findings


# ---------- R9 未完成执行 ----------


def check_incomplete_run(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	for mr in turn_scoped(run.model_requests, run.turn_id):
		starts = [a for a in mr.attempts if _s(a.get("kind")) == "model.started"]
		finishes = [a for a in mr.attempts if _s(a.get("kind")) == "model.finished"]
		if len(starts) > len(finishes):
			findings.append(
				Finding(
					rule_id="incomplete_run",
					rule_version=RULESET_VERSION,
					phenomenon=f"逻辑调用 {mr.model_request_id} 有 {len(starts)} 次开始、{len(finishes)} 次结束记录",
					boundary="model_request",
					component="模型请求边界",
					status=UNKNOWN,
					evidence=[
						EvidenceRef(source="audit", locator=_loc(run), ref_id=f"L{_s(a.get('line_no'))}", detail="model.started 无配对 finished")
						for a in starts
					],
					impact="可能是仍在流式输出、被中断、或结束记录未写。",
					coverage_gap="仅凭结束记录缺失不能证明进程已死；需与 job/进程状态联合判断。",
					allowed_conclusion="只能说记录不成对。",
				)
			)
	for job in run.jobs:
		status = _s(job.get("status"))
		if status in {"running", "stopping"}:
			findings.append(
				Finding(
					rule_id="incomplete_run",
					rule_version=RULESET_VERSION,
					phenomenon=f"后台任务 {job.get('job_id')} 状态 {status}（长任务与超时未区分）",
					boundary="background_job",
					component="后台任务注册表",
					status=UNKNOWN,
					evidence=[
						EvidenceRef(source="job", locator=_s(job.get("locator")), ref_id=_s(job.get("job_id")), detail=f"status={status}")
					],
					impact="合法长任务会命中同一状态；不能据此判死锁。",
					coverage_gap="job 注册表是纯内存、无退出码、无心跳落盘，进程重启后历史不可读。",
					allowed_conclusion="只能说明当前状态。",
				)
			)
		elif status == "failed":
			findings.append(
				Finding(
					rule_id="incomplete_run",
					rule_version=RULESET_VERSION,
					phenomenon=f"后台任务 {job.get('job_id')} 以 failed 结束：{_s(job.get('detail'))[:120]}",
					boundary="background_job",
					component="后台任务注册表",
					status=CONFIRMED_FAULT,
					evidence=[
						EvidenceRef(source="job", locator=_s(job.get("locator")), ref_id=_s(job.get("job_id")), detail="status=failed")
					],
					impact="进程侧失败已确认。",
					coverage_gap="无退出码，只有 status/detail 字符串。",
					allowed_conclusion="可确认任务失败，不可推断失败原因。",
				)
			)
	return findings


# ---------- R10 重复失败 ----------


def check_repeated_failure(run: RunEvidence) -> list[Finding]:
	window = 60
	scoped = run.events_for_turn()[-window:]
	signatures: dict[str, list[Any]] = {}
	for event in scoped:
		if event.kind != "tool.finished":
			continue
		if not bool(event.row.get("is_error")):
			continue
		arg = ""
		for key in ("file_path", "path", "pattern", "command_summary", "command", "url"):
			if event.row.get(key):
				arg = _s(event.row.get(key))
				break
		sig = f"{_kv(event, 'tool_name')}|{_kv(event, 'error_kind')}|{_sig(arg[:200])}"
		signatures.setdefault(sig, []).append(event)
	findings: list[Finding] = []
	for sig, events in signatures.items():
		if len(events) < 3:
			continue
		name, error_kind, _digest = sig.split("|", 2)
		findings.append(
			Finding(
				rule_id="repeated_failure",
				rule_version=RULESET_VERSION,
				phenomenon=f"工具 {name} 以同一 error_kind={error_kind or '未记录'} 重复失败 {len(events)} 次",
				boundary="tool_permission",
				component=f"工具执行：{name}",
				status=SUSPECTED_CAUSE,
				evidence=[_event_ref(run, e, "重复失败") for e in events][:12],
				impact="重复失败信号：同一参数与错误签名在有界窗口内反复出现。",
				coverage_gap="审计不含完整参数，签名相同不等于参数相同；窗口外的重复看不到。",
				allowed_conclusion="不得据此断言死循环，也不得自动改写模型计划。",
			)
		)
	return findings


# ---------- R11 用量账目 ----------


def check_usage_accounting(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	orphans: list[dict[str, Any]] = []
	for row in run.usage_rows:
		if not _s(row.get("attempt_key")):
			orphans.append(row)
	known_sources = {"api", "estimate"}
	missing: list[EvidenceRef] = []
	duplicated: list[EvidenceRef] = []
	bad_source: list[EvidenceRef] = []
	for mr in turn_scoped(run.model_requests, run.turn_id):
		for att in mr.attempts:
			if _s(att.get("kind")) != "model.finished":
				continue
			if _s(att.get("status")) not in {"ok", "retry", "protocol_fallback"}:
				continue
			key = f"{mr.model_request_id}#{att.get('attempt')}"
			rows = [row for row in run.usage_rows if _s(row.get("attempt_key")) == key]
			if not rows:
				missing.append(
					EvidenceRef(
						source="audit",
						locator=_loc(run),
						ref_id=f"L{_s(att.get('line_no'))}",
						detail=f"attempt {key} 无用量账",
					)
				)
				continue
			if len(rows) > 1:
				duplicated.append(
					EvidenceRef(
						source="usage",
						locator=_s(rows[0].get("locator")),
						ref_id=f"L{_s(rows[0].get('line_no'))}",
						detail=f"同一 {key} 有 {len(rows)} 笔账",
					)
				)
			for row in rows:
				if _s(row.get("cost_source")) not in known_sources:
					bad_source.append(
						EvidenceRef(
							source="usage",
							locator=_s(row.get("locator")),
							ref_id=f"L{_s(row.get('line_no'))}",
							detail=f"cost_source={_s(row.get('cost_source'))} 非已知口径",
						)
					)
	if missing:
		findings.append(
			Finding(
				rule_id="usage_accounting",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(missing)} 次模型尝试在用量账本里没有对应记录",
				boundary="model_request",
				component="用量账本（usage/ledger）",
				status=CONFIRMED_FAULT,
				evidence=missing[:20],
				impact="这些请求的费用未知：不得按 0 元计入合计，也不得释放实验预算预留。",
				coverage_gap="账本在 usage 缺失时整行不写，因此「没有行」既可能是没计费也可能是没落账。",
				allowed_conclusion="报告为费用未知/账目缺失。",
			)
		)
	if duplicated:
		findings.append(
			Finding(
				rule_id="usage_accounting",
				rule_version=RULESET_VERSION,
				phenomenon="同一 (model_request_id, attempt) 出现多笔用量账",
				boundary="model_request",
				component="用量账本（双写防御失效）",
				status=CONFIRMED_FAULT,
				evidence=duplicated,
				impact="合计费用会被重复计入。",
				coverage_gap="无法从账本判断哪一笔是真实结算。",
				allowed_conclusion="账目异常，不得用作成本结论。",
			)
		)
	if bad_source:
		findings.append(
			Finding(
				rule_id="usage_accounting",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(bad_source)} 笔用量账的 cost_source 不是已知计价口径",
				boundary="model_request",
				component="用量账本计价（api / estimate）",
				status=CONFIRMED_FAULT,
				evidence=bad_source[:20],
				impact="该笔费用的来源不可解释，不能计入可信合计。",
				coverage_gap="账本没有 unknown 口径：缺价目时按 estimate 落账，本规则无法把「估不出来」与「估错了」分开。",
				allowed_conclusion="报账目异常，不报金额。",
			)
		)
	if orphans:
		findings.append(
			Finding(
				rule_id="usage_accounting",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(orphans)} 笔用量账不带 request_id/attempt，无法关联到模型请求",
				boundary="model_request",
				component="模型适配器记账 meta 注入",
				status=UNKNOWN,
				evidence=[
					EvidenceRef(source="usage", locator=_s(r.get("locator")), ref_id=f"L{_s(r.get('line_no'))}", detail="缺 request_id")
					for r in orphans[:10]
				],
				impact="这笔钱存在，但归不到具体请求；按会话聚合正确、按请求聚合会漏。",
				coverage_gap="非流式路径与旁路调用（CLI/评测）本就不带 request_id。",
				allowed_conclusion="不得把这些账当作 0，也不得凭归属猜测分配。",
			)
		)
	return findings


# ---------- R12 验收 ----------


def check_verifier(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	pinned = [p for p in run.pins if _s(p.get("kind")) == "verifier"]
	if not pinned:
		findings.append(
			Finding(
				rule_id="verifier",
				rule_version=RULESET_VERSION,
				phenomenon="本运行没有验收记录（未固定 verifier，或测试未运行）",
				boundary="file_verifier",
				component="结果验收",
				status=UNKNOWN,
				# 没有 pin 就没有 pin 可指：留空定位符，绝不拿 working.json 的路径冒充。
				evidence=[
					EvidenceRef(
						source="pin",
						locator="",
						ref_id="",
						detail="absent：本会话的固定记录里没有 kind=verifier 的条目",
					)
				],
				impact="无法判定任务是否成功：模型说「通过」不等于已通过。",
				coverage_gap="没有固定 verifier 时，本规则只能报「未执行/未记录」，不能推断结果。",
				allowed_conclusion="验收状态未知。",
			)
		)
		return findings
	for item in pinned:
		code = item.get("exit_code")
		state = "未运行" if code is None else ("通过" if int(code) == 0 else "失败")
		findings.append(
			Finding(
				rule_id="verifier",
				rule_version=RULESET_VERSION,
				phenomenon=f"verifier {_s(item.get('name'))} 状态={state}（退出码={_s(code) if code is not None else '未记录'}）",
				boundary="file_verifier",
				component=f"结果验收：{_s(item.get('name'))}",
				status=UNKNOWN if code is None else (CONFIRMED_FAULT if int(code) != 0 else UNKNOWN),
				evidence=[
					EvidenceRef(source="pin", locator=_s(item.get("locator")), ref_id=_s(item.get("pin_id")), detail=f"verifier exit={code}")
				],
				impact="验收结果按原始记录呈现。",
				coverage_gap="退出码 0 只证明该 verifier 通过，不证明任务完成或没有越界修改。",
				allowed_conclusion="通过/失败/执行错误/未执行四态分开报，不合并成单一分数。",
			)
		)
	return findings


@dataclass
class Rule:
	rule_id: str
	check: Callable[[RunEvidence], list[Finding]]


RULES: tuple[Rule, ...] = tuple(
	Rule(rule_id, fn)
	for rule_id, fn in (
		("tool_pair_integrity", check_tool_pair_integrity),
		("instruction_drift", check_instruction_drift),
		("cold_reference", check_cold_references),
		("frozen_head", check_frozen_head),
		("provider_stream_failure", check_provider_stream),
		("permission_block", check_permission_block),
		("tool_failure", check_tool_failure),
		("wire_gap", check_wire_gap),
		("incomplete_run", check_incomplete_run),
		("repeated_failure", check_repeated_failure),
		("usage_accounting", check_usage_accounting),
		("verifier", check_verifier),
	)
)


def no_turn_records_finding(run: RunEvidence) -> Finding:
	"""「本轮无记录」：采集跑过，但这个轮子没有任何带自己身份的记录。

	它必须是 unknown 加写明缺什么，不能是一个干净通过：会话级的 transcript /
	working / usage 记录并不属于本轮，拿它们给本轮下结论就是误归因。
	"""
	window = run.window("audit")
	if window is not None:
		evidence = [
			EvidenceRef(
				source="audit",
				locator=_s(window.locator),
				ref_id="",
				detail=f"扫描 {window.rows_scanned} 行、匹配 {window.rows_matched} 行，无 turn_id={run.turn_id} 的事件",
			)
		]
	else:
		evidence = [
			EvidenceRef(source="config", locator="diagnostics/rules.py", ref_id="no_turn_records", detail="无审计采集窗口")
		]
	return Finding(
		rule_id="no_turn_records",
		rule_version=RULESET_VERSION,
		phenomenon=f"本轮无记录：采集窗口里没有一条带 turn_id={run.turn_id} 的记录",
		boundary="user_request",
		component="证据采集（轮次身份）",
		status=UNKNOWN,
		evidence=evidence,
		impact="会话级记录（transcript / working / usage）不属于本轮：本轮没有任何可核对的自身记录，规则集本轮未运行。",
		coverage_gap=(
			"无记录不等于没发生：审计与账本都按尾窗采集，窗口可能没覆盖这一轮；"
			"不带 turn_id 的旧审计行也不参与轮次归因。扩大窗口或补轮次身份前，本轮既不能判正常也不能判异常。"
		),
		allowed_conclusion="只能报本轮无记录；同会话别处的记录不得算给本轮。",
	)


def evaluate_run(run: RunEvidence) -> list[Finding]:
	"""跑完整规则集。单条规则异常不吞掉：它自己变成一条 unknown 结论。"""
	if no_turn_records(run):
		return [no_turn_records_finding(run)]
	findings: list[Finding] = []
	for rule in RULES:
		try:
			findings.extend(rule.check(run))
		except Exception as exc:  # noqa: BLE001 — 规则故障必须可见
			findings.append(
				Finding(
					rule_id=rule.rule_id,
					rule_version=RULESET_VERSION,
					phenomenon=f"规则执行失败：{type(exc).__name__}",
					boundary="instruction_context",
					component="诊断规则集",
					status=UNKNOWN,
					evidence=[EvidenceRef(source="config", locator="diagnostics/rules.py", ref_id=rule.rule_id, detail=str(exc)[:200])],
					impact="该规则本轮未产生结论。",
					coverage_gap="规则自身故障，覆盖范围未知。",
					allowed_conclusion="不得把「没发现异常」读成「没有异常」。",
				)
			)
	findings.sort(key=lambda f: (f.status != CONFIRMED_FAULT, f.status != SUSPECTED_CAUSE, f.rule_id))
	return findings


def earliest_anomaly(findings: list[Finding]) -> Finding | None:
	for item in findings:
		if item.status == CONFIRMED_FAULT:
			return item
	return None


__all__ = [
	"OUTCOME_ALLOWED",
	"OUTCOME_DENIED",
	"OUTCOME_UNRECORDED",
	"RULESET_VERSION",
	"RULES",
	"check_cold_references",
	"check_frozen_head",
	"check_incomplete_run",
	"check_instruction_drift",
	"check_permission_block",
	"check_provider_stream",
	"check_repeated_failure",
	"check_tool_failure",
	"check_tool_pair_integrity",
	"check_usage_accounting",
	"check_verifier",
	"check_wire_gap",
	"collection_attempted",
	"earliest_anomaly",
	"evaluate_run",
	"no_turn_records",
	"no_turn_records_finding",
	"permission_blocked",
	"permission_outcome",
	"permission_outcome_unrecorded",
	"row_belongs_to_run",
	"source_locator",
	"turn_has_records",
	"turn_scoped",
]
