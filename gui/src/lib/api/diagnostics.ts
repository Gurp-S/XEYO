/**
 * diagnostics.ts — XEYO 诊断中心 API 客户端（docs/xeyo-diagnostics-design-2026-09-24.md）。
 *
 * 读取为主的域：运行列表 / 运行详情 / 结论 / 定位链 / 固定证据 / 采集开关 / 实验。
 *
 * 措辞纪律（产品要求，不是装饰）：
 * - 缺用量 ≠ 0 元：`cost_cny` 缺失一律解析成 null，渲染层显示「费用未知」。
 * - 无证据 ≠ 无异常：`coverage_note` / `gaps` / `complete=false` 必须原样带上前端。
 * - 不合成概率、不合成总分：本模块只搬运后端字段，不做任何打分。
 * 因此这里所有解析函数遵循「宁缺勿补」：字段不在就是 null/空串，绝不填默认值。
 */
import {apiUrl} from '@/lib/apiBase';
import {formatErrorDetail} from './core';

// ---------------------------------------------------------------------------
// 防御式读取器（缺字段留 null / 空串，不补 0）
// ---------------------------------------------------------------------------

function s(v: unknown): string {
	if (typeof v === 'string') return v;
	if (typeof v === 'number' || typeof v === 'boolean') return String(v);
	return '';
}

function n(v: unknown): number | null {
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	if (typeof v === 'string' && v.trim()) {
		const f = Number(v);
		return Number.isFinite(f) ? f : null;
	}
	return null;
}

function b(v: unknown): boolean {
	return v === true;
}

function tri(v: unknown): boolean | null {
	if (typeof v === 'boolean') return v;
	return null;
}

function rec(v: unknown): Record<string, unknown> {
	return v && typeof v === 'object' && !Array.isArray(v)
		? (v as Record<string, unknown>)
		: {};
}

function arr(v: unknown): unknown[] {
	return Array.isArray(v) ? v : [];
}

// ---------------------------------------------------------------------------
// 类型（与 python/diagnostics/* 的 to_dict 对齐）
// ---------------------------------------------------------------------------

export type DiagEvidenceRef = {
	source: string;
	locator: string;
	ref_id: string;
	detail: string;
};

export type DiagCoverageEntry = {
	state: string; // full | partial | absent | redacted | expired | not_captured
	complete: boolean;
	rows: number;
	locator: string;
	note: string;
};

export type DiagBoundary = {
	name: string;
	label: string;
	present: boolean;
	evidence: DiagEvidenceRef[];
	evidence_count: number;
	notes: string[];
};

export type DiagRunListItem = {
	turn_id: string;
	first_ts: number | null;
	last_ts: number | null;
	event_kinds: string[];
	boundaries: string[];
	model_request_count: number;
	tool_call_count: number;
	/** 本轮出现过的 tool_use.id；失败步骤「查看诊断」靠它反查轮次。 */
	tool_use_ids: string[];
	audit_lines: [number, number];
	coverage_note: string;
};

export type DiagRunsResult = {
	schema_version: number | null;
	ruleset_version: number | null;
	session_id: string;
	runs: DiagRunListItem[];
	count: number;
	limit: number | null;
	complete: boolean;
	/** 列表口径的扫描覆盖情况；runs 为空时它是唯一能说清"为什么是空"的东西。
	 *  null = 后端没报这个口径（旧版或字段缺失），不得当成"读完了"或"没读完"。 */
	coverage: {
		present: boolean;
		truncated: boolean;
		complete: boolean;
		widened: boolean;
		rows_scanned: number;
		note: string;
	} | null;
	store_root: string;
};

export type DiagAttempt = {
	attempt: number | null;
	kind: string;
	ts: number | null;
	status: string;
	error_code: string;
	http_status: number | null;
	duration_ms: number | null;
	error_kind: string;
	line_no: number | null;
};

/** usage 账本的一行（缺字段一律 null；cost_cny 缺失 = 费用未知，不是 0）。 */
export type DiagUsageRow = {
	request_id: string;
	attempt: number | null;
	attempt_key: string;
	kind: string;
	model: string;
	vendor: string;
	provider: string;
	ts: number | null;
	cache_hit: number | null;
	cache_miss: number | null;
	output: number | null;
	tokens: number | null;
	cost_cny: number | null;
	cost_source: string;
	line_no: number | null;
	locator: string;
};

export type DiagModelRequest = {
	model_request_id: string;
	provider: string;
	model: string;
	turn_id: string;
	projection_id: string;
	attempts: DiagAttempt[];
	attempt_keys: string[];
	tool_use_ids: string[];
	usage_by_attempt: Record<string, DiagUsageRow>;
	capture: Record<string, unknown> | null;
	evidence: DiagEvidenceRef[];
};

export type DiagToolCall = {
	tool_use_id: string;
	tool_name: string;
	turn_id: string;
	model_request_id: string;
	projection_id: string;
	action_id: string;
	started: Record<string, unknown> | null;
	finished: Record<string, unknown> | null;
	paired: boolean;
	approval_ids: string[];
	result_message_id: string;
	is_error: boolean | null;
	error_kind: string;
	evidence: DiagEvidenceRef[];
};

export type DiagPermission = {
	request_id: string;
	kind: string;
	tool_name: string;
	matched_rule: string;
	approved: boolean | null;
	outcome: string;
	user_choice: string;
	actor: string;
	ts: number | null;
	line_no: number | null;
	tool_use_id: string;
	model_request_id: string;
};

export type DiagEvent = {
	seq: number;
	line_no: number;
	kind: string;
	ts: number | null;
	session_id: string;
	turn_id: string;
	model_request_id: string;
	attempt: number | null;
	tool_use_id: string;
	approval_id: string;
	action_id: string;
	projection_id: string;
	row: Record<string, unknown>;
	evidence: DiagEvidenceRef;
};

