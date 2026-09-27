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
import time
from dataclasses import dataclass
from typing import Any, Callable

from diagnostics.collect import RunEvidence
from diagnostics.identity import (
	CONFIRMED_FAULT,
	SUSPECTED_CAUSE,
	UNKNOWN,
	EvidenceRef,
	Finding,
	_f,
	_s,
	request_key,
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
#: 「没人答复 / 被中止」这两类结果由执行层自己写下，属设计内的 fail-closed：
#: 它们说明这一枪为什么没执行，但不构成产品故障（判据见 check_permission_block 的注释）。
_UNANSWERED_OUTCOMES = {"timeout", "aborted"}

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


def scope_word(run: RunEvidence) -> str:
	"""运行范围的中文说法：会话级报告（``turn_id=""``）不许说「本轮」。

	`/report` 端点接受空 turn_id（server/routers/diagnostics.py::post_report），那时每条规则
	读的都是整个会话的行 —— 说「本轮」就是把会话级的行数算给一轮。check_tool_routing 的措辞
	注释早就为这一条改过口，但只改了它自己那一处。
	"""
	return "本轮" if _s(run.turn_id) else "本会话"


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


def _turn_projection_ids(run: RunEvidence) -> set[str]:
	"""本轮自己提交过哪些投影：working 只存"本会话最后一份"manifest，
	没有这一步归属，会话级记录就会被同会话的每一个轮次各自报一遍
	（2026-09-25 实测：29 条投影结论里 22 条属于这种情况）。
	"""
	return {_s(event.row.get("projection_id")) for event in run.events_for_turn() if _s(event.row.get("projection_id"))}


# ---------- R1 工具调用 / 结果不成对 ----------


def check_tool_pair_integrity(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	refs: list[EvidenceRef] = []
	turn_projection_ids = _turn_projection_ids(run)
	for manifest in run.projections:
		if _s(manifest.get("projection_id")) not in turn_projection_ids:
			# 这份 manifest 不是本轮提交的那一份：它的坏形状可能是别轮留下的，
			# 而这条结论一旦下达就是"已确认 + 引擎定责"（fault_split._ENGINE_RULES）。
			continue
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
				allowed_conclusion=f"可确认某个边界上配对被破坏；不足以解释{scope_word(run)}任务失败的全部原因。",
			)
		)

	# 生产者的第四类旗标说的是 **canonical 层**（持久化的工作记忆），不是发出去的那份投影：
	# 历史里存着没有对应 tool_result 的 tool_use。它不证明这次请求形状坏 —— 折叠可以把
	# 调用与结果一起丢掉，那时 projected 是干净的 —— 所以只能停在未定。但一声不吭就是把
	# 已经拿到的事实丢掉：这条旗标由 engine/projection_manifest.py 写下，本规则集此前
	# 没有任何一条读它（2026-09-25 对照生产者与读取方清单发现）。
	for manifest in run.projections:
		if _s(manifest.get("projection_id")) not in turn_projection_ids:
			continue
		hits = [_s(e) for e in (manifest.get("invariant_errors") or []) if _s(e).startswith("canonical_unpaired_tool_calls")]
		if not hits:
			continue
		findings.append(
			Finding(
				rule_id="tool_pair_integrity",
				rule_version=RULESET_VERSION,
				phenomenon="持久化的工作记忆里存着没有配对结果的 tool_use（查的是完整历史，不是发出去的那份投影）",
				boundary="wsc_fold",
				component="上下文组装（projection manifest 的 canonical 检查）",
				status=UNKNOWN,
				evidence=[
					EvidenceRef(
						source="projection",
						locator=_s(manifest.get("locator")),
						ref_id=_s(manifest.get("projection_id")),
						detail=hit,
					)
					for hit in hits
				],
				impact="发出去的那份投影不一定带着这个洞：折叠可以把调用与结果一起丢掉。",
				coverage_gap=(
					"manifest 只保留最后一份，且旗标本身说不上成因 —— 中止收尾没写结果、"
					"还是折叠单独丢掉了结果，都要另找证据。"
				),
				allowed_conclusion="只能说工作记忆里有不成对的 tool_use；不能据此判定请求形状坏了。",
			)
		)

	# 审计侧：有 started 无 finished 的工具调用。
	started_only = [t for t in turn_scoped(run.tool_calls, run.turn_id) if t.started and not t.finished]
	orphaned = [t for t in started_only if not _activity_after(_turn_comparable_events(run), t)]
	if orphaned:
		# 没有更晚的活动可参照，无法区分"还在跑"和"没了结束记录"。
		findings.append(
			Finding(
				rule_id="tool_pair_integrity",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(orphaned)} 个工具调用有开始记录、无结束记录，且{scope_word(run)}记录里该行之后没有别的行可参照",
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
					for t in orphaned
				],
				impact="无法判断工具仍在执行还是结束记录缺失。",
				coverage_gap=(
					"参照范围只有本运行读到的行：同一会话更晚轮次的行不在里面，跨轮补记的结束行看不到；"
					"结束记录缺失本身也不证明进程已死，正常长任务会命中同一形状。"
				),
				allowed_conclusion="只能说记录不完整，不能说执行失败。",
			)
		)
	return findings


def _turn_comparable_events(run: RunEvidence) -> list[Any]:
	"""与 ``turn_scoped`` 同口径的行集：本轮的行 + 不带轮次身份的行。

	用 ``events_for_turn()`` 会比选调用时窄一档（它丢掉不带 turn_id 的旧行），
	那会让"其后无更晚活动"在一堆未归属记录面前被谎报成成立。
	"""
	if not run.turn_id:
		return list(run.events)
	return [e for e in run.events if not e.turn_id or e.turn_id == run.turn_id]


