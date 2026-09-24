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
	started_only = [t for t in run.tool_calls if t.started and not t.finished]
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


def check_instruction_drift(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	hashes: dict[str, list[str]] = {}
	for event in run.events_for_turn():
		if not event.kind.startswith(("model.", "tool.")):
			continue
		for field in ("tool_schema_hash", "tool_surface_id", "permission_snapshot_id", "runtime_profile_id"):
			value = _kv(event, field)
			if value:
				hashes.setdefault(field, []).append(value)
	for field, values in hashes.items():
		uniq = sorted(set(values))
		if len(uniq) <= 1:
			continue
		findings.append(
			Finding(
				rule_id="instruction_drift",
				rule_version=RULESET_VERSION,
				phenomenon=f"同一轮内 {field} 出现 {len(uniq)} 个不同取值",
				boundary="instruction_context",
				component=f"上下文组装（{field}）",
				status=CONFIRMED_FAULT if field == "permission_snapshot_id" else SUSPECTED_CAUSE,
				evidence=[
					_event_ref(run, e, f"{field}={_kv(e, field)}")
					for e in run.events_for_turn()
					if _kv(e, field)
				][:20],
				impact=f"变化值：{', '.join(v[:12] for v in uniq)}（只报事实，不评价哪一版更好）。",
				coverage_gap="轮内可见；跨轮的指令正文变化不在本规则范围，由 A0 静态差异负责。",
				allowed_conclusion="可确认哪一段标识变了；不能据此判定变好或变坏。",
			)
		)
	return findings


# ---------- R3 冷引用 / 可回读性 ----------


def check_cold_references(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	broken = [
		row
		for row in run.transcript_rows
		if row.get("body_state") in {"missing_blob", "resolve_failed", "absent"} and row.get("content_ref")
	]
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
	# 折叠账本里没有合法折叠事件却出现 projection_id 变化 ⇒ 头意外变化
	if run.fold_rows:
		return findings
	proj_ids = []
	for event in run.events_for_turn():
		if event.kind.startswith("model.") and event.projection_id:
			if not proj_ids or proj_ids[-1] != event.projection_id:
				proj_ids.append(event.projection_id)
	if len(proj_ids) > 1:
		findings.append(
			Finding(
				rule_id="frozen_head",
				rule_version=RULESET_VERSION,
				phenomenon=f"本运行无折叠账本，却出现 {len(proj_ids)} 个不同投影",
				boundary="wsc_fold",
				component="前缀冻结不变量",
				status=SUSPECTED_CAUSE,
				evidence=[
					EvidenceRef(
						source="usage",
						locator=_s((run.windows[0].locator if run.windows else "")),
						ref_id="fold_events",
						detail="fold 账本为空",
					)
				],
				impact=f"投影序列：{', '.join(p[:10] for p in proj_ids[:6])}",
				coverage_gap="fold_events 按会话写入、不带轮次身份，跨轮混在一起时会误判。",
				allowed_conclusion="可疑：需核对是否存在未落账的折叠。",
			)
		)
	return findings


# ---------- R5 Provider / 流解析失败 ----------


def check_provider_stream(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	for mr in run.model_requests:
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
	for row in run.permissions:
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
		outcome = _s(last.get("outcome")) or ("denied" if not last.get("approved") else "allowed")
		if outcome in {"timeout", "denied"} or last.get("approved") is False:
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
	if run.permissions and not any(_s(r.get("tool_use_id")) for r in run.permissions):
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
					for r in run.permissions[:10]
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
	failed = [t for t in run.tool_calls if t.finished and t.is_error]
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
	for mr in run.model_requests:
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
	for mr in run.model_requests:
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
				evidence=[
					EvidenceRef(source="pin", locator=_s(run.working.get("locator")), ref_id="", detail="无 verifier 固定记录")
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


def evaluate_run(run: RunEvidence) -> list[Finding]:
	"""跑完整规则集。单条规则异常不吞掉：它自己变成一条 unknown 结论。"""
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
	"earliest_anomaly",
	"evaluate_run",
]