export type DiagFinding = {
	rule_id: string;
	rule_version: number | null;
	phenomenon: string;
	boundary: string;
	component: string;
	status: string; // confirmed_fault | suspected_cause | unknown
	evidence: DiagEvidenceRef[];
	impact: string;
	coverage_gap: string;
	allowed_conclusion: string;
};

export type DiagAttribution = {
	first_anomaly_boundary: string;
	first_anomaly_label: string;
	last_evidenced_boundary: string;
	last_evidenced_label: string;
	confirmed_count: number;
	suspected_count: number;
	unknown_count: number;
	attributed: boolean;
	statement: string;
};

export type DiagUsageSummary = {
	finished_attempts: number;
	priced_attempts: number;
	unknown_cost_attempts: number;
	unknown_cost_keys: string[];
	estimated_total_cny: number | null;
	cost_basis: string;
	cost_sources: string[];
	unlinked_usage_rows: number;
	statement: string;
};

export type DiagGap = {boundary: string; reason: string; detail: string; scope: string};

export type DiagWindow = {
	source: string;
	locator: string;
	complete: boolean;
	rows_scanned: number;
	rows_matched: number;
	bytes_read: number;
	note: string;
};

export type DiagPin = {
	pin_id: string;
	kind: string;
	session_id: string;
	turn_id: string;
	created_at: number | null;
	note: string;
	expected: string;
	name: string;
	command: string;
	exit_code: number | null;
	output_ref: string;
	verifier_version: string;
	evidence: DiagEvidenceRef[];
	pinned_files: string[];
	locator: string;
};

export type DiagRunDetail = {
	schema_version: number | null;
	session_id: string;
	turn_id: string;
	generated_at: number | null;
	coverage: Record<string, DiagCoverageEntry>;
	boundaries: DiagBoundary[];
	identity: {
		model_request_ids: string[];
		attempt_keys: string[];
		tool_use_ids: string[];
		approval_ids: string[];
		projection_ids: string[];
	};
	model_requests: DiagModelRequest[];
	tool_calls: DiagToolCall[];
	permissions: DiagPermission[];
	projections: Record<string, unknown>[];
	usage: DiagUsageRow[];
	folds: Record<string, unknown>[];
	wire_drops: Record<string, unknown>[];
	captures: Record<string, unknown>[];
	jobs: Record<string, unknown>[];
	pins: DiagPin[];
	working: Record<string, unknown>;
	windows: DiagWindow[];
	gaps: DiagGap[];
	notes: string[];
	events: DiagEvent[];
	event_total: number;
	event_offset: number;
	event_limit: number;
	events_complete: boolean;
	next_event_cursor: string;
	findings: DiagFinding[];
	attribution: DiagAttribution | null;
	usage_summary: DiagUsageSummary | null;
	fault: DiagFault | null;
	versions: {commit: string; branch: string; worktree_state: string; probed_at: number | null};
};

export type DiagFactStage = {
	stage: string;
	label: string;
	state: string; // found | absent | not_recorded | not_captured | unreadable
	evidence: DiagEvidenceRef[];
	note: string;
};

export type DiagFactTrace = {
	needle: string;
	session_id: string;
	turn_id: string;
	stages: DiagFactStage[];
	verdict: string;
	statement: string;
	unprovable_stages: string[];
	caveat: string;
};

export type DiagMessageBody = {
	ok: boolean;
	message_id: string;
	role: string;
	content: string;
	truncated: boolean;
	body_state: string;
	content_hash: string;
	locator: string;
	error: string;
};

export type DiagFaultStep = {
	order: number;
	boundary: string;
	fact: string;
	party: string;
	party_label: string;
	evidence: DiagEvidenceRef[];
};

/** 一条失败原因：与归属分开——原因可以不属于任何一方。 */
export type DiagCause = {
	code: string;
	label: string;
	party: string;
	proves: string;
	does_not_prove: string;
	detail_kind?: string;
	evidence: DiagEvidenceRef[];
	/** 后端只带前 6 条指针，总数另说：否则界面写"等 6 条"而实际有 20 条。
	 *  旧后端不报这个字段时保持缺位——截断列表的长度不是总数，补成 0 或长度都是凭空认账。 */
	evidence_total?: number | null;
};

/** 责任划分：后端判据不对称——判"模型的错"必须有约束送达证据。 */
export type DiagFault = {
	responsibility: string;
	responsibility_label: string;
	why: string;
	primary_cause: string;
	primary_cause_label: string;
	cause_statement: string;
	causes: DiagCause[];
	task_outcome: string;
	task_outcome_label: string;
	obligation: {source: string; locator: string; ref_id: string; excerpt: string};
	shown_to_model: string;
	shown_to_model_note: string;
	engine_confirmed: number;
	environment_confirmed: number;
	transport_gap: boolean;
	chain: DiagFaultStep[];
	missing_evidence: string[];
	not_claimed: string[];
};

export type DiagCaptureState = {
	session_id: string;
	enabled: boolean;
	disk_bytes: number | null;
	quota_bytes: number | null;
	locator: string;
};

/** 实验层由并行工作流实现；本模块只透传，不声明字段。 */
export type DiagRawResult =
	| {ok: true; status: number; data: unknown}
	| {ok: false; status: number; error: string};

// ---------------------------------------------------------------------------
// 解析器
// ---------------------------------------------------------------------------

function parseEvidence(v: unknown): DiagEvidenceRef {
	const o = rec(v);
	return {
		source: s(o.source),
		locator: s(o.locator),
		ref_id: s(o.ref_id),
		detail: s(o.detail),
	};
}