def _activity_after(events: list[Any], tool: Any) -> bool:
	"""这条 started 之后还有没有别的审计行。

	旧写法拿整轮有没有 ``tool.finished`` 当判据（且那个与运算让 ``model.*``
	两项从不参与判决），于是两种形状都会走偏：同一轮里前一个调用干净结束、
	后一个调用只开了头且其后什么都没有——正是要报的那件事被整体吞掉；
	反过来整轮没有 tool.finished 但孤儿行后面还有记录时，"其后无更晚活动"
	是一句假话。判据只能按行号逐条问。
	"""
	line = _s((tool.started or {}).get("line_no"))
	if not line.isdigit():
		return True  # 不知位置就不能宣称"其后无更晚活动"
	start = int(line)
	return any(e.line_no > start for e in events)


# ---------- R2 指令 / 配置漂移 ----------

# 参与"轮内标识漂移"比较的字段。
#
# ``permission_snapshot_id`` 被排除，且不是因为它偶尔合法变化：它是**写入那一瞬间**
# 的 ambient 权限身份 —— permissions/trace.py::permission_snapshot 把 mode / revision /
# cwd / runtime_profile_id 一起取哈希，而 revision 由 begin_turn 与每次 set() 递增，
# 任何一条 model.* 行都可能在流式开始与结束之间被别的声道改动过的 ambient 值打标。
# 2026-09-25 直接读原始审计行测最近 40 轮：32/40 轮的 model.* 行带着 ≥2 个快照 id，
# 其中 27/40 轮是**同一个 model_request_id 的两次写入就用了不同 id**（最极端一轮
# 有 29 个逻辑调用出现这种分裂），而同轮的逻辑调用数远大于快照 id 数（中位数 8.5 枪
# 对 3 个 id）⇒ 它不是"这一轮的指令上下文变了"的量具。旧版本据此每条都产出一项，
# 把需要人工判断的"未定"桶占满；事实与理由改由采集层说
# （collect._note_identity_granularity 的 instruction_context/not_comparable）。
# 要让这个字段可比，需要的是把请求级身份钉在请求行上（引擎侧补口，另立待批）。
_DRIFT_FIELDS = ("tool_schema_hash", "tool_surface_id", "runtime_profile_id")


def check_instruction_drift(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	scoped = [e for e in run.events_for_turn() if e.kind.startswith(("model.", "tool."))]
	hashes: dict[str, list[str]] = {}
	for event in scoped:
		for field in _DRIFT_FIELDS:
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
				phenomenon=f"{scope_word(run)}里 {field} 出现 {len(uniq)} 个不同取值",
				boundary="instruction_context",
				component=f"上下文组装（{field}）",
				status=SUSPECTED_CAUSE,
				evidence=[
					_event_ref(run, e, f"{field}={_kv(e, field)}")
					for e in scoped
					if _kv(e, field)
				][:20],
				impact=f"变化值：{', '.join(v[:12] for v in uniq)}（只报事实，不评价哪一版更好）。",
				coverage_gap="轮内可见；跨轮的指令正文变化不在本规则范围，由 A0 静态差异负责。",
				allowed_conclusion="可确认哪一段标识变了；不能据此判定变好或变坏。",
			)
		)
	return findings


# ---------- R3 冷引用 / 可回读性 ----------


