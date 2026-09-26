/**
 * features/diagnostics/model.ts — 诊断页的纯函数层（无 React、无 fetch）。
 *
 * 这里放的是**措辞纪律**的落点，因此单独成模块以便直接单测：
 * - 缺用量 → null → 「费用未知」，永不显示 ¥0；
 * - 每次重试各成一行（按 (model_request_id, attempt) 分组，绝不折叠成最后一次）；
 * - 等待授权 / 长任务 ≠ 失败：tone 用 waiting / active，不用 fail；
 * - 不合成概率、不加权总分：只有后端字段与固定措辞。
 */
import type {
	DiagAttempt,
	DiagEvidenceRef,
	DiagFinding,
	DiagGap,
	DiagModelRequest,
	DiagPermission,
	DiagRunDetail,
	DiagUsageRow,
	DiagWindow,
} from '@/lib/api/diagnostics';

export type TimelineTone =
	| 'neutral'
	| 'active'
	| 'waiting'
	| 'ok'
	| 'warn'
	| 'fail';

export type TimelineRow = {
	key: string;
	ts: number | null;
	source: 'model' | 'tool' | 'permission' | 'job' | 'event';
	kind: string;
	/** 中文动作词（事实型措辞，不含评价）。 */
	title: string;
	/** 关联身份（model_request_id / tool_use_id / approval_id / job_id）。 */
	subject: string;
	statusText: string;
	tone: TimelineTone;
	/** 「第 N 次尝试」；非模型行为空串。 */
	attemptText: string;
	durationMs: number | null;
	/** null = 该尝试没有用量账 → 费用未知（不是 0）。 */
	costCny: number | null;
	hasUsage: boolean;
	boundary: string;
	lineNo: number | null;
	evidence: DiagEvidenceRef[];
	/** 审计行里没中文名 / 值为嵌套结构的原文字段：只在展开后出现，不进状态行。 */
	rawFields: RawAuditField[];
};

// ---------------------------------------------------------------------------
// 格式化（null 一律 '—'）
// ---------------------------------------------------------------------------

export const DASH = '—';

export function fmtDash(v: string | number | null | undefined): string {
	if (v === null || v === undefined) return DASH;
	if (typeof v === 'string') return v.trim() ? v : DASH;
	return String(v);
}