function parseEvidenceList(v: unknown): DiagEvidenceRef[] {
	return arr(v).map(parseEvidence);
}

function parseUsageRow(v: unknown): DiagUsageRow {
	const o = rec(v);
	return {
		request_id: s(o.request_id),
		attempt: n(o.attempt),
		attempt_key: s(o.attempt_key),
		kind: s(o.kind),
		model: s(o.model),
		vendor: s(o.vendor),
		provider: s(o.provider),
		ts: n(o.ts),
		cache_hit: n(o.cache_hit),
		cache_miss: n(o.cache_miss),
		output: n(o.output),
		tokens: n(o.tokens),
		// 关键：后端没写 cost_cny 时保持 null —— 渲染层据此显示「费用未知」。
		cost_cny: n(o.cost_cny),
		cost_source: s(o.cost_source),
		line_no: n(o.line_no),
		locator: s(o.locator),
	};
}

function parseAttempt(v: unknown): DiagAttempt {
	const o = rec(v);
	return {
		attempt: n(o.attempt),
		kind: s(o.kind),
		ts: n(o.ts),
		status: s(o.status),
		error_code: s(o.error_code),
		http_status: n(o.http_status),
		duration_ms: n(o.duration_ms),
		error_kind: s(o.error_kind),
		line_no: n(o.line_no),
	};
}

function parseModelRequest(v: unknown): DiagModelRequest {
	const o = rec(v);
	const usageRows: Record<string, DiagUsageRow> = {};
	for (const [k, row] of Object.entries(rec(o.usage_by_attempt))) {
		usageRows[k] = parseUsageRow(row);
	}
	return {
		model_request_id: s(o.model_request_id),
		provider: s(o.provider),
		model: s(o.model),
		turn_id: s(o.turn_id),
		projection_id: s(o.projection_id),
		attempts: arr(o.attempts).map(parseAttempt),
		attempt_keys: arr(o.attempt_keys).map(s),
		tool_use_ids: arr(o.tool_use_ids).map(s),
		usage_by_attempt: usageRows,
		capture: o.capture ? rec(o.capture) : null,
		evidence: parseEvidenceList(o.evidence),
	};
}

function parseToolCall(v: unknown): DiagToolCall {
	const o = rec(v);
	return {
		tool_use_id: s(o.tool_use_id),
		tool_name: s(o.tool_name),
		turn_id: s(o.turn_id),
		model_request_id: s(o.model_request_id),
		projection_id: s(o.projection_id),
		action_id: s(o.action_id),
		started: o.started ? rec(o.started) : null,
		finished: o.finished ? rec(o.finished) : null,
		paired: b(o.paired),
		approval_ids: arr(o.approval_ids).map(s),
		result_message_id: s(o.result_message_id),
		is_error: tri(o.is_error),
		error_kind: s(o.error_kind),
		evidence: parseEvidenceList(o.evidence),
	};
}

function parsePermission(v: unknown): DiagPermission {
	const o = rec(v);
	return {
		request_id: s(o.request_id),
		kind: s(o.kind),
		tool_name: s(o.tool_name),
		matched_rule: s(o.matched_rule),
		approved: tri(o.approved),
		outcome: s(o.outcome),
		user_choice: s(o.user_choice),
		actor: s(o.actor),
		ts: n(o.ts),
		line_no: n(o.line_no),
		tool_use_id: s(o.tool_use_id),
		model_request_id: s(o.model_request_id),
	};
}

function parseEvent(v: unknown): DiagEvent {
	const o = rec(v);
	return {
		seq: n(o.seq) ?? 0,
		line_no: n(o.line_no) ?? 0,
		kind: s(o.kind),
		ts: n(o.ts),
		session_id: s(o.session_id),
		turn_id: s(o.turn_id),
		model_request_id: s(o.model_request_id),
		attempt: n(o.attempt),
		tool_use_id: s(o.tool_use_id),
		approval_id: s(o.approval_id),
		action_id: s(o.action_id),
		projection_id: s(o.projection_id),
		row: rec(o.row),
		evidence: parseEvidence(o.evidence),
	};
}

function parseFinding(v: unknown): DiagFinding {
	const o = rec(v);
	return {
		rule_id: s(o.rule_id),
		rule_version: n(o.rule_version),
		phenomenon: s(o.phenomenon),
		boundary: s(o.boundary),
		component: s(o.component),
		status: s(o.status),
		evidence: parseEvidenceList(o.evidence),
		impact: s(o.impact),
		coverage_gap: s(o.coverage_gap),
		allowed_conclusion: s(o.allowed_conclusion),
	};
}

function parseAttribution(v: unknown): DiagAttribution | null {
	if (!v || typeof v !== 'object') return null;
	const o = rec(v);
	return {
		first_anomaly_boundary: s(o.first_anomaly_boundary),
		first_anomaly_label: s(o.first_anomaly_label),
		last_evidenced_boundary: s(o.last_evidenced_boundary),
		last_evidenced_label: s(o.last_evidenced_label),
		confirmed_count: n(o.confirmed_count) ?? 0,
		suspected_count: n(o.suspected_count) ?? 0,
		unknown_count: n(o.unknown_count) ?? 0,
		attributed: b(o.attributed),
		statement: s(o.statement),
	};
}