def _spill_retention_days() -> float | None:
	"""spill 句柄的例行保留期（tools/spill.py 每次落盘顺带删掉更早的）。

	读引擎的权威常量与环境覆盖，不在诊断侧抄一个数字：保留期一改，这条判据必须跟着改。
	读不出来返回 None —— 宁可不判过期，也不把"拿不到常数"说成"没过期"。
	"""
	try:
		import os

		from tools.spill import DEFAULT_RETENTION_DAYS, ENV_RETENTION_DAYS

		raw = _s(os.environ.get(ENV_RETENTION_DAYS, ""))
		days = float(raw or DEFAULT_RETENTION_DAYS)
	except Exception:  # noqa: BLE001 — 引擎常量读不到时退回"无从判断"
		return None
	if days <= 0:
		# 保留期关掉＝引擎永不做例行清理，读不到的文件没有任何"到期"可归。
		return None
	return days


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
	expired_handles: list[EvidenceRef] = []
	retention_days = _spill_retention_days()
	for spill in [e for e in run.events_for_turn() if e.kind == "tool.spill"]:
		path = _kv(spill, "path")
		if not path:
			continue
		from pathlib import Path

		if Path(path).is_file():
			continue
		ref = spill.ref(_loc(run), f"spill 文件缺失: {path}")
		# 引擎每次落 spill 都会删掉超过保留期的旧文件（tools/spill.py::_prune_old）。
		# 越过那个时刻的句柄读不到是例行清理的形状，不能记成"冷层原文丢了"的已确认故障。
		handle_ts = _f(spill.row.get("ts"))
		expiry_cut = None if retention_days is None else time.time() - retention_days * 86400.0
		if handle_ts is not None and expiry_cut is not None and handle_ts < expiry_cut:
			expired_handles.append(ref)
		else:
			refs.append(ref)
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
				phenomenon=f"本会话窗口里有 {len(foreign)} 处不可回读的冷层引用，但都没有可归属的轮次身份",
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
				impact="这些引用锚不到这次运行里的任何一次工具调用：既归不到具体轮次，也不能据此说查过没问题。",
				coverage_gap="transcript 行不带轮次身份，采集器只按本运行的 tool_use_id 锚定；锚不上的行无法归轮。",
				allowed_conclusion="只能说这些引用无法归属到这次运行的某一次工具调用；不得据此判定它的恢复性没问题。",
			)
		)
	if expired_handles:
		findings.append(
			Finding(
				rule_id="cold_reference",
				rule_version=RULESET_VERSION,
				phenomenon=(
					f"{len(expired_handles)} 处 spill 句柄现在读不到，落盘时刻已越过 tools/spill.py "
					f"的 {retention_days:g} 天保留期"
				),
				boundary="wsc_fold",
				component="可恢复性（输出预算 spill 的保留期）",
				# 引擎每次落 spill 都顺带删掉超过保留期的旧文件，所以"到期"与"丢了"
				# 在这里是同一个观察结果。保留期是设计，不是恢复性故障。
				status=UNKNOWN,
				evidence=expired_handles,
				impact="句柄到期后原文不再可回读：跨保留期的取证只能靠 transcript 里的预览段。",
				coverage_gap=(
					"删除按文件 mtime、这里按审计行的落盘时刻估，两者差一次保存延迟；"
					"到期只说明句柄该被例行清理，不证明它一定没被别的机制提前删掉。"
				),
				allowed_conclusion="可确认现在回读不到；不得据此判定引擎弄丢了冷层原文。",
			)
		)
	turn_projection_ids = _turn_projection_ids(run)
	for manifest in run.projections:
		errors = manifest.get("invariant_errors") or []
		# working 只存"本会话最后一份"manifest，它多半不是本轮那一份。归不到本轮的
		# 投影不得冒充本轮结论：2026-09-25 分层普查 57 轮里，29 条投影结论只有 7 条
		# 的 projection_id 真出现在本轮的模型行里，其余 22 条是同一条会话级记录被
		# 别轮复用（最多一份 manifest 被 22 个轮次各自报一遍）。
		if _s(manifest.get("projection_id")) not in turn_projection_ids:
			continue
		handle_count = manifest.get("spills")
		count_text = f"该投影带 {handle_count} 个可回读句柄" if isinstance(handle_count, int) else ""
		if "truncation_without_handle" in errors:
			# 精确判据（engine/projection_manifest.py::_unhandled_truncations）：
			# 有 "[output truncated: …]" 声明却拿不到同一处的 full output: 句柄。
			findings.append(
				Finding(
					rule_id="cold_reference",
					rule_version=RULESET_VERSION,
					phenomenon=f"投影里有预算截断声明没有给出可回读句柄（{count_text}）",
					boundary="wsc_fold",
					component="输出预算 / 折叠",
					status=SUSPECTED_CAUSE,
					evidence=[
						EvidenceRef(
							source="projection",
							locator=_s(manifest.get("locator")),
							ref_id=_s(manifest.get("projection_id")),
							detail="truncation_without_handle",
						)
					],
					impact="被截断的那段原文没有回读入口：模型看不到、也读不回来。",
					coverage_gap=(
						"旗标只说这份投影里有这样的声明，不说是哪一处；要定位需要该次投影的正文，"
						"而 manifest 只保留最后一份。"
					),
					allowed_conclusion=f"可疑：{scope_word(run)}确实有截断声明拿不到回读句柄；不能据此判定是哪个工具的输出。",
				)
			)
		elif "spill_reference_mismatch" in errors:
			# 旧旗标来自改版前的判据（两个裸子串的整串计数比较）：四个产生方的形状本就
			# 不同，健康运行也会为真（真实数据 26/40 轮）。现在还能看见它，只可能是
			# 判据改版前留下的 manifest ⇒ 登记为读不出，不当可疑原因。
			findings.append(
				Finding(
					rule_id="cold_reference",
					rule_version=RULESET_VERSION,
					phenomenon=f"这份投影带的是改版前的 spill 旗标（按字面量计数比较），{scope_word(run)}读不出回读性",
					boundary="wsc_fold",
					component="输出预算 / 折叠",
					status=UNKNOWN,
					evidence=[
						EvidenceRef(
							source="projection",
							locator=_s(manifest.get("locator")),
							ref_id=_s(manifest.get("projection_id")),
							detail="spill_reference_mismatch（旧判据留下）",
						)
					],
					impact=f"这条不构成{scope_word(run)}的任何结论：判据已改成按标记作用域配对（engine/projection_manifest.py）。",
					coverage_gap="manifest 只保留最后一份，而这份是改版前写的；下一次投影重建后才会带新旗标。",
					allowed_conclusion="只能说这份投影带的是改版前的旗标，不能据此判定折叠或输出预算出了故障。",
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
						phenomenon="同一折叠区间内冻结摘要长度发生变化",
						boundary="wsc_fold",
						component="前缀冻结不变量",
						status=CONFIRMED_FAULT,
						evidence=[
							EvidenceRef(
								source="working",
								locator=_s(run.working.get("locator")),
								ref_id="compact_checkpoint.window_chain",
								detail=(
									f"cursor={entry.get('cursor')} "
									f"摘要长度 {prev.get('summary_fp')}→{entry.get('summary_fp')}"
								),
							)
						],
						impact="两次折叠之间前缀必须逐字不变；变化会让缓存命中作废并使对比实验失配。",
						coverage_gap=(
							"判据比的是摘要长度（生产者在 summary_fp 里存的是 len(summary_text)），"
							"等长而不同文的改动这条看不见；window_chain 也只记折叠边界，"
							"不记每次发射的头内容。"
						),
						allowed_conclusion="可确认前缀稳定性不变量失败。",
					)
				)
		prev = entry
	# 冻结头不变量的可核对形式只有一个：同一个逻辑调用的多次尝试必须逐字同一。
	#
	# 这里刻意不看"本轮出现了几个不同 projection_id"。投影是对整份消息列表取哈希
	# （engine/projection_manifest.py:98），每发一枪都允许合法变化：真实数据 40 轮里
	# 该前提命中 28 轮，而这 28 轮的不同投影数**全都 ≤ 本枪数** ⇒ 前提只等价于
	# "这一轮不止一枪"，不携带任何异常信息（旧版本把它写成 27/40 轮的"未定"和
	# 1/40 轮的"疑似"，正好淹掉真正说不清的那几条）。
	# 折叠账本零记录这一事实改由采集层说（collect._collect_folds 的 wsc_fold/no_records）。
	series_by_request: dict[str, list[str]] = {}
	line_by_request: dict[str, int] = {}
	for event in run.events_for_turn():
		if not event.kind.startswith("model.") or not event.model_request_id:
			continue
		pid = _s(event.projection_id)
		if not pid:
			continue
		series = series_by_request.setdefault(event.model_request_id, [])
		if not series or series[-1] != pid:
			series.append(pid)
		line_by_request.setdefault(event.model_request_id, int(event.line_no or 0))
	shifted = sorted(
		(rid for rid, series in series_by_request.items() if len(series) > 1),
		key=lambda rid: (line_by_request.get(rid) or 0, rid),
	)
	if not shifted:
		return findings
	evidence: list[EvidenceRef] = []
	for rid in shifted[:10]:
		evidence.append(
			EvidenceRef(
				source="audit",
				locator=_loc(run),
				ref_id=f"L{line_by_request.get(rid) or ''}",
				detail=f"model_request_id={rid} 投影 {'→'.join(p[:10] for p in series_by_request[rid][:4])}",
			)
		)
	first = shifted[0]
	if len(shifted) > 1:
		phen = f"{len(shifted)} 个逻辑调用在重试之间提交了不同投影（首个 {first[:12]}）"
	else:
		phen = f"逻辑调用 {first[:12]} 在重试之间提交了不同投影"
	findings.append(
		Finding(
			rule_id="frozen_head",
			rule_version=RULESET_VERSION,
			phenomenon=phen,
			boundary="wsc_fold",
			component="前缀冻结不变量",
			status=SUSPECTED_CAUSE,
			evidence=evidence,
			impact="同一个逻辑调用的两次尝试换了字节面：这两枪之间前缀不逐字相同，缓存命中作废，对比实验也不同底。",
			coverage_gap=(
				"审计只记投影标识，不记投影正文；要定位变的是哪一段，需要等价的请求体捕获（默认关闭）"
				"或两次序列化的差异。"
			),
			allowed_conclusion="可确认同一逻辑调用的两次尝试提交了不同投影；不能据此判定是哪一处内容变化，也不能判定折叠出错。",
		)
	)
	return findings