/** 审计 ts 是 epoch 秒；缺值不猜。 */
export function fmtClock(ts: number | null | undefined): string {
	const raw = ts == null ? null : ts;
	if (raw == null) return DASH;
	const ms = raw < 1e12 ? raw * 1000 : raw;
	const d = new Date(ms);
	if (Number.isNaN(d.getTime())) return DASH;
	const p = (x: number) => String(x).padStart(2, '0');
	return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function fmtDuration(ms: number | null | undefined): string {
	if (ms == null || !Number.isFinite(ms) || ms < 0) return DASH;
	if (ms < 1000) return `${Math.round(ms)}ms`;
	if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
	const total = Math.floor(ms / 1000);
	const m = Math.floor(total / 60);
	const sec = total % 60;
	return `${m}:${String(sec).padStart(2, '0')}`;
}

/** 费用：null = 费用未知；有账才出金额（¥0 也只可能来自真实账目）。 */
export function fmtCostCny(v: number | null | undefined): string {
	if (v == null || !Number.isFinite(v)) return '费用未知';
	return `¥${Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2)}`;
}

export function fmtInt(v: number | null | undefined): string {
	if (v == null || !Number.isFinite(v)) return DASH;
	return Math.round(v).toLocaleString('en-US');
}

/** 字节 → 人类可读（采集配额用）；null = 未知。 */
export function fmtBytes(v: number | null | undefined): string {
	if (v == null || !Number.isFinite(v)) return DASH;
	if (v < 1024) return `${v} B`;
	const units = ['KB', 'MB', 'GB', 'TB'];
	let out = v;
	let i = -1;
	do {
		out = out / 1024;
		i += 1;
	} while (out >= 1024 && i < units.length - 1);
	return `${out.toFixed(out >= 10 ? 0 : 1)} ${units[i]}`;
}

// ---------------------------------------------------------------------------
// 结论分组 / 措辞
// ---------------------------------------------------------------------------

export type FindingStatus = 'confirmed_fault' | 'suspected_cause' | 'unknown';

export const FINDING_STATUS_LABEL: Record<FindingStatus, string> = {
	confirmed_fault: '已确认',
	suspected_cause: '疑似',
	unknown: '未定',
};

export function findingStatusOf(f: DiagFinding): FindingStatus {
	if (f.status === 'confirmed_fault') return 'confirmed_fault';
	if (f.status === 'suspected_cause') return 'suspected_cause';
	return 'unknown';
}

/** 无已确认异常时的固定免责措辞（不得渲染成绿色"通过"）。 */
export const NO_CONFIRMED_FAULT_TEXT =
	'本次规则集未发现已确认异常，这不等于任务正确';

/** 未归因时的固定措辞。 */
export const NOT_ATTRIBUTED_TEXT = '无法归因';

export function groupFindingsByStatus(
	findings: DiagFinding[],
): Record<FindingStatus, DiagFinding[]> {
	const out: Record<FindingStatus, DiagFinding[]> = {
		confirmed_fault: [],
		suspected_cause: [],
		unknown: [],
	};
	for (const f of findings) out[findingStatusOf(f)].push(f);
	return out;
}

export function hasConfirmedFault(findings: DiagFinding[]): boolean {
	return findings.some(f => findingStatusOf(f) === 'confirmed_fault');
}

/**
 * 归因块措辞：后端 statement 优先；缺字段时按同一纪律给保守文案，
 * 永不产出「没有异常 / 通过」。
 */
export function attributionLines(detail: DiagRunDetail): string[] {
	const att = detail.attribution;
	const lines: string[] = [];
	if (!att) {
		lines.push(NOT_ATTRIBUTED_TEXT + '：本轮未取回归因块（报告未生成或来源不可读）。');
		return lines;
	}
	lines.push(
		att.attributed
			? `首个已确认异常边界：${att.first_anomaly_label || DASH}`
			: `${NOT_ATTRIBUTED_TEXT}：没有已确认异常的边界记录。`,
	);
	lines.push(
		att.attributed
			? `它之前最近一个有记录的边界：${att.last_evidenced_label || '无（更早的边界连记录都没有）'}（有记录不等于已确认正常）`
			: `最近一个有记录的边界：${att.last_evidenced_label || DASH}（本轮没有已确认异常，这条只说明记录读到哪儿）`,
	);
	if (att.statement) lines.push(att.statement);
	return lines;
}

/** 采集/记录完整性措辞：absent ≠ 没发生。 */
export const COVERAGE_STATE_LABEL: Record<string, string> = {
	full: '完整',
	partial: '部分',
	absent: '无记录',
	redacted: '已脱敏',
	expired: '已过期',
	not_captured: '未采集',
};

/** 缺项原因码 → 中文。真实载荷上这些码会直接进界面，原样投出去就是机器名。 */
export const GAP_REASON_LABEL: Record<string, string> = {
	absent: '该来源缺失',
	out_of_window: '超出采集窗口',
	recovered_outside_window: '尾窗外的记录已扩窗读回',
	not_found_in_full_file: '读完整份记录仍无本轮身份',
	source_absent: '来源文件不存在',
	not_captured: '未采集',
	not_recorded: '该级未记账',
	no_records: '该来源对本会话没有记录行',
	unattributed_rows: '行内没有可归属的身份',
	not_comparable: '字段粒度不支持这个判断',
	field_missing: '记录里缺该字段',
	missing_evidence: '缺原始证据',
	missing_blob: '冷层正文已不在盘上',
	read_failed: '读取失败',
};

export function gapReasonLabel(reason: string): string {
	if (!reason) return DASH;
	return GAP_REASON_LABEL[reason] ?? `未归类原因（${reason}）`;
}

/** 按 scope 把缺项分成"本轮特有"与"整个会话共有"。
 *
 * scope 由生产者判定并随载荷下发（同一会话内这几条要么每轮都在、要么都不在），
 * 界面只负责把它折叠到会话级一次呈现——不自己按原因码猜，避免第二套真相。
 * 缺 scope（旧后端）一律落 per_turn，宁可逐轮照旧也不误折叠。
 */
export function splitGapsByScope(gaps: DiagGap[]): {perTurn: DiagGap[]; session: DiagGap[]} {
	const perTurn: DiagGap[] = [];
	const session: DiagGap[] = [];
	for (const g of gaps) {
		(g.scope === 'session' ? session : perTurn).push(g);
	}
	return {perTurn, session};
}

export function coverageStateLabel(state: string): string {
	return COVERAGE_STATE_LABEL[state] ?? (state || DASH);
}

export const FACT_STATE_LABEL: Record<string, string> = {
	found: '找到',
	absent: '未命中',
	folded_out: '被折叠移出投影（未送达）',
	not_recorded: '该级未记账',
	not_captured: '该级未采集',
	unreadable: '不可读',
};

export function factStateLabel(state: string): string {
	return FACT_STATE_LABEL[state] ?? (state || DASH);
}

/** 固定证据的种类：后端存的是 snake_case id，界面只出中文（未知种类原样带出，不静默丢）。 */
export const PIN_KIND_LABEL: Record<string, string> = {
	run_mark: '结果标记',
	verifier: '验收记录',
};

export function pinKindLabel(kind: string): string {
	if (!kind) return '标记';
	return PIN_KIND_LABEL[kind] ?? kind;
}

// ---------------------------------------------------------------------------
// 审计行字段 → 中文（界面不得出现 `session_id=…` 这类原文标签）
// ---------------------------------------------------------------------------

/** 值得直接展示的审计字段：其余进折叠的「审计行原文」块。 */
export const AUDIT_FIELD_LABEL: Record<string, string> = {
	model_request_id: '模型请求',
	attempt: '尝试',
	tool_use_id: '工具调用',
	tool_name: '工具',
	approval_id: '审批请求',
	request_id: '审批请求',
	projection_id: '投影',
	action_id: '动作',
	message_id: '消息',
	job_id: '后台任务',
	matched_rule: '命中规则',
	reason: '原因',
	status: '状态',
	is_error: '返回错误',
	error_kind: '错误类别',
	duration_ms: '耗时毫秒',
	exit_code: '退出码',
	agent_id: '子代理',
	agent_mode: '代理模式',
	command_summary: '命令摘要',
};

/** 结构身份已经单独呈现、不必重复出现在状态行里的键。 */
const AUDIT_FIELD_HIDDEN = new Set([
	'ts',
	'kind',
	'session_id',
	'turn_id',
	'trace_id',
	'line_no',
	'seq',
	'event_id',
	'correlation_id',
]);

export type RawAuditField = {key: string; value: string};

/** 只有标量能进状态行：对象/数组经 `String()` 会变成 `[object Object]`，
 *  经既有 `str()` 会变成空串，于是渲染出 `provider=` 这种吊尾标签。 */
function scalarText(v: unknown): string | null {
	if (typeof v === 'string') return v.trim() ? v : null;
	if (typeof v === 'number') return Number.isFinite(v) ? String(v) : null;
	if (typeof v === 'boolean') return v ? '是' : '否';
	return null;
}

function rawTextOf(v: unknown): string {
	if (v === null || v === undefined) return DASH;
	if (typeof v === 'object') {
		try {
			return JSON.stringify(v) ?? DASH;
		} catch {
			return '[不可序列化]';
		}
	}
	return String(v);
}

/**
 * 审计行拆成「中文可展示字段」与「原文字段」两组：前者进状态行（有中文名才展示，
 * 且值必须是标量），后者进折叠块，保证既不丢信息也不把英文键名当标签。
 */
export function describeAuditRow(row: Record<string, unknown>): {
	shown: string[];
	raw: RawAuditField[];
} {
	const shown: string[] = [];
	const raw: RawAuditField[] = [];
	for (const [k, v] of Object.entries(row ?? {})) {
		if (AUDIT_FIELD_HIDDEN.has(k)) continue;
		const scalar = scalarText(v);
		const label = AUDIT_FIELD_LABEL[k];
		if (label && scalar) {
			if (shown.length < 4) shown.push(`${label} ${scalar}`);
			else raw.push({key: k, value: scalar});
			continue;
		}
		raw.push({key: k, value: rawTextOf(v)});
	}
	return {shown, raw};
}

// ---------------------------------------------------------------------------
// 时间线
// ---------------------------------------------------------------------------

/** 时间戳统一到毫秒：审计/job 用 epoch 秒，GUI 差值按毫秒算。 */
function toMs(v: unknown): number | null {
	if (typeof v !== 'number' || !Number.isFinite(v)) return null;
	if (v <= 0) return null;
	return v < 1e12 ? Math.round(v * 1000) : Math.round(v);
}

function num(v: unknown): number | null {
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	if (typeof v === 'string' && v.trim()) {
		const f = Number(v);
		return Number.isFinite(f) ? f : null;
	}
	return null;
}

function str(v: unknown): string {
	if (typeof v === 'string') return v;
	if (typeof v === 'number' || typeof v === 'boolean') return String(v);
	return '';
}

const KIND_LABEL: Record<string, string> = {
	'model.started': '模型请求发出',
	'llm.failure': '模型请求失败',
	'tool.started': '工具开始执行',
	'tool.finished': '工具结束',
	'permission.pending': '等待权限授权',
	'permission.resolved': '权限已处理',
	'permission.denied': '权限被拒绝',
};

function modelAttemptLabel(a: DiagAttempt): string {
	if (a.kind === 'llm.failure') return '模型请求失败';
	if (a.kind === 'model.finished') return '模型响应结束';
	if (a.kind === 'model.started') return '模型请求发出';
	return a.kind || DASH;
}

/** 授权结果的中文措辞：后端写的是 allow/deny/timeout 一类的机器值。 */
export const PERMISSION_OUTCOME_LABEL: Record<string, string> = {
	allow: '已允许',
	allowed: '已允许',
	approved: '已允许',
	deny: '已拒绝',
	denied: '已拒绝',
	reject: '已拒绝',
	rejected: '已拒绝',
	remind: '本次提醒（未放行）',
	timeout: '超时未答',
	cancel: '已取消',
	cancelled: '已取消',
};

/** 没有任何结果字段时的固定措辞——绝不猜成通过或拒绝。 */
export const NO_OUTCOME_TEXT = '结果未记录';

export function permissionOutcomeLabel(outcome: string): string {
	const k = (outcome || '').trim().toLowerCase();
	return PERMISSION_OUTCOME_LABEL[k] ?? (k || NO_OUTCOME_TEXT);
}

function attemptFailed(a: DiagAttempt): boolean {
	if (a.kind === 'llm.failure') return true;
	if (a.error_code || a.error_kind) return true;
	const st = a.status.toLowerCase();
	return st.includes('error') || st.includes('fail') || st === 'timeout';
}

/**
 * 一次逻辑调用内的多次尝试按 attempt 号分组：同一 attempt 的 started/finished
 * 合成一行，但不同 attempt 绝不合并（设计 §5.1：不能只显示最后一次尝试）。
 */
function groupAttempts(mr: DiagModelRequest): DiagAttempt[][] {
	const order: string[] = [];
	const map = new Map<string, DiagAttempt[]>();
	for (const a of mr.attempts) {
		const k = a.attempt == null ? `_无尝试号_${order.length}` : `#${a.attempt}`;
		if (!map.has(k)) {
			map.set(k, []);
			order.push(k);
		}
		map.get(k)!.push(a);
	}
	return order.map(k => map.get(k)!);
}

function usageOf(mr: DiagModelRequest, attempt: number | null): DiagUsageRow | null {
	const key = mr.model_request_id && attempt != null ? `${mr.model_request_id}#${attempt}` : '';
	if (key && mr.usage_by_attempt[key]) return mr.usage_by_attempt[key];
	const hit = Object.values(mr.usage_by_attempt).find(
		r => r.attempt === attempt && (attempt == null || r.request_id === mr.model_request_id),
	);
	return hit ?? null;
}

function permissionState(perms: DiagPermission[]): Map<string, {pending: DiagPermission[]; resolved: DiagPermission[]}> {
	const map = new Map<string, {pending: DiagPermission[]; resolved: DiagPermission[]}>();
	for (const p of perms) {
		const key = p.request_id || p.tool_use_id;
		if (!key) continue;
		const cur = map.get(key) ?? {pending: [], resolved: []};
		if (p.kind.startsWith('permission.pending')) cur.pending.push(p);
		else cur.resolved.push(p);
		map.set(key, cur);
	}
	return map;
}

/** 一次工具调用是否有尚未结束的授权等待。 */
function waitingApprovalIds(detail: DiagRunDetail): Set<string> {
	const out = new Set<string>();
	const states = permissionState(detail.permissions);
	for (const [key, st] of states) {
		if (st.pending.length && !st.resolved.length) out.add(key);
	}
	return out;
}

export function buildTimeline(detail: DiagRunDetail): TimelineRow[] {
	const rows: TimelineRow[] = [];
	const waiting = waitingApprovalIds(detail);

	// 1) 模型请求：逐 attempt 成行。
	for (const mr of detail.model_requests) {
		for (const group of groupAttempts(mr)) {
			const first = group[0]!;
			const last = group[group.length - 1]!;
			const attemptNo = first.attempt;
			const failed = group.some(attemptFailed);
			const finished = group.some(a => a.kind === 'model.finished' && !attemptFailed(a));
			const usage = usageOf(mr, attemptNo);
			const startMs = toMs(first.ts);
			const endMs = toMs(last.ts);
			const dur =
				num(last.duration_ms) ??
				(startMs != null && endMs != null && endMs >= startMs ? endMs - startMs : null);
			const errText = [last.error_code, last.error_kind, last.status && !finished && !failed ? last.status : '']
				.filter(Boolean)
				.join(' · ');
			rows.push({
				key: `model:${mr.model_request_id}:${attemptNo ?? 'x'}:${first.line_no ?? 0}`,
				ts: last.ts ?? first.ts,
				source: 'model',
				kind: group.map(a => a.kind).filter(Boolean).join(' → ') || DASH,
				title: failed ? '模型请求失败' : finished ? '模型响应结束' : modelAttemptLabel(first),
				subject: mr.model_request_id,
				statusText: [
					`第 ${attemptNo == null ? '?' : attemptNo} 次尝试`,
					mr.model || DASH,
					errText || (finished ? '正常结束' : failed ? '未产出正常结果' : '未见结束记录'),
				]
					.filter(Boolean)
					.join(' · '),
				tone: failed ? 'fail' : finished ? 'ok' : 'active',
				attemptText: `第 ${attemptNo == null ? '?' : attemptNo} 次尝试`,
				durationMs: dur,
				costCny: usage ? usage.cost_cny : null,
				hasUsage: usage != null,
				boundary: 'model_request',
				lineNo: last.line_no ?? first.line_no,
				evidence: mr.evidence,
				rawFields: [],
			});
		}
	}

	// 2) 工具调用：一次调用一行（未结束 = 执行中，不是失败）。
	for (const tc of detail.tool_calls) {
		const startedMs = toMs(num(tc.started?.ts));
		const finishedMs = toMs(num(tc.finished?.ts));
		const dur =
			num(tc.finished?.duration_ms) ??
			(startedMs != null && finishedMs != null && finishedMs >= startedMs
				? finishedMs - startedMs
				: null);
		const waitingHere = tc.approval_ids.some(id => waiting.has(id)) || waiting.has(tc.tool_use_id);
		const isError = tc.is_error === true;
		const parts: string[] = [];
		if (tc.error_kind) parts.push(tc.error_kind);
		if (tc.model_request_id) parts.push(`请求 ${tc.model_request_id}`);
		if (tc.approval_ids.length) parts.push(`授权 ${tc.approval_ids.join(' / ')}`);
		if (!tc.paired) parts.push(tc.started ? '未见结束记录' : '未见开始记录');
		rows.push({
			key: `tool:${tc.tool_use_id}`,
			ts: num(tc.finished?.ts) ?? num(tc.started?.ts),
			source: 'tool',
			kind: tc.paired ? 'tool.started → tool.finished' : tc.started ? 'tool.started' : 'tool.finished',
			title: waitingHere
				? '工具等待授权'
				: isError
					? '工具返回错误'
					: tc.paired
						? '工具执行完成'
						: '工具执行中',
			subject: tc.tool_use_id,
			statusText: [tc.tool_name || DASH, parts.join(' · ')].filter(Boolean).join(' · '),
			tone: waitingHere ? 'waiting' : isError ? 'fail' : tc.paired ? 'ok' : 'active',
			attemptText: '',
			durationMs: dur,
			costCny: null,
			hasUsage: false,
			boundary: 'tool_permission',
			lineNo: num(tc.finished?.line_no) ?? num(tc.started?.line_no),
			evidence: tc.evidence,
			rawFields: [],
		});
	}

	// 3) 权限审批：等待与结果分别成行（等待 ≠ 卡死 ≠ 失败；没记账 ≠ 通过）。
	for (const [key, st] of permissionState(detail.permissions)) {
		const pendingOnly = st.pending.length > 0 && st.resolved.length === 0;
		const last = st.resolved[st.resolved.length - 1];
		// 真实 DENY 审计行由 tools/tool_registry.py 直接落 `permission.denied`，
		// 既没有 outcome 也没有 approved：只看这两个字段会把被挡下的动作读成绿色通过。
		const deniedByKind = st.resolved.some(p => p.kind.startsWith('permission.denied'));
		const rawOutcome = str(last?.outcome) ||
			(last?.approved === false ? 'denied' : last?.approved === true ? 'allowed' : '');
		const outcome = rawOutcome || (deniedByKind ? 'denied' : '');
		const allowed = !deniedByKind && outcome === 'allowed';
		const blocked = deniedByKind || outcome === 'denied' || outcome === 'timeout';
		const recorded = outcome !== '' || deniedByKind;
		const toolName =
			str(st.pending[0]?.tool_name) || str(last?.tool_name) || DASH;
		const rawFields = st.resolved.flatMap(p => describeAuditRow(p as unknown as Record<string, unknown>).raw);
		rows.push({
			key: `permission:${key}:${st.pending[0]?.line_no ?? last?.line_no ?? 0}`,
			ts: num(last?.ts) ?? num(st.pending[0]?.ts),
			source: 'permission',
			kind: pendingOnly
				? 'permission.pending'
				: str(last?.kind) || 'permission.resolved',
			title: pendingOnly
				? '等待用户授权'
				: blocked
					? '权限层挡住该工具'
					: allowed
						? '授权已通过'
						: '授权结果未记录',
			subject: key,
			statusText: [
				`工具 ${toolName}`,
				str(last?.matched_rule) || str(st.pending[0]?.matched_rule)
					? `规则 ${str(last?.matched_rule) || str(st.pending[0]?.matched_rule)}`
					: '',
				outcome
					? `结果 ${permissionOutcomeLabel(outcome)}`
					: pendingOnly
						? '未结束：仍在等待，不代表卡死'
						: NO_OUTCOME_TEXT,
			]
				.filter(Boolean)
				.join(' · '),
			tone: pendingOnly ? 'waiting' : blocked ? 'warn' : recorded ? 'ok' : 'neutral',
			attemptText: '',
			durationMs:
				st.pending[0]?.ts != null && last?.ts != null
					? (toMs(last.ts) ?? 0) - (toMs(st.pending[0].ts) ?? 0)
					: null,
			costCny: null,
			hasUsage: false,
			boundary: 'tool_permission',
			lineNo: last?.line_no ?? st.pending[0]?.line_no ?? null,
			evidence: [
				...st.pending.map(p => ({source: 'audit', locator: '', ref_id: p.line_no ? `L${p.line_no}` : '', detail: p.kind})),
				...st.resolved.map(p => ({source: 'audit', locator: '', ref_id: p.line_no ? `L${p.line_no}` : '', detail: p.kind})),
			],
			rawFields,
		});
	}

	// 4) 后台任务：合法长任务与失败分开显示。
	for (const job of detail.jobs) {
		const status = str(job.status);
		const active = status === 'running' || status === 'stopping';
		const failedJob = status === 'failed' || status === 'killed';
		const startedMs = toMs(num(job.started_at));
		const finishedMs = toMs(num(job.finished_at));
		rows.push({
			key: `job:${str(job.job_id) || String(rows.length)}`,
			ts: num(job.finished_at) ?? num(job.started_at),
			source: 'job',
			kind: 'job',
			title: active
				? '后台任务运行中'
				: status === 'succeeded'
					? '后台任务已完成'
					: failedJob
						? '后台任务终止于错误'
						: `后台任务 ${status || DASH}`,
			subject: str(job.job_id),
			statusText: [str(job.label) || str(job.kind) || DASH, str(job.detail)]
				.filter(Boolean)
				.join(' · '),
			tone: active ? 'active' : failedJob ? 'fail' : 'neutral',
			attemptText: '',
			durationMs:
				startedMs != null && finishedMs != null && finishedMs >= startedMs
					? finishedMs - startedMs
					: null,
			costCny: null,
			hasUsage: false,
			boundary: 'background_job',
			lineNo: null,
			evidence: [],
			rawFields: [],
		});
	}

	// 5) 其余审计事件：只补前三类没覆盖的（按 line_no 去重，不重复记账）。
	const coveredLines = new Set<number>();
	for (const r of rows) if (r.lineNo != null) coveredLines.add(r.lineNo);
	for (const e of detail.events) {
		if (coveredLines.has(e.line_no)) continue;
		if (
			e.kind.startsWith('model.') ||
			e.kind === 'llm.failure' ||
			e.kind.startsWith('tool.') ||
			e.kind.startsWith('permission.')
		) {
			continue;
		}
		const described = describeAuditRow(e.row);
		rows.push({
			key: `event:${e.seq}:${e.line_no}`,
			ts: e.ts,
			source: 'event',
			kind: e.kind,
			// 没有中文动作词的审计类型不照抄机器名，原文在展开区的「事件类型」里仍可见。
			title: KIND_LABEL[e.kind] ?? '审计记录（未收录类型）',
			subject: e.turn_id || e.session_id,
			statusText: described.shown.join(' · '),
			tone: 'neutral',
			attemptText: '',
			durationMs: null,
			costCny: null,
			hasUsage: false,
			boundary: '',
			lineNo: e.line_no,
			evidence: [e.evidence],
			rawFields: described.raw,
		});
	}

	rows.sort((a, b) => {
		const ta = a.ts ?? 0;
		const tb = b.ts ?? 0;
		if (ta !== tb) return ta - tb;
		return (a.lineNo ?? 0) - (b.lineNo ?? 0);
	});
	return rows;
}

// ---------------------------------------------------------------------------
// 用量表（逐 attempt）
// ---------------------------------------------------------------------------

export type AttemptUsageRow = {
	key: string;
	requestId: string;
	attempt: number | null;
	model: string;
	provider: string;
	finished: boolean;
	failed: boolean;
	/** 该尝试的时间（优先用量账，其次审计事件）。 */
	ts: number | null;
	inputHit: number | null;
	inputMiss: number | null;
	output: number | null;
	costCny: number | null;
	costSource: string;
	/** 该尝试有没有用量账（false → 费用未知）。 */
	hasUsage: boolean;
	lineNo: number | null;
};

export function buildAttemptUsage(detail: DiagRunDetail): AttemptUsageRow[] {
	const out: AttemptUsageRow[] = [];
	for (const mr of detail.model_requests) {
		for (const group of groupAttempts(mr)) {
			const first = group[0]!;
			const last = group[group.length - 1]!;
			const finished = group.some(a => a.kind === 'model.finished' && !attemptFailed(a));
			const failed = group.some(attemptFailed);
			const usage = usageOf(mr, first.attempt);
			out.push({
				key: `${mr.model_request_id}#${first.attempt ?? 'x'}`,
				requestId: mr.model_request_id,
				attempt: first.attempt,
				model: mr.model || (usage?.model ?? ''),
				provider: mr.provider || (usage?.vendor ?? ''),
				finished,
				failed,
				ts: usage?.ts ?? last.ts ?? first.ts,
				inputHit: usage ? usage.cache_hit : null,
				inputMiss: usage ? usage.cache_miss : null,
				output: usage ? usage.output : null,
				costCny: usage ? usage.cost_cny : null,
				costSource: usage?.cost_source ?? '',
				hasUsage: usage != null,
				lineNo: last.line_no ?? first.line_no,
			});
		}
	}
	return out;
}

/**
 * 估算合计措辞：无依据 / 有未知尝试时绝不给出一个看起来确定的 ¥ 数字。
 */
export function estimatedTotalLabel(
	summary: DiagRunDetail['usage_summary'],
): string {
	if (!summary) return '费用未知：未取回用量汇总';
	const unknown = summary.unknown_cost_attempts;
	if (summary.cost_basis === '无可依据的用量' || summary.estimated_total_cny == null) {
		return unknown > 0
			? `费用未知（${unknown} 次已结束尝试没有用量账，未按 0 计入）`
			: '费用未知：无可依据的用量';
	}
	const total = fmtCostCny(summary.estimated_total_cny);
	return unknown > 0
		? `${total}（另有 ${unknown} 次已结束尝试费用未知，未按 0 计入）`
		: total;
}

/** 责任方标签：判"模型的错"的门槛比引擎高，措辞必须能体现这种不对称。 */
export const PARTY_LABEL: Record<string, string> = {
	engine: '引擎侧',
	model: '模型侧',
	environment: '外部环境',
	mixed: '混合',
	undetermined: '无法归因',
};

export const PARTY_TONE: Record<string, 'fail' | 'warn' | 'neutral' | 'unknown'> = {
	engine: 'fail',
	model: 'warn',
	environment: 'neutral',
	mixed: 'fail',
	undetermined: 'unknown',
};

/** 约束是否进入模型实际收到的内容。 */
export const SHOWN_LABEL: Record<string, string> = {
	shown: '已送达模型',
	not_shown: '未送达',
	// 后端 fault_split.py 在这条路上发的是 folded_out：丢了哪一级已定位到折叠，
	// 缺这一条时徽章会照抄机器名（约束：folded_out）。
	folded_out: '被折叠移出投影（未送达）',
	unprovable: '无法证明是否送达',
	no_obligation: '没有声明的约束',
};

export const COST_BASIS_LABEL = '按 usage 估算（非账单实付）';

/** 采集开关的产品措辞：只写文件，不改变模型可见内容。 */
export const CAPTURE_NOTE =
	'开启后只把适配器最终请求体落盘到本机，不改变模型可见的消息、工具执行结果或本轮任何输出。';

/** 列表为空的单一措辞：与「尾窗截断」徽章不能同时出现，两句必须同口径。 */
export const NO_RUNS_IN_TAIL_TEXT =
	'该会话在审计尾窗内没有轮次记录。这不代表没有运行过轮次——尾窗之外的轮次不在本页范围内。';

/** 后端报的列表扫描口径（结构类型，与 api/diagnostics 的 coverage 字段对齐）。 */
export type DiagRunsCoverage = {
	present: boolean;
	truncated: boolean;
	complete: boolean;
	widened: boolean;
	rows_scanned: number;
	note: string;
} | null;

/**
 * 「没有可诊断的运行」这句话有三种完全不同的事实，必须分开说：
 * 读完整份确实没有 / 尾窗没盖到 / 审计文件根本不存在。
 * 后端扩窗重读之后第一种才是常态，继续念尾窗那句就是把采集范围说成事实。
 * 口径缺失（旧后端、字段没带）时保守处理：不冒充"读完了"。
 */
export function noRunsText(coverage: DiagRunsCoverage): string {
	if (!coverage) return NO_RUNS_IN_TAIL_TEXT;
	if (!coverage.present) return '审计文件不存在：本页列不出任何轮次。这不代表没有运行过轮次。';
	if (coverage.truncated) return NO_RUNS_IN_TAIL_TEXT;
	return `已读完审计（${coverage.rows_scanned} 行），该会话没有留下任何轮次记录。`;
}

/**
 * 计数措辞：账本窗口根本没出现在本次响应里时，0 条是"没看"，不是"没有"。
 * 窗口读了但不完整时必须继续带截断标记，不得伪装成确切计数。
 */
export function ledgerCountText(
	window: DiagWindow | undefined,
	count: number,
	unit: string,
	windowLabel: string,
): string {
	if (!window) return `未取回（本次响应没有${windowLabel}窗口）`;
	const base = `${count} ${unit}`;
	return window.complete ? base : `${base}（窗口未读全，实际不少于此数）`;
}

/** 投影 manifest 的条数措辞：working 只留会话最后一份，未必属于本轮。
 *
 * 采集器在每一条 projection 上带 `scope: "last_only"`（python/diagnostics/collect.py）；
 * 后端没标这个字段时不凭空加限制句 —— 说了没有的证据就是假话。
 */
export function projectionManifestText(
	projections: Record<string, unknown>[],
	window: DiagWindow | undefined,
): string {
	const base = ledgerCountText(window, projections.length, '份', '投影');
	if (!projections.some(p => String(p['scope'] ?? '') === 'last_only')) return base;
	return `${base}；working 只留存会话最后一份，未必属于本轮`;
}

/** 深链没落进审计尾窗时的措辞：说清"没有顶替"，不假装这是用户点的那一击的结论。 */
export function linkMismatchText(
	kind: 'tool' | 'turn' | 'replaced',
	value: string,
	alt?: string,
): string {
	if (kind === 'tool') {
		return `工具调用 ${value || DASH} 不在当前审计尾窗里：本页没有自动改选其他轮次，下方结论不对应这一次点击。`;
	}
	if (kind === 'replaced') {
		return `轮次 ${value || DASH} 已滑出当前审计尾窗：下面显示的是列表里最新一轮 ${alt || DASH} 的结论，不是你上次点的那一轮。`;
	}
	return `轮次 ${value || DASH} 不在当前审计尾窗里：本页没有自动改选其他轮次。`;
}

/** 刷新失败但底下仍有数据时的措辞：错误不遮数据。 */
export const STALE_REFRESH_SUFFIX = '以下为上一次成功取回的内容，可能已不是最新状态。';

/** 证据引用 → 可复制文本（source + ref_id + locator）。 */
export function evidenceText(e: DiagEvidenceRef): string {
	return [e.source, e.ref_id, e.locator, e.detail].filter(Boolean).join(' | ');
}

/**
 * 一条原因的证据摘要：界面原来只投出 label 与"能证明/不能证明"，
 * 后端已经带过来的原始记录指针被丢掉（因果链那一段是渲染的）。
 * 逐条铺开会和因果链重复，这里只给一行"指得到哪里"，没有证据时返回空串。
 */
export function causeEvidenceSummary(items: DiagEvidenceRef[] | undefined, total?: number): string {
	const shown = items ?? [];
	const first = shown.find(e => e && (e.source || e.ref_id || e.locator || e.detail));
	if (!first) return '';
	const head =
		[first.source, first.ref_id].filter(Boolean).join(' ') ||
		(first.locator ? (first.locator.split(/[\\/]/).pop() ?? '') : '');
	if (!head) return '';
	const n = typeof total === 'number' && total > 0 ? total : shown.length;
	return `证据：${head}${n > 1 ? ` 等 ${n} 条` : ''}`;
}

// ---------------------------------------------------------------------------
// 运行列表的边界覆盖
// ---------------------------------------------------------------------------

/** 与 python/diagnostics/collect.py::BOUNDARIES 同序同名的展示表（未知名字回落原名）。 */
export const BOUNDARY_ORDER: ReadonlyArray<{name: string; label: string}> = [
	{name: 'user_request', label: '用户请求 / 接收'},
	{name: 'resume_schedule', label: '会话恢复与调度'},
	{name: 'instruction_context', label: '指令与上下文'},
	{name: 'wsc_fold', label: 'WSC 折叠'},
	{name: 'adapter', label: '适配器最终请求'},
	{name: 'model_request', label: '模型请求与响应'},
	{name: 'tool_permission', label: '工具与权限'},
	{name: 'background_job', label: '后台任务'},
	{name: 'file_verifier', label: '文件与验收'},
	{name: 'sse_gui', label: 'SSE / 界面'},
];

export type RunBoundaryCoverage = {
	name: string;
	label: string;
	present: boolean;
};

export function boundaryCoverageOfRun(run: {boundaries: string[]}): RunBoundaryCoverage[] {
	const known = new Set<string>(run.boundaries ?? []);
	const out: RunBoundaryCoverage[] = BOUNDARY_ORDER.map(b => ({
		name: b.name,
		label: b.label,
		present: known.has(b.name),
	}));
	// 后端若新增边界名，原样追加，不静默丢弃。
	for (const extra of known) {
		if (!BOUNDARY_ORDER.some(b => b.name === extra)) {
			out.push({name: extra, label: extra, present: true});
		}
	}
	return out;
}

/** 边界名 → 中文标签：优先用后端本轮返回的 label，其次展示表，最后回落原名。 */
export function boundaryLabelOf(
	detail: Pick<DiagRunDetail, 'boundaries'>,
	name: string,
): string {
	if (!name) return DASH;
	const fromRun = detail.boundaries.find(b => b.name === name)?.label;
	if (fromRun) return fromRun;
	return BOUNDARY_ORDER.find(b => b.name === name)?.label ?? name;
}

// ---------------------------------------------------------------------------
// 静默刷新与手工翻页的合并
// ---------------------------------------------------------------------------

/**
 * 20 秒静默轮询拿回来的永远是第 0 页；用户手工「继续加载」翻出来的后续页不能被
 * 它换掉（否则读到 600 条时时间线会突然退回 200 条，游标也倒回去）。
 * 首页与后续页按审计行号合并，行号是审计文件内的唯一键。
 */
export function mergeDetailPreservingLoadedPages(
	cur: DiagRunDetail,
	fresh: DiagRunDetail,
): DiagRunDetail {
	// 本轮响应已经覆盖全部事件时，它就是权威全集，不需要保留旧页。
	if (fresh.events_complete || fresh.event_total <= fresh.events.length) return fresh;
	// 只有"本地比这一页长"才需要合并，其余情况直接用新页。
	if (cur.events.length <= fresh.events.length) return fresh;
	const seen = new Set<number>();
	for (const e of fresh.events) seen.add(e.line_no);
	const extras = cur.events.filter(e => !seen.has(e.line_no));
	if (!extras.length) return fresh;
	return {
		...fresh,
		events: [...fresh.events, ...extras].sort((a, b) => a.line_no - b.line_no),
		event_offset: Math.max(cur.event_offset, fresh.event_offset),
		event_limit: fresh.event_limit || cur.event_limit,
	};
}