function parseUsageSummary(v: unknown): DiagUsageSummary | null {
	if (!v || typeof v !== 'object') return null;
	const o = rec(v);
	return {
		finished_attempts: n(o.finished_attempts) ?? 0,
		priced_attempts: n(o.priced_attempts) ?? 0,
		unknown_cost_attempts: n(o.unknown_cost_attempts) ?? 0,
		unknown_cost_keys: arr(o.unknown_cost_keys).map(s),
		estimated_total_cny: n(o.estimated_total_cny),
		cost_basis: s(o.cost_basis),
		cost_sources: arr(o.cost_sources).map(s),
		unlinked_usage_rows: n(o.unlinked_usage_rows) ?? 0,
		statement: s(o.statement),
	};
}

function parseFault(v: unknown): DiagFault | null {
	if (!v || typeof v !== 'object') return null;
	const o = rec(v);
	const ob = rec(o.obligation);
	return {
		responsibility: s(o.responsibility),
		responsibility_label: s(o.responsibility_label),
		why: s(o.why),
		primary_cause: s(o.primary_cause),
		primary_cause_label: s(o.primary_cause_label),
		cause_statement: s(o.cause_statement),
		causes: arr(o.causes).map(c => {
			const c1 = rec(c);
			return {
				code: s(c1.code),
				label: s(c1.label),
				party: s(c1.party),
				proves: s(c1.proves),
				does_not_prove: s(c1.does_not_prove),
				detail_kind: c1.detail_kind ? s(c1.detail_kind) : undefined,
				evidence: arr(c1.evidence).map(parseEvidence),
				evidence_total: n(c1.evidence_total),
			};
		}),
		task_outcome: s(o.task_outcome),
		task_outcome_label: s(o.task_outcome_label),
		obligation: {
			source: s(ob.source),
			locator: s(ob.locator),
			ref_id: s(ob.ref_id),
			excerpt: s(ob.excerpt),
		},
		shown_to_model: s(o.shown_to_model),
		shown_to_model_note: s(o.shown_to_model_note),
		engine_confirmed: n(o.engine_confirmed) ?? 0,
		environment_confirmed: n(o.environment_confirmed) ?? 0,
		transport_gap: b(o.transport_gap),
		chain: arr(o.chain).map(c => {
			const g = rec(c);
			return {
				order: n(g.order) ?? 0,
				boundary: s(g.boundary),
				fact: s(g.fact),
				party: s(g.party),
				party_label: s(g.party_label),
				evidence: arr(g.evidence).map(parseEvidence),
			};
		}),
		missing_evidence: arr(o.missing_evidence).map(s),
		not_claimed: arr(o.not_claimed).map(s),
	};
}

function parseBoundary(v: unknown): DiagBoundary {
	const o = rec(v);
	return {
		name: s(o.name),
		label: s(o.label),
		present: b(o.present),
		evidence: parseEvidenceList(o.evidence),
		evidence_count: n(o.evidence_count) ?? 0,
		notes: arr(o.notes).map(s),
	};
}

function parseWindow(v: unknown): DiagWindow {
	const o = rec(v);
	return {
		source: s(o.source),
		locator: s(o.locator),
		complete: b(o.complete),
		rows_scanned: n(o.rows_scanned) ?? 0,
		rows_matched: n(o.rows_matched) ?? 0,
		bytes_read: n(o.bytes_read) ?? 0,
		note: s(o.note),
	};
}

function parsePin(v: unknown): DiagPin {
	const o = rec(v);
	return {
		pin_id: s(o.pin_id),
		kind: s(o.kind),
		session_id: s(o.session_id),
		turn_id: s(o.turn_id),
		created_at: n(o.created_at),
		note: s(o.note),
		expected: s(o.expected),
		name: s(o.name),
		command: s(o.command),
		exit_code: n(o.exit_code),
		output_ref: s(o.output_ref),
		verifier_version: s(o.verifier_version),
		evidence: parseEvidenceList(o.evidence),
		pinned_files: arr(o.pinned_files).map(s),
		locator: s(o.locator),
	};
}

function parseCoverage(v: unknown): Record<string, DiagCoverageEntry> {
	const out: Record<string, DiagCoverageEntry> = {};
	for (const [k, raw] of Object.entries(rec(v))) {
		const o = rec(raw);
		out[k] = {
			state: s(o.state),
			complete: b(o.complete),
			rows: n(o.rows) ?? 0,
			locator: s(o.locator),
			note: s(o.note),
		};
	}
	return out;
}

function parseIdentity(v: unknown) {
	const o = rec(v);
	return {
		model_request_ids: arr(o.model_request_ids).map(s),
		attempt_keys: arr(o.attempt_keys).map(s),
		tool_use_ids: arr(o.tool_use_ids).map(s),
		approval_ids: arr(o.approval_ids).map(s),
		projection_ids: arr(o.projection_ids).map(s),
	};
}

export function parseRunDetail(raw: unknown): DiagRunDetail {
	const o = rec(raw);
	return {
		schema_version: n(o.schema_version),
		session_id: s(o.session_id),
		turn_id: s(o.turn_id),
		generated_at: n(o.generated_at),
		coverage: parseCoverage(o.coverage),
		boundaries: arr(o.boundaries).map(parseBoundary),
		identity: parseIdentity(o.identity),
		model_requests: arr(o.model_requests).map(parseModelRequest),
		tool_calls: arr(o.tool_calls).map(parseToolCall),
		permissions: arr(o.permissions).map(parsePermission),
		projections: arr(o.projections).map(rec),
		usage: arr(o.usage).map(parseUsageRow),
		folds: arr(o.folds).map(rec),
		wire_drops: arr(o.wire_drops).map(rec),
		captures: arr(o.captures).map(rec),
		jobs: arr(o.jobs).map(rec),
		pins: arr(o.pins).map(parsePin),
		working: rec(o.working),
		windows: arr(o.windows).map(parseWindow),
		gaps: arr(o.gaps).map(v => {
			const g = rec(v);
			// 缺 scope（旧后端）时按 per_turn 处理：宁可逐轮照旧显示，也不误当会话级折叠掉。
			const scope = s(g.scope) || 'per_turn';
			return {boundary: s(g.boundary), reason: s(g.reason), detail: s(g.detail), scope};
		}),
		notes: arr(o.notes).map(s),
		events: arr(o.events).map(parseEvent),
		event_total: n(o.event_total) ?? 0,
		event_offset: n(o.event_offset) ?? 0,
		event_limit: n(o.event_limit) ?? 0,
		events_complete: b(o.events_complete),
		next_event_cursor: s(o.next_event_cursor),
		findings: arr(o.findings).map(parseFinding),
		attribution: parseAttribution(o.attribution),
		usage_summary: parseUsageSummary(o.usage_summary),
		fault: parseFault(o.fault),
		versions: (() => {
			const v = rec(o.versions);
			return {
				commit: s(v.commit),
				branch: s(v.branch),
				worktree_state: s(v.worktree_state),
				probed_at: n(v.probed_at),
			};
		})(),
	};
}