# ---------- R5 Provider / 流解析失败 ----------


def check_provider_stream(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	for mr in turn_scoped(run.model_requests, run.turn_id):
		attempts = mr.attempts
		for idx, att in enumerate(attempts):
			status = _s(att.get("status"))
			kind = _s(att.get("kind"))
			if kind != "llm.failure" and status not in _FAILED_MODEL_STATUSES:
				continue
			http = att.get("http_status")
			attempt_no = att.get("attempt")
			# 证据正文要带上结论所依据的那几个字段：原先只写一个 kind
			# （"model.finished"），断言"这枪 status=protocol_fallback"的结论
			# 在证据里看不到 status，读者只能按行号自己回读。
			detail_bits = [kind or "model_attempt"]
			for bit, val in (("status", status), ("error_code", _s(att.get("error_code"))), ("http", _s(http))):
				if val:
					detail_bits.append(f"{bit}={val}")
			detail_bits.append(f"attempt={_s(attempt_no)}")
			evidence = [
				EvidenceRef(
					source="audit",
					locator=_loc(run),
					ref_id=f"L{_s(att.get('line_no'))}",
					detail=" ".join(detail_bits),
				)
			]
			# 重试是设计里的下一步：同一逻辑调用后面还有尝试在跑时，
			# 中间那次 retry 记录不构成故障，本轮的结论要看最后一次。
			if status == "retry" and idx < len(attempts) - 1:
				continue
			component = "模型适配器 / 传输"
			impact = f"逻辑调用 {mr.model_request_id} 的第 {attempt_no} 次尝试未产出正常结果。"
			if status == "aborted":
				# engine/query_loop.py 的 except Aborted 分支：用户停止/中断。
				# 它不是厂商返回，也不是传输故障 —— 定责到 model_request 边界是误归因。
				verdict = UNKNOWN
				phen = f"模型尝试被中止（attempt={attempt_no}）"
				gap = "中止来自引擎的 Aborted 分支（用户停止/中断），与厂商返回无关；谁触发的不在审计行里。"
				allowed = "只能说明这一枪没跑完；不能据此判定模型或引擎出错。"
			elif status == "retry":
				# 最后一次尝试停在 retry 且没有后续记录：结果未知，不是已确认失败。
				verdict = UNKNOWN
				phen = f"模型尝试以 status=retry 结束且没有后续尝试记录（attempt={attempt_no}）"
				gap = f"重试的下一枪若没落审计行，{scope_word(run)}就看不到最终结果。"
				allowed = "只能说这一枪停在重试状态、后续未落记录；不能据此判定请求失败。"
			elif status == "protocol_fallback":
				verdict = CONFIRMED_FAULT
				phen = f"模型请求被协议回退接管（status=protocol_fallback，code={_s(att.get('error_code'))}，attempt={attempt_no}）"
				gap = "厂商内部为什么拒这个请求形状不可见；只能定位到适配器提交边界。"
				allowed = (
					"可确认这一枪的请求形状被厂商拒过、引擎降级重打（白多一次请求）；"
					"不能据此判定提示词内容错误。"
				)
			else:
				verdict = CONFIRMED_FAULT
				if kind == "llm.failure":
					# 厂商没给 HTTP 码时行里是 status=null（真实 24 行 llm.failure 有 4 行如此）。
					# 空位直接印出来会变成「status=，」，读起来像"厂商返回了空状态"。
					phen = (
						f"模型请求失败（attempt={attempt_no}，status={_s(http) or '未记录'}，"
						f"code={_s(att.get('error_code'))}）"
					)
				else:
					phen = f"模型尝试以 status={status} 结束（attempt={attempt_no}）"
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
					status=verdict,
					evidence=evidence,
					impact=impact,
					coverage_gap=gap,
					allowed_conclusion=allowed,
				)
			)
	return findings