export function parseRunsResult(raw: unknown): DiagRunsResult {
	const o = rec(raw);
	return {
		schema_version: n(o.schema_version),
		ruleset_version: n(o.ruleset_version),
		session_id: s(o.session_id),
		runs: arr(o.runs).map(v => {
			const r = rec(v);
			const lines = arr(r.audit_lines).map(n);
			return {
				turn_id: s(r.turn_id),
				first_ts: n(r.first_ts),
				last_ts: n(r.last_ts),
				event_kinds: arr(r.event_kinds).map(s),
				boundaries: arr(r.boundaries).map(s),
				model_request_count: n(r.model_request_count) ?? 0,
				tool_call_count: n(r.tool_call_count) ?? 0,
				tool_use_ids: arr(r.tool_use_ids).map(s),
				audit_lines: [lines[0] ?? 0, lines[1] ?? 0],
				coverage_note: s(r.coverage_note),
			};
		}),
		count: n(o.count) ?? 0,
		limit: n(o.limit),
		complete: b(o.complete),
		// 后端没带 coverage 时留 null（= 口径未知），不许塌成"读完了/没读完"两种断言之一。
		coverage:
			o.coverage === undefined || o.coverage === null
				? null
				: (() => {
						const cov = rec(o.coverage);
						return {
							present: b(cov.present),
							truncated: b(cov.truncated),
							complete: b(cov.complete),
							widened: b(cov.widened),
							rows_scanned: n(cov.rows_scanned) ?? 0,
							note: s(cov.note),
						};
					})(),
		store_root: s(o.store_root),
	};
}

// ---------------------------------------------------------------------------
// 请求
// ---------------------------------------------------------------------------

const LONG_TIMEOUT_MS = 60_000;
const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * 本地后端不可达时的唯一措辞（产品要求：不得把 `Failed to fetch` 之类的浏览器
 * 原文投进注意力）。调用方拿到的是 Error.message 已是中文的错误，界面配 重试 按钮。
 */
export const OFFLINE_ERROR_MESSAGE = '无法连接本地后端（请确认 server 已启动）';

/** 取消不是故障：调用方按请求身份丢弃即可，不进错误态。 */
export class DiagRequestCancelled extends Error {
	constructor() {
		super('请求已取消');
		this.name = 'DiagRequestCancelled';
	}
}

export function isDiagRequestCancelled(err: unknown): boolean {
	return err instanceof DiagRequestCancelled;
}

/** 把 core 层 / 浏览器抛出的未知失败收窄成中文事实。 */
function describeTransportFailure(err: unknown, timeoutMs?: number): Error {
	const name =
		err && typeof err === 'object' ? String((err as {name?: unknown}).name ?? '') : '';
	const message =
		err && typeof err === 'object'
			? String((err as {message?: unknown}).message ?? '')
			: typeof err === 'string'
				? err
				: '';
	if (err instanceof DiagRequestCancelled) return err;
	// DOMException 不一定是 Error 子类，因此按 name / message 判定而不是 instanceof。
	if (name === 'AbortError') {
		return timeoutMs == null
			? new DiagRequestCancelled()
			: new Error(`请求超时：${Math.round(timeoutMs / 1000)} 秒内未收到服务器响应`);
	}
	if (message.startsWith('请求超时')) return err as Error;
	if (
		name === 'TypeError' ||
		/failed to fetch|networkerror|load failed|err_connection|err_network/i.test(message)
	) {
		return new Error(OFFLINE_ERROR_MESSAGE);
	}
	return message ? new Error(message) : new Error(OFFLINE_ERROR_MESSAGE);
}

/**
 * 诊断域自己的 fetch：带外部 AbortSignal（core.fetchWithTimeout 会覆盖调用方 signal，
 * 因此不能借用），并统一把非 Response / 网络失败换成中文错误。
 * 60 秒的 collect_run 全尾扫描会占住浏览器对同一 host 的连接槽，切轮次时必须能中止。
 */
async function send(
	path: string,
	init?: RequestInit,
	timeoutMs?: number,
	signal?: AbortSignal,
): Promise<Response> {
	const limit = timeoutMs ?? DEFAULT_TIMEOUT_MS;
	const controller = new AbortController();
	let timedOut = false;
	const timer = setTimeout(() => {
		timedOut = true;
		controller.abort();
	}, limit);
	const forward = () => controller.abort();
	if (signal) {
		if (signal.aborted) forward();
		else signal.addEventListener('abort', forward, {once: true});
	}
	try {
		const res = await fetch(apiUrl(path), {
			cache: 'no-store',
			...init,
			signal: controller.signal,
		});
		if (!res || typeof (res as {json?: unknown}).json !== 'function') {
			throw new Error(OFFLINE_ERROR_MESSAGE);
		}
		return res;
	} catch (err) {
		if (timedOut) {
			throw new Error(`请求超时：${Math.round(limit / 1000)} 秒内未收到服务器响应`);
		}
		if (signal?.aborted) throw new DiagRequestCancelled();
		throw describeTransportFailure(err);
	} finally {
		clearTimeout(timer);
		signal?.removeEventListener('abort', forward);
	}
}

/** HTTP 状态 + 响应体 → 中文 Error（非 2xx 一律进错误态）。 */
async function failureOf(res: Response): Promise<Error> {
	let payload: unknown = null;
	try {
		payload = await res.json();
	} catch {
		/* 非 JSON 错误响应由状态码兜底 */
	}
	if (isDefaultNotFound(payload, res.status)) return new Error(DIAG_MODULE_MISSING_MESSAGE);
	return new Error(formatErrorDetail(payload, res.status));
}

/** 诊断路由自己从不回 404（见 server/routers/diagnostics.py），所以框架默认的
 *  `Not Found` 只有一个解释：这个后端压根没挂诊断模块。桌面版打包的引擎快照早于
 *  诊断层，此时把英文原文投给读者，既看不懂也说不出该做什么。 */
export const DIAG_MODULE_MISSING_MESSAGE =
	'这个后端没有诊断模块：请改用 dev 后端（py -3.11 -m cli serve），或重新打包引擎后再看诊断中心';

function isDefaultNotFound(payload: unknown, status: number): boolean {
	if (status !== 404) return false;
	if (payload == null) return true;
	if (typeof payload === 'string') return payload.trim() === '' || payload.trim() === 'Not Found';
	if (typeof payload !== 'object' || Array.isArray(payload)) return true;
	const detail = (payload as {detail?: unknown}).detail;
	return detail == null || detail === 'Not Found' || detail === 'Method Not Found';
}

/**
 * 200 信封里的失败：诊断/实验端点大量用 `{ok:false,error}` 表达拒绝
 * （FastAPI 的校验失败也以 200 回这里的 mode 检查），只看 `res.ok` 会把拒绝读成成功。
 */
function envelopeFailure(payload: unknown, status: number): string {
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return '';
	const o = payload as Record<string, unknown>;
	if (o.ok !== false) return '';
	const reason = o.error ?? o.detail ?? o.message;
	if (typeof reason === 'string' && reason.trim()) return reason.trim();
	if (reason != null && typeof reason === 'object') return JSON.stringify(reason);
	return `端点返回 ok:false 且未给出原因（HTTP ${status}）`;
}

async function getJson(
	path: string,
	timeoutMs?: number,
	signal?: AbortSignal,
): Promise<unknown> {
	const res = await send(path, undefined, timeoutMs, signal);
	if (!res.ok) throw await failureOf(res);
	return await res.json();
}

async function postJson(
	path: string,
	body: Record<string, unknown>,
	timeoutMs?: number,
	signal?: AbortSignal,
): Promise<unknown> {
	const res = await send(
		path,
		{
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify(body),
		},
		timeoutMs,
		signal,
	);
	if (!res.ok) throw await failureOf(res);
	return await res.json();
}

function qs(params: Record<string, string | number | undefined>): string {
	const q = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v === undefined || v === '') continue;
		q.set(k, String(v));
	}
	const out = q.toString();
	return out ? `?${out}` : '';
}

/** 有界运行列表：每个 turn 覆盖到哪些边界。 */
export async function fetchDiagRuns(
	sessionId: string,
	opts?: {limit?: number; signal?: AbortSignal},
): Promise<DiagRunsResult> {
	const data = await getJson(
		`/v1/diagnostics/runs${qs({session_id: sessionId, limit: opts?.limit})}`,
		undefined,
		opts?.signal,
	);
	return parseRunsResult(data);
}

/** 一次运行的证据链 + 结论 + 缺项（事件按 offset 分页）。 */
export async function fetchDiagRun(
	sessionId: string,
	turnId: string,
	opts?: {eventLimit?: number; eventOffset?: number; signal?: AbortSignal},
): Promise<DiagRunDetail> {
	const data = await getJson(
		`/v1/diagnostics/runs/${encodeURIComponent(turnId)}${qs({
			session_id: sessionId,
			event_limit: opts?.eventLimit,
			event_offset: opts?.eventOffset,
		})}`,
		LONG_TIMEOUT_MS,
		opts?.signal,
	);
	return parseRunDetail(data);
}

/** 追加一页事件（同一运行的分页游标；返回合并后的 detail 由调用方保留）。 */
export async function fetchDiagRunEvents(
	sessionId: string,
	turnId: string,
	offset: number,
	eventLimit?: number,
): Promise<{events: DiagEvent[]; total: number; complete: boolean; nextCursor: string}> {
	const data = rec(
		await getJson(
			`/v1/diagnostics/runs/${encodeURIComponent(turnId)}${qs({
				session_id: sessionId,
				event_limit: eventLimit,
				event_offset: offset,
				with_report: 'false',
			})}`,
			LONG_TIMEOUT_MS,
		),
	);
	return {
		events: arr(data.events).map(parseEvent),
		total: n(data.event_total) ?? 0,
		complete: b(data.events_complete),
		nextCursor: s(data.next_event_cursor),
	};
}