# ---------- R6 权限等待 / 拒绝 ----------


def _permission_row_ref(run: RunEvidence, row: dict[str, Any]) -> EvidenceRef:
	"""审批行的证据正文：把结论所依据的字段一起写出来。

	只写 kind（"permission.resolved"）时，"以 timeout 收口""被权限层挡住"这类断言在
	证据里看不见依据 —— 与 ``_tool_error_detail``、provider 证据同族（R7 / R5 已修）。
	"""
	parts = [_s(row.get("kind")) or "permission"]
	for key in ("outcome", "permission_action", "matched_rule", "permission_reason_code", "reason", "actor"):
		value = _s(row.get(key))
		if value:
			parts.append(f"{key}={value}")
	if isinstance(row.get("approved"), bool):
		parts.append(f"approved={row.get('approved')}")
	parts.append(f"request_id={_s(row.get('request_id'))}")
	return EvidenceRef(
		source="audit",
		locator=_loc(run),
		ref_id=f"L{_s(row.get('line_no'))}",
		detail=" ".join(parts),
	)


def check_permission_block(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	by_approval: dict[str, list[dict[str, Any]]] = {}
	for row in turn_scoped(run.permissions, run.turn_id):
		by_approval.setdefault(_s(row.get("request_id")), []).append(row)
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
					impact=f"{scope_word(run)}可能停在等待用户，而不是卡死。",
					coverage_gap="pending 存储是纯内存进程状态，服务重启后无法判断当时是否仍在等待。",
					allowed_conclusion="等待与中断两种可能都未被排除。",
				)
			)
			continue
		last = resolved[-1]
		outcome = permission_outcome(last)
		if outcome in _UNANSWERED_OUTCOMES:
			# 超时与中止都是执行层的**结果**，不是故障：
			# timeout 来自 engine/permission_coordinator.py::wait —— 没人答复时按不放行收口
			# （fail-closed，写 approved=False + outcome="timeout"）；aborted 来自 engine/abort.py
			# 的停止分支。真实数据（分层普查 57 轮）里这一档占该规则全部 7 条"已确认"，
			# 与"预期拒绝不得计成产品故障"的自有口径自相矛盾。
			findings.append(
				Finding(
					rule_id="permission_block",
					rule_version=RULESET_VERSION,
					phenomenon=f"工具 {_s(pending[0].get('tool_name'))} 的授权等待以 {outcome} 收口（规则={_s(pending[0].get('matched_rule'))}）",
					boundary="tool_permission",
					component="权限执行层（等待超时 / 中止）",
					status=UNKNOWN,
					evidence=[_permission_row_ref(run, r) for r in rows],
					impact="这一枪未执行：等待没人答复时按不放行收口，中止来自停止操作。",
					coverage_gap="谁在等、等多久、期间界面有没有弹出来都不在审计行里；这两类结果都不证明权限层出了故障。",
					allowed_conclusion="可确认执行停在权限等待的结果上；不能据此判定权限层或审批链故障。",
				)
			)
		elif outcome in _BLOCKED_OUTCOMES:
			findings.append(
				Finding(
					rule_id="permission_block",
					rule_version=RULESET_VERSION,
					phenomenon=f"工具 {_s(pending[0].get('tool_name'))} 被权限层挡住（结果={outcome}，规则={_s(pending[0].get('matched_rule'))}）",
					boundary="tool_permission",
					component="权限执行层（DENY / 超时）",
					status=CONFIRMED_FAULT,
					evidence=[_permission_row_ref(run, r) for r in rows],
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
					evidence=[_permission_row_ref(run, r) for r in rows],
					impact="这一行说不上放行还是拦下：把「没记结果」读成「已通过」或「已拒绝」都会造出假结论。",
					coverage_gap="permission.resolved 的三个结果字段（approved / outcome / permission_action）任缺其一就无法核对；旧审计不补写。",
					allowed_conclusion="只能报审批结果未记录，不能报这一枪通过或失败。",
				)
			)
	own_permissions = turn_scoped(run.permissions, run.turn_id)
	pending_ids = {
		_s(r.get("request_id")) for r in own_permissions if _s(r.get("kind")).startswith("permission.pending")
	}
	gated = [
		r
		for r in own_permissions
		if _s(r.get("kind")).startswith("permission.denied") and _s(r.get("request_id")) not in pending_ids
	]
	if gated:
		by_tool: dict[str, int] = {}
		for row in gated:
			name = _s(row.get("tool_name")) or "未记录工具"
			by_tool[name] = by_tool.get(name, 0) + 1
		shapes = "、".join(f"{name} {n} 次" for name, n in sorted(by_tool.items(), key=lambda kv: (-kv[1], kv[0])))
		findings.append(
			Finding(
				rule_id="permission_block",
				rule_version=RULESET_VERSION,
				phenomenon=f"{len(gated)} 次工具调用没进审批等待就被执行层挡下（{shapes}）",
				boundary="tool_permission",
				component="权限执行层（策略 DENY / 只读门）",
				# 只读门与策略 DENY 本来就不弹审批：真实审计 214 行 permission.denied
				# 每一行在整份审计里只此一行 —— 没有 pending 兄弟，也没有 tool.started /
				# tool.finished（2026-09-26 逐 id 追踪）。上面那条按 pending 配对的通路
				# 整条看不到它们，"这一枪为什么没执行"于是没有答案。
				status=UNKNOWN,
				evidence=[_permission_row_ref(run, r) for r in gated[:12]],
				impact="这些调用没有执行：模型拿到的是执行层的拒绝结果；被哪条规则、以什么理由挡下列在证据里。",
				coverage_gap=(
					"这一形不落 tool.started / tool.finished，调用意图只能按 tool_name 与时刻近似对应；"
					"策略表里那条规则当初为什么写、能不能申请放开，不在审计里。"
				),
				allowed_conclusion=(
					"可确认这一枪被执行层按策略挡下及其规则与理由；策略拒绝是执行层的设计结果，"
					"不得计成产品故障，也不得据此说模型没有尝试。"
				),
			)
		)
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
				phenomenon="权限记录不带 tool_use_id / model_request_id（写入时引擎还没带这两个字段，或来自不落关联身份的路径）",
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
	return findings


# ---------- R7 工具 / 进程失败 ----------


def _tool_error_detail(tool: Any) -> str:
	"""工具失败那条审计行的证据文本。

	error_kind 必须写在这里：fault_split 只从证据 detail 读归属，detail 里没有它
	就等于两张归属表从来没被生产数据读到过（2026-09-25 实测 74/74 条落空）。
	"""
	parts = ["tool.finished is_error=true"]
	kind = _s(tool.error_kind)
	if kind:
		parts.append(f"error_kind={kind}")
	parts.append(f"action_id={_s(tool.action_id)}")
	return " ".join(parts)


def check_tool_failure(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	failed = [t for t in turn_scoped(run.tool_calls, run.turn_id) if t.finished and t.is_error]
	if not failed:
		return findings
	grouped: dict[tuple[str, str], list[Any]] = {}
	for tool in failed:
		grouped.setdefault((tool.tool_name, tool.error_kind), []).append(tool)
	for (name, error_kind), items in sorted(grouped.items()):
		# INTERNAL 不是分类：tools/base_tool.py 给所有"只回了 is_error + 文本"的错误
		# 统一填 INTERNAL，tools/error_taxonomy.py::classify_exception 也只接在
		# orchestration（子代理工具）上。真实数据里非空的 error_kind 100% 是 INTERNAL
		# （2026-09-25 尾窗 12 000 行：INTERNAL=129，其余取值 0）⇒ 把它印成分类是给
		# 读者一个不存在的区分，写进归属表就是把所有工具失败判给我方引擎。
		classified = error_kind if error_kind and error_kind != "INTERNAL" else ""
		findings.append(
			Finding(
				rule_id="tool_failure",
				rule_version=RULESET_VERSION,
				phenomenon=(
					f"工具 {name} 返回错误（{f'error_kind={classified}' if classified else '错误分类未细分'}，共 {len(items)} 次）"
				),
				boundary="tool_permission",
				component=f"工具执行：{name}",
				status=CONFIRMED_FAULT,
				evidence=[
					EvidenceRef(
						source="audit",
						locator=_loc(run),
						ref_id=f"L{_s((t.finished or {}).get('line_no'))}",
						detail=_tool_error_detail(t),
					)
					for t in items
				][:20],
				impact="失败步骤已定位到工具与 action_id；结果正文按需在 transcript 里回读。",
				coverage_gap=(
					"审计不含退出码与 stderr 正文；「测试失败」与「测试无法运行」不在本规则区分范围内（见 verifier）。"
					"error_kind 未细分（INTERNAL 或未记录）时不得据此定责。"
				),
				allowed_conclusion="可确认工具在这一步失败；未细分的分类不支持把责任落到某一方。",
			)
		)
	return findings


# ---------- 工具改道（执行层 bash 路由）----------


def check_tool_routing(run: RunEvidence) -> list[Finding]:
	"""``tool.routed`` 行的事实：模型请求执行 A，执行层实际跑了 B。

	改道此前在整个诊断面上是隐形的：审计有行、采集器把它们归到工具边界，
	但没有任何一条规则读 ``routed_to``（2026-09-25 对照生产者清单时发现，
	真实语料里 94 行、带完整的会话/轮次/调用身份）。
	"""
	# ``tool.routed_observed`` 刻意不读：那是 Phase 0 观测（计划命中但**不拦截**，
	# 见 tools/tool_registry.py::_observe_bash_route），把它说成"被改道执行"就是假话。
	routed = [e for e in run.events_for_turn() if e.kind == "tool.routed"]
	if not routed:
		return []
	by_target: dict[str, list[Any]] = {}
	for event in routed:
		by_target.setdefault(_kv(event, "routed_to") or "（未记录目标）", []).append(event)
	targets = "、".join(f"{name} {len(items)} 次" for name, items in sorted(by_target.items()))
	return [
		Finding(
			rule_id="tool_routing",
			rule_version=RULESET_VERSION,
			# 措辞里不写"这一轮"：报告端点也接受空 turn_id 的会话级运行（server/routers/diagnostics.py::post_report），
			# 那种范围下说"这一轮"就是把会话级的行数算给一轮。
			phenomenon=f"{len(routed)} 次工具调用在执行层换了工具：{targets}",
			boundary="tool_permission",
			component="工具分发（bash 路由）",
			# 未定不是"读不出"，而是与权限层同一裁定：执行层按策略做出的**结果**不计成产品故障
			# （见 check_permission_block 里 timeout / aborted 那一档的理由）。
			# 改道是设计行为，归因层因此不拿它定责；但它必须可见 —— 这一步的报错与输出
			# 来自另一个工具，不先看清它就给上一轮下结论会读错证据。
			status=UNKNOWN,
			evidence=[
				_event_ref(
					run,
					event,
					f"{_kv(event, 'tool_name') or 'Bash'}→{_kv(event, 'routed_to')} {_kv(event, 'command')[:80]}",
				)
				for event in routed
			],
			impact="模型请求的是左边的工具，实际执行的是右边的：这一步的输出、报错与耗时都来自改写后的工具。",
			coverage_gap=(
				"改道发生在执行层、模型侧不回显，transcript 里看不出这一步被改过；"
				"目标工具被会话路径拒绝时会回退执行原调用且不留 tool.routed 行"
				"（tools/tool_registry.py 的回退分支），所以这里只能说改道成了什么，"
				"不能说每次同类请求都会被改道。"
			),
			allowed_conclusion="可确认这一步实际执行的是哪个工具；改道本身是执行层策略，不得据此判定分发故障。",
		)
	]


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
		# 缺口通知是 SSE 帧，过去没有任何地方为它落审计行 —— 这一支读的是
		# notice.channel 上一个从未被写过的 kind_detail 字段，所以在生产里永远不命中，
		# 而界面却已经按"sse_gui 边界有规则覆盖"展示它。现在读 stream.gap
		# （engine/turn_runner.py 在发出缺口帧的同一处落审计）。
		if event.kind != "stream.gap":
			continue
		dropped = _kv(event, "dropped_through_event_id")
		first = _kv(event, "first_available_event_id")
		findings.append(
			Finding(
				rule_id="wire_gap",
				rule_version=RULESET_VERSION,
				phenomenon=f"重放起点已被环形缓冲挤掉：事件 {dropped} 之前的帧不在，界面只拿到 {first} 起的那一段",
				boundary="sse_gui",
				component="SSE 传输 / 界面",
				status=SUSPECTED_CAUSE,
				evidence=[_event_ref(run, event, "stream_gap")],
				impact="界面缺一段而服务端可能已完成：显示边界与执行边界要分开判；缺段必须靠重拉 transcript 对账。",
				coverage_gap=(
					"只知道服务端告知了缺口，客户端有没有真的补回这一段不在审计里。"
					"这条判据需要引擎写出 stream.gap 行：重启前产生的旧轮次看不到（不是没发生）。"
				),
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
			# 只把**没配上结束记录的那几次开始**列进证据。整串 starts 会让用户点到
			# 已经正常结束的 attempt（重试场景下 2 开始 1 结束是常态）。
			unpaired = starts[len(finishes):]
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
						for a in unpaired
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
		if error_kind:
			phen = f"工具 {name} 以同一 error_kind={error_kind} 重复失败 {len(events)} 次"
			group_note = "同一工具与同一错误签名在有界窗口内反复出现"
		else:
			# 真实审计 16 229 行 tool.finished 里带 error_kind 键的 2 948 行有 2 819 行是
			# null（非空的 129/129 又都是 INTERNAL），而审计从来不带参数 ⇒ 分类位空时，
			# "同一签名"实际只剩工具名。说成"同一错误签名"就是把读不出当成一个取值。
			phen = f"工具 {name} 重复失败 {len(events)} 次（错误分类未记录：这一组只按工具名归）"
			group_note = "只按工具名在有界窗口内归组：错误分类没有记录位，签名里没有别的区分项"
		findings.append(
			Finding(
				rule_id="repeated_failure",
				rule_version=RULESET_VERSION,
				phenomenon=phen,
				boundary="tool_permission",
				component=f"工具执行：{name}",
				status=SUSPECTED_CAUSE,
				evidence=[_event_ref(run, e, "重复失败") for e in events][:12],
				impact=f"重复失败信号：{group_note}；参数是否相同不可证（审计不带参数）。",
				coverage_gap="审计不含完整参数，签名相同不等于参数相同；窗口外的重复看不到。",
				allowed_conclusion="不得据此断言死循环，也不得自动改写模型计划。",
			)
		)
	return findings


# ---------- R11 用量账目 ----------


def check_usage_accounting(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	known_sources = {"api", "estimate"}
	missing: list[EvidenceRef] = []
	missing_retried: list[EvidenceRef] = []
	duplicated: list[EvidenceRef] = []
	bad_source: list[EvidenceRef] = []
	for mr in turn_scoped(run.model_requests, run.turn_id):
		for att in mr.attempts:
			if _s(att.get("kind")) != "model.finished":
				continue
			status = _s(att.get("status"))
			if status not in {"ok", "retry", "protocol_fallback"}:
				continue
			key = request_key(mr.model_request_id, att.get("attempt"))
			rows = [row for row in run.usage_rows if _s(row.get("attempt_key")) == key]
			if not rows:
				ref = EvidenceRef(
					source="audit",
					locator=_loc(run),
					ref_id=f"L{_s(att.get('line_no'))}",
					detail=f"attempt {key} 无用量账",
				)
				# 成功结束的那一枪本该带用量；重打／换通道的那一枪未必拿到过用量尾帧，
				# 两者不能共用一句"已确认故障"（理由见下方 missing_retried 的 coverage_gap）。
				(missing if status == "ok" else missing_retried).append(ref)
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
				phenomenon=f"{len(missing)} 次成功结束的模型尝试在用量账本里没有对应记录",
				boundary="model_request",
				component="用量账本（usage/ledger）",
				status=CONFIRMED_FAULT,
				evidence=missing[:20],
				impact="这些请求的费用未知：不得按 0 元计入合计，也不得释放实验预算预留。",
				coverage_gap="账本在 usage 缺失时整行不写，因此「没有行」既可能是没计费也可能是没落账。",
				allowed_conclusion="报告为费用未知/账目缺失。",
			)
		)
	if missing_retried:
		findings.append(
			Finding(
				rule_id="usage_accounting",
				rule_version=RULESET_VERSION,
				phenomenon=(
					f"{len(missing_retried)} 次重打或换通道结束的尝试在用量账本里没有对应记录："
					"费用未知，但不因此记成账目故障"
				),
				boundary="model_request",
				component="用量账本（按尝试归账）",
				# 生产者契约：适配器拿到厂商用量才写行（model/deepseek.py::_record_usage_safe
				# 的 ``if not usage: return``）。被打断的一枪没拿到用量尾帧时，账本按契约
				# 本来就没有行——把它写成"已确认故障"是凭空给引擎认一笔账。
				status=UNKNOWN,
				evidence=missing_retried[:20],
				impact="这些尝试的费用未知：不得按 0 元计入合计。",
				coverage_gap=(
					"没有行既可能是这一枪没拿到厂商用量（重打与换通道常在尾帧到达前就中断），"
					"也可能是拿到了却没落账；成功结束的那一枪才一定要有用量。两种情况在此分不开，"
					"所以只报费用未知，不报账目故障。"
				),
				allowed_conclusion="可确认这笔费用无从核对；不得据此判定账本漏记，也不得按 0 计入。",
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
	# 「账本行不带 request_id」不再作为本轮结论报出：这类行没有轮次身份，归属只到
	# "会话 + 尾窗"一级，此前被同会话的每一轮重复报成同一条（真实数据 37/40 轮）。
	# 事实保留在采集缺项里（collect._collect_usage 的 unattributed_rows），
	# 报告侧的笔数仍由 report.cost 的 unlinked_usage_rows 承担。
	return findings


# ---------- R12 验收 ----------


def check_verifier(run: RunEvidence) -> list[Finding]:
	findings: list[Finding] = []
	pinned = [p for p in run.pins if _s(p.get("kind")) == "verifier"]
	if not pinned:
		# 不再作为结论报出：采集器已把这条事实放进缺项清单（collect._attach_pins）。
		# 它此前在真实数据里 40/40 轮都产出一条 unknown —— 一条恒真的"未定"
		# 不携带信息，只会把需要人工判断的那几条淹掉。
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
		("tool_routing", check_tool_routing),
		("wire_gap", check_wire_gap),
		("incomplete_run", check_incomplete_run),
		("repeated_failure", check_repeated_failure),
		("usage_accounting", check_usage_accounting),
		("verifier", check_verifier),
	)
)


def no_turn_records_finding(run: RunEvidence) -> Finding:
	"""「本轮读不出自身记录」：采集跑过，但这个轮子没有带自己身份的记录。

	它必须是 unknown 加写明缺什么，不能是一个干净通过：会话级的 transcript /
	working / usage 记录并不属于本轮，拿它们给本轮下结论就是误归因。

	三种"读不出"不是一件事，措辞必须分开（真实数据分层普查 57 轮里曾有 11 轮落在这条，
	其中没有一轮是真的"没记录"，全是尾窗没覆盖到 —— 采集层现已在 miss 路径上扩窗重读，
	见 collect._collect_audit；剩下会落到这里的才是下面三种）：
	- 窗口整份读完：本轮确实没有带身份的记录（多半是深链来的错轮次号）；
	- 窗口截断且本会话零行：连会话都不在尾窗里，本轮无从谈起；
	- 窗口截断但本会话有行：会话在窗口内，这一轮不在（更早，或行不带轮次身份）。
	"""
	window = run.window("audit")
	if window is None:
		phen = f"本轮无记录：没有审计采集窗口，无从判断 turn_id={run.turn_id} 是否有记录"
		gap = "本次运行没有审计采集窗口：既不能说有记录，也不能说没有。"
		evidence = [
			EvidenceRef(source="config", locator="diagnostics/rules.py", ref_id="no_turn_records", detail="无审计采集窗口")
		]
	elif window.complete:
		phen = f"本轮无记录：审计窗口整份读完，本会话 {window.rows_matched} 行里没有一条带 turn_id={run.turn_id}"
		gap = (
			"窗口已读完，所以这不是覆盖不足：剩下的可能是轮次号来自别处/已删轮，"
			"或该轮的记录本就不带 turn_id（旧审计格式）。"
		)
		evidence = [
			EvidenceRef(
				source="audit",
				locator=_s(window.locator),
				ref_id="",
				detail=f"整份读完：扫描 {window.rows_scanned} 行、本会话 {window.rows_matched} 行，无 turn_id={run.turn_id} 的事件",
			)
		]
	elif not window.rows_matched:
		phen = f"尾窗没覆盖到这个会话：审计只读最近 {window.rows_scanned} 行，本会话零行在窗内（turn_id={run.turn_id} 无从判断）"
		gap = (
			"这是采集范围，不是这一轮的性质：尾窗之外的行没有被读，"
			"所以本轮既不能判没发生，也不能判正常或异常。扩大 XEYO_DIAGNOSTICS_AUDIT_BYTES 或换较新的轮次再看。"
		)
		evidence = [
			EvidenceRef(
				source="audit",
				locator=_s(window.locator),
				ref_id="",
				detail=f"尾窗截断：扫描 {window.rows_scanned} 行，其中 {window.rows_other_session} 行属于其他会话",
			)
		]
	else:
		phen = (
			f"本会话在尾窗内有 {window.rows_matched} 行，但没有一条带 turn_id={run.turn_id}"
			f"（{window.rows_other_turn} 行属于其他轮次）"
		)
		gap = (
			"尾窗截断，且窗口里没有这一轮的行：可能是这一轮比尾窗更早，"
			"也可能是它的记录不带轮次身份；两种都不能读成「本轮没有发生任何事」。"
		)
		evidence = [
			EvidenceRef(
				source="audit",
				locator=_s(window.locator),
				ref_id="",
				detail=f"扫描 {window.rows_scanned} 行、匹配 {window.rows_matched} 行，无 turn_id={run.turn_id} 的事件",
			)
		]
	return Finding(
		rule_id="no_turn_records",
		rule_version=RULESET_VERSION,
		phenomenon=phen,
		boundary="user_request",
		component="证据采集（轮次身份）",
		status=UNKNOWN,
		evidence=evidence,
		impact="会话级记录（transcript / working / usage）不属于本轮：本轮没有任何可核对的自身记录，规则集本轮未运行。",
		coverage_gap=gap + "不带 turn_id 的旧审计行也不参与轮次归因。",
		allowed_conclusion="只能报本轮读不出自身记录，并说明是哪一种读不出；同会话别处的记录不得算给本轮。",
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
					impact=f"该规则{scope_word(run)}未产生结论。",
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
	"check_tool_routing",
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