export async function fetchDiagReportMarkdown(
	sessionId: string,
	turnId: string,
): Promise<{markdown: string; turn_id: string; session_id: string}> {
	const o = rec(
		await getJson(
			`/v1/diagnostics/runs/${encodeURIComponent(turnId)}/report.md${qs({
				session_id: sessionId,
			})}`,
			LONG_TIMEOUT_MS,
		),
	);
	const markdown = s(o.markdown);
	// 空正文不等于"这份报告没有内容"：不导出空文件冒充成功。
	if (!markdown.trim()) {
		throw new Error('导出失败：后端未返回报告正文（该轮次可能不在审计尾窗内）');
	}
	return {
		markdown,
		turn_id: s(o.turn_id),
		session_id: s(o.session_id),
	};
}

export type DiagPinInput = {
	note: string;
	expected?: string;
	evidence?: DiagEvidenceRef[];
	pinned_files?: string[];
};

/** 标记「这轮结果不对」并固定证据；不触发付费实验、不改任务内容。 */
export async function pinDiagRun(
	sessionId: string,
	turnId: string,
	input: DiagPinInput,
): Promise<{ok: boolean; pin: DiagPin | null; error: string}> {
	const o = rec(
		await postJson(
			`/v1/diagnostics/runs/${encodeURIComponent(turnId)}/pin${qs({
				session_id: sessionId,
			})}`,
			{
				note: input.note,
				...(input.expected ? {expected: input.expected} : {}),
				...(input.evidence?.length ? {evidence: input.evidence} : {}),
				...(input.pinned_files?.length ? {pinned_files: input.pinned_files} : {}),
			},
		),
	);
	return {ok: b(o.ok), pin: o.pin ? parsePin(o.pin) : null, error: s(o.error)};
}

export async function recordDiagVerifier(
	sessionId: string,
	turnId: string,
	input: {
		name: string;
		command?: string;
		exit_code?: number | null;
		output_ref?: string;
		verifier_version?: string;
		evidence?: DiagEvidenceRef[];
	},
): Promise<{ok: boolean; pin: DiagPin | null; error: string}> {
	const o = rec(
		await postJson(
			`/v1/diagnostics/runs/${encodeURIComponent(turnId)}/verifier${qs({
				session_id: sessionId,
			})}`,
			{
				name: input.name,
				...(input.command ? {command: input.command} : {}),
				// exit_code 省略即「未运行」：后端不会按 0 处理，这里也不补值。
				...(input.exit_code !== undefined ? {exit_code: input.exit_code} : {}),
				...(input.output_ref ? {output_ref: input.output_ref} : {}),
				...(input.verifier_version ? {verifier_version: input.verifier_version} : {}),
				...(input.evidence?.length ? {evidence: input.evidence} : {}),
			},
		),
	);
	return {ok: b(o.ok), pin: o.pin ? parsePin(o.pin) : null, error: s(o.error)};
}

export async function fetchDiagPins(
	sessionId: string,
	turnId?: string,
): Promise<DiagPin[]> {
	const o = rec(
		await getJson(`/v1/diagnostics/pins${qs({session_id: sessionId, turn_id: turnId})}`),
	);
	return arr(o.pins).map(parsePin);
}

/**
 * 撤销一条固定证据。回执必须读 body：`remove_pin` 在 200 里回 `{ok:false}`
 * 表示"这条 pin 不在了 / 不属于你的会话"，只看 HTTP 状态会把没删掉报成已删除。
 */
export async function deleteDiagPin(
	pinId: string,
	sessionId: string,
): Promise<{ok: boolean; error: string}> {
	const res = await send(
		`/v1/diagnostics/pins/${encodeURIComponent(pinId)}${qs({session_id: sessionId})}`,
		{method: 'DELETE'},
	);
	const payload = await res.json().catch(() => null);
	if (!res.ok) {
		return {ok: false, error: formatErrorDetail(payload, res.status)};
	}
	const o = rec(payload);
	if (o.ok !== true) {
		return {ok: false, error: s(o.error) || `HTTP ${res.status}`};
	}
	return {ok: true, error: ''};
}

/** 信息丢失定位链（7 级）；任一级未记账 → 后端判无法归因。 */
export async function traceDiagFact(
	sessionId: string,
	turnId: string,
	needle: string,
): Promise<DiagFactTrace> {
	const o = rec(
		await getJson(
			`/v1/diagnostics/runs/${encodeURIComponent(turnId)}/fact${qs({
				session_id: sessionId,
				needle,
			})}`,
			LONG_TIMEOUT_MS,
		),
	);
	return {
		needle: s(o.needle),
		session_id: s(o.session_id),
		turn_id: s(o.turn_id),
		stages: arr(o.stages).map(v => {
			const g = rec(v);
			return {
				stage: s(g.stage),
				label: s(g.label),
				state: s(g.state),
				evidence: parseEvidenceList(g.evidence),
				note: s(g.note),
			};
		}),
		verdict: s(o.verdict),
		statement: s(o.statement),
		unprovable_stages: arr(o.unprovable_stages).map(s),
		caveat: s(o.caveat),
	};
}

/** 按需回读 transcript 正文（含冷层 blob）；失败必须说明，不返回空正文冒充成功。 */
export async function fetchDiagMessage(
	sessionId: string,
	messageId: string,
	maxChars?: number,
): Promise<DiagMessageBody> {
	const o = rec(
		await getJson(
			`/v1/diagnostics/messages/${encodeURIComponent(messageId)}${qs({
				session_id: sessionId,
				max_chars: maxChars,
			})}`,
		),
	);
	return {
		ok: b(o.ok),
		message_id: s(o.message_id || messageId),
		role: s(o.role),
		content: s(o.content),
		truncated: b(o.truncated),
		body_state: s(o.body_state),
		content_hash: s(o.content_hash),
		locator: s(o.locator),
		error: s(o.error),
	};
}

export async function fetchDiagCapture(sessionId: string): Promise<DiagCaptureState> {
	const o = rec(await getJson(`/v1/diagnostics/capture${qs({session_id: sessionId})}`));
	return {
		session_id: s(o.session_id || sessionId),
		enabled: b(o.enabled),
		disk_bytes: n(o.disk_bytes),
		quota_bytes: n(o.quota_bytes),
		locator: s(o.locator),
	};
}

export async function setDiagCapture(
	sessionId: string,
	enabled: boolean,
	opts?: {maxBytes?: number; note?: string},
): Promise<DiagCaptureState> {
	const o = rec(
		await postJson(`/v1/diagnostics/capture`, {
			session_id: sessionId,
			enabled,
			...(opts?.maxBytes != null ? {max_bytes: opts.maxBytes} : {}),
			...(opts?.note ? {note: opts.note} : {}),
		}, LONG_TIMEOUT_MS),
	);
	// 开关响应只带 enabled；磁盘与配额由 fetchDiagCapture 另行读取，不补 0。
	return {
		session_id: s(o.session_id || sessionId),
		enabled: b(o.enabled),
		disk_bytes: null,
		quota_bytes: null,
		locator: '',
	};
}

// ---------------------------------------------------------------------------
// 实验层（后端由并行工作流实现；这里只透传，不声明字段、不合成结构）
// ---------------------------------------------------------------------------

async function rawJson(
	path: string,
	init?: {method?: 'GET' | 'POST'; body?: unknown},
): Promise<DiagRawResult> {
	let res: Response;
	try {
		res = await send(
			path,
			{
				method: init?.method ?? 'GET',
				...(init?.body !== undefined
					? {
							headers: {'Content-Type': 'application/json'},
							body: JSON.stringify(init.body),
						}
					: {}),
			},
			LONG_TIMEOUT_MS,
		);
	} catch (err) {
		return {
			ok: false,
			status: 0,
			error: err instanceof Error ? err.message : String(err),
		};
	}
	const payload: unknown = await res.json().catch(() => null);
	if (!res.ok) {
		return {ok: false, status: res.status, error: formatErrorDetail(payload, res.status)};
	}
	// 关键：实验端点用 200 + {ok:false,error} 表达拒绝（mode 非法、配对不成立、
	// 启动失败都走这里）。只看 res.status 会把拒绝渲染成绿色"端点可访问"。
	const refused = envelopeFailure(payload, res.status);
	if (refused) return {ok: false, status: res.status, error: refused};
	return {ok: true, status: res.status, data: payload};
}

/** 后端 `diagnostics/experiments/manifest.MODES` 的常量是小写；大写一律被拒。 */
export const DIAG_EXPERIMENT_MODES = ['a0', 'a1', 'a2'] as const;
export type DiagExperimentMode = (typeof DIAG_EXPERIMENT_MODES)[number];

/** 一次 A/B 配对的臂身份（后端 manifest.ARMS = ("A","B")）。 */
export type DiagExperimentArms = {A: Record<string, unknown>; B: Record<string, unknown>};

export type DiagExperimentRequestBody = {
	mode: DiagExperimentMode;
	task_id: string;
	variants: DiagExperimentArms;
	repeat: number;
	allowed_differences: string[];
	budget_cny?: number;
	idempotency_key?: string;
};

/**
 * 实验请求体：只发服务端真实存在的键（`variants` / `repeat` / `task_id`）。
 * 旧实现发的 `baseline` / `candidate` / `repeats` / `session_id` / `turn_id` 会被
 * pydantic 的 `extra='ignore'` 静默丢掉，于是两臂永远相同。
 */
export function buildExperimentBody(args: {
	mode: DiagExperimentMode;
	sessionId: string;
	turnId: string;
	variantA: Record<string, unknown>;
	variantB: Record<string, unknown>;
	repeat: number;
	/** 未通过有限性检查就不要带上——`Number('')` 是 NaN，序列化后会变成 null，
	 *  而 null 在后端读作「不设上限」，与界面上的"计划里会标出"正好相反。 */
	budgetCny?: number | null;
	allowedDifferences?: string[];
}): DiagExperimentRequestBody {
	const body: DiagExperimentRequestBody = {
		mode: args.mode,
		task_id: `xeyo:${args.sessionId}:${args.turnId}`.slice(0, 200),
		variants: {A: args.variantA, B: args.variantB},
		repeat: Number.isFinite(args.repeat) ? Math.max(0, Math.min(20, Math.trunc(args.repeat))) : 0,
		allowed_differences: (args.allowedDifferences ?? []).filter(x => typeof x === 'string' && x.trim()),
	};
	if (args.budgetCny != null && Number.isFinite(args.budgetCny) && args.budgetCny >= 0) {
		body.budget_cny = args.budgetCny;
	}
	return body;
}

export function planDiagExperiment(body: Record<string, unknown>): Promise<DiagRawResult> {
	return rawJson('/v1/diagnostics/experiments/plan', {method: 'POST', body});
}

export function startDiagExperiment(body: Record<string, unknown>): Promise<DiagRawResult> {
	return rawJson('/v1/diagnostics/experiments', {method: 'POST', body});
}

export function listDiagExperiments(limit?: number): Promise<DiagRawResult> {
	return rawJson(`/v1/diagnostics/experiments${qs({limit})}`);
}

export function fetchDiagExperiment(id: string): Promise<DiagRawResult> {
	return rawJson(`/v1/diagnostics/experiments/${encodeURIComponent(id)}`);
}

export function cancelDiagExperiment(id: string): Promise<DiagRawResult> {
	return rawJson(
		`/v1/diagnostics/experiments/${encodeURIComponent(id)}/cancel`,
		{method: 'POST'},
	);
}
