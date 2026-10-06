/**
 * 用量页的实时数据面：`GET /v1/usage/report`（本机账本聚合，见 `usage/live_report.py`）。
 *
 * 为什么另立一个文件而不是复用 `./api/usage.ts`：那份是**厂商通路**（带 key 出网、
 * 按厂商口径回三分类），这一份是**本机账本通路**（不出网、不算钱、按天/会话/枪下钻）。
 * 两者的失败形态完全不同，混在一个文件里只会让"读不到"说成同一句话。
 *
 * 逐字段收口的纪律与 A3 报告数据面一致：服务端少给一个键 ⇒ 该键是 `null`/`undefined`，
 * 而不是 0。界面按这个区别说话（「数据里没有」/「无价目」/「部分未知」）。
 */
import {apiUrl} from '@/lib/apiBase';
import {fetchWithTimeout, formatErrorDetail} from './core';

/** 服务端清洗过的数值：非有限值（NaN/Inf）一律回 null，界面据此说"数据里没有"。 */
export type LiveNum = number | null | undefined;

export type LiveUsageModelRow = {
	provider?: string;
	model?: string;
	requests?: LiveNum;
	prompt_tokens?: LiveNum;
	cache_hit?: LiveNum;
	cache_miss?: LiveNum;
	/** 命中率是 0—1 的小数（与报告同式：hit/(hit+miss)）；无输入时 null。 */
	hit_rate?: LiveNum;
	output?: LiveNum;
	/** 账本自带的 tokens（厂商 total_tokens 语义）。三分类仍分列，不参与相加。 */
	tokens?: LiveNum;
	cost_cny?: LiveNum;
	/** 无价目行数：>0 时上面那笔成本是部分合计，界面要标「部分未知」。 */
	cost_unknown_requests?: LiveNum;
};

export type LiveUsageDay = {
	day: string;
	/**
	 * 快照验收判据，三态：`true` 已验收 / `false` 快照过但未验收 / `null` 这一天
	 * 从没进过快照。界面只透传，绝不从数字反推。
	 */
	accepted: boolean | null;
	snapshot?: boolean;
	requests?: LiveNum;
	prompt_tokens?: LiveNum;
	cache_hit?: LiveNum;
	cache_miss?: LiveNum;
	hit_rate?: LiveNum;
	c2_count?: LiveNum;
	output?: LiveNum;
	tokens?: LiveNum;
	cost_cny?: LiveNum;
	cost_unknown_requests?: LiveNum;
	/** 有会话归属的会话数；无归属的行另算（见 unattributed_requests）。 */
	sessions?: LiveNum;
	turns?: LiveNum;
	/** 24 桶，按每轮首笔时间的北京时间小时；与 day 字段同时区。 */
	hour_counts: number[];
	/** 首笔时间读不出的轮数；不为 0 时界面要说明。 */
	hour_unknown: number;
	/** 账本里没有 session_id 的笔数（老行）：不猜归属，只报数。 */
	unattributed_requests?: LiveNum;
	by_model: LiveUsageModelRow[];
};

export type LiveUsageSource = {
	/** 恒为 'live_ledger'：这一份读的是本机账本，不是快照报告文件。 */
	kind?: string;
	path?: string;
	rows?: LiveNum;
	/** 'ok' / 'empty_store' / 'missing_store'——缺账本是正面事实，不是故障。 */
	store?: string;
	bytes?: LiveNum;
	mtime?: LiveNum;
};

export type LiveUsageReport = {
	ok: true;
	live: true;
	/** 本次聚合时刻（北京时间 ISO）；账本每变一次它就变一次。 */
	generated_at: string;
	source: LiveUsageSource;
	day_count: number;
	days: LiveUsageDay[];
};

export type LiveUsageEventRow = {
	ts?: LiveNum;
	provider?: string;
	model?: string;
	prompt_tokens?: LiveNum;
	cache_hit?: LiveNum;
	cache_miss?: LiveNum;
	output?: LiveNum;
	tokens?: LiveNum;
	cost_cny?: LiveNum;
	/** 'api' / 'estimate' / 'unpriced'：金额是哪一档，界面据此决定说什么。 */
	cost_source?: string | null;
	kind?: string | null;
	attempt?: LiveNum;
	request_id?: string | null;
};

export type LiveUsageTurnRow = {
	session_id?: string;
	label?: string;
	model?: string;
	first_ts?: LiveNum;
	last_ts?: LiveNum;
	requests?: LiveNum;
	prompt_tokens?: LiveNum;
	cache_hit?: LiveNum;
	cache_miss?: LiveNum;
	hit_rate?: LiveNum;
	output?: LiveNum;
	tokens?: LiveNum;
	cost_cny?: LiveNum;
	cost_unknown_requests?: LiveNum;
	event_count?: LiveNum;
	/** 该轮被上界省掉的原文行数（>0 时界面要说明"另有 N 枪未展开"）。 */
	events_truncated?: LiveNum;
	events: LiveUsageEventRow[];
};

export type LiveUsageSessionRow = {
	session_id?: string;
	requests?: LiveNum;
	prompt_tokens?: LiveNum;
	cache_hit?: LiveNum;
	cache_miss?: LiveNum;
	hit_rate?: LiveNum;
	output?: LiveNum;
	tokens?: LiveNum;
	cost_cny?: LiveNum;
	cost_unknown_requests?: LiveNum;
};

export type LiveUsageDayDetail = {
	ok: true;
	live: true;
	generated_at: string;
	source: LiveUsageSource;
	day: string;
	/** 账本可读而这一天没有行：true（"没有"与"没读到"是两件事）。 */
	missing: boolean;
	summary: LiveUsageDay | null;
	sessions: LiveUsageSessionRow[];
	turns: LiveUsageTurnRow[];
	/** 这一天被上界省掉的每枪行总数。 */
	events_truncated?: LiveNum;
};

/** 与后端同一条判据：读不出走 HTTP 错误，"没读到"与"确认没有"在 ok/message 上分家。 */
export type LiveUsageRead = {ok: boolean; data: LiveUsageReport | null; message: string};
export type LiveUsageDayRead = {ok: boolean; data: LiveUsageDayDetail | null; message: string};

function str(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() ? value : undefined;
}

function numOr(value: unknown): LiveNum {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function arr(value: unknown): Record<string, unknown>[] {
	return Array.isArray(value)
		? value.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object')
		: [];
}

/** 数字数组：定长 24、逐项收口，缺项补 0（缺桶与"这一小时 0 轮"在界面上是同一格）。 */
function hours(value: unknown): number[] {
	const raw = Array.isArray(value) ? value : [];
	return Array.from({length: 24}, (_, i) => {
		const n = raw[i];
		return typeof n === 'number' && Number.isFinite(n) ? n : 0;
	});
}

function modelRows(value: unknown): LiveUsageModelRow[] {
	return arr(value).map(r => ({
		provider: str(r.provider),
		model: str(r.model),
		requests: numOr(r.requests),
		prompt_tokens: numOr(r.prompt_tokens),
		cache_hit: numOr(r.cache_hit),
		cache_miss: numOr(r.cache_miss),
		hit_rate: numOr(r.hit_rate),
		output: numOr(r.output),
		tokens: numOr(r.tokens),
		cost_cny: numOr(r.cost_cny),
		cost_unknown_requests: numOr(r.cost_unknown_requests),
	}));
}

function dayRow(raw: unknown): LiveUsageDay | null {
	if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
	const o = raw as Record<string, unknown>;
	const day = str(o.day);
	if (!day) return null;
	return {
		day,
		// 三态：只有服务端明确给了 true/false 才是判据；缺键是"没快照过"这一档。
		accepted: typeof o.accepted === 'boolean' ? o.accepted : null,
		snapshot: o.snapshot === true,
		requests: numOr(o.requests),
		prompt_tokens: numOr(o.prompt_tokens),
		cache_hit: numOr(o.cache_hit),
		cache_miss: numOr(o.cache_miss),
		hit_rate: numOr(o.hit_rate),
		c2_count: numOr(o.c2_count),
		output: numOr(o.output),
		tokens: numOr(o.tokens),
		cost_cny: numOr(o.cost_cny),
		cost_unknown_requests: numOr(o.cost_unknown_requests),
		sessions: numOr(o.sessions),
		turns: numOr(o.turns),
		hour_counts: hours(o.hour_counts),
		hour_unknown: typeof o.hour_unknown === 'number' && Number.isFinite(o.hour_unknown) ? o.hour_unknown : 0,
		unattributed_requests: numOr(o.unattributed_requests),
		by_model: modelRows(o.by_model),
	};
}

function source(raw: unknown): LiveUsageSource {
	const o = (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>;
	return {
		kind: str(o.kind),
		path: str(o.path),
		rows: numOr(o.rows),
		store: str(o.store),
		bytes: numOr(o.bytes),
		mtime: numOr(o.mtime),
	};
}

function eventRows(value: unknown): LiveUsageEventRow[] {
	return arr(value).map(r => ({
		ts: numOr(r.ts),
		provider: str(r.provider),
		model: str(r.model),
		prompt_tokens: numOr(r.prompt_tokens),
		cache_hit: numOr(r.cache_hit),
		cache_miss: numOr(r.cache_miss),
		output: numOr(r.output),
		tokens: numOr(r.tokens),
		cost_cny: numOr(r.cost_cny),
		cost_source: typeof r.cost_source === 'string' ? r.cost_source : null,
		kind: typeof r.kind === 'string' ? r.kind : null,
		attempt: numOr(r.attempt),
		request_id: typeof r.request_id === 'string' ? r.request_id : null,
	}));
}

function turnRows(value: unknown): LiveUsageTurnRow[] {
	return arr(value).map(r => ({
		session_id: str(r.session_id),
		label: str(r.label),
		model: str(r.model),
		first_ts: numOr(r.first_ts),
		last_ts: numOr(r.last_ts),
		requests: numOr(r.requests),
		prompt_tokens: numOr(r.prompt_tokens),
		cache_hit: numOr(r.cache_hit),
		cache_miss: numOr(r.cache_miss),
		hit_rate: numOr(r.hit_rate),
		output: numOr(r.output),
		tokens: numOr(r.tokens),
		cost_cny: numOr(r.cost_cny),
		cost_unknown_requests: numOr(r.cost_unknown_requests),
		event_count: numOr(r.event_count),
		events_truncated: numOr(r.events_truncated),
		events: eventRows(r.events),
	}));
}

function sessionRows(value: unknown): LiveUsageSessionRow[] {
	return arr(value).map(r => ({
		session_id: str(r.session_id),
		requests: numOr(r.requests),
		prompt_tokens: numOr(r.prompt_tokens),
		cache_hit: numOr(r.cache_hit),
		cache_miss: numOr(r.cache_miss),
		hit_rate: numOr(r.hit_rate),
		output: numOr(r.output),
		tokens: numOr(r.tokens),
		cost_cny: numOr(r.cost_cny),
		cost_unknown_requests: numOr(r.cost_unknown_requests),
	}));
}

/** 全区间日摘要（日列表 / 历史表 / Token 活动热力图）。 */
export async function fetchLiveUsageReport(opts?: {
	days?: number;
}): Promise<LiveUsageRead> {
	try {
		const qs = opts?.days ? `?days=${encodeURIComponent(String(opts.days))}` : '';
		const res = await fetchWithTimeout(apiUrl(`/v1/usage/report${qs}`), {cache: 'no-store'});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, data: null, message: 'receipt_bad_live_usage'};
		}
		const body = payload as Record<string, unknown>;
		if (body.ok !== true || !Array.isArray(body.days)) {
			return {ok: false, data: null, message: 'receipt_bad_live_usage'};
		}
		const days = body.days
			.map(dayRow)
			.filter((d): d is LiveUsageDay => d !== null);
		return {
			ok: true,
			data: {
				ok: true,
				live: true,
				generated_at: str(body.generated_at) ?? '',
				source: source(body.source),
				day_count: typeof body.day_count === 'number' ? body.day_count : days.length,
				days,
			},
			message: '',
		};
	} catch (err) {
		return {ok: false, data: null, message: err instanceof Error ? err.message : String(err)};
	}
}

/** 某一天的下钻：分会话 + 分轮次（每轮带每枪事件行）。 */
export async function fetchLiveUsageDay(day: string): Promise<LiveUsageDayRead> {
	const wanted = day.trim();
	if (!wanted) return {ok: false, data: null, message: 'no_day'};
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/usage/report?day=${encodeURIComponent(wanted)}`),
			{cache: 'no-store'},
		);
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, data: null, message: 'receipt_bad_live_usage_day'};
		}
		const body = payload as Record<string, unknown>;
		if (body.ok !== true || !str(body.day)) {
			return {ok: false, data: null, message: 'receipt_bad_live_usage_day'};
		}
		const missing = body.missing === true;
		const summary = missing ? null : dayRow(body.summary);
		if (!missing && !summary) {
			// 后端说这一天有行，summary 却读不出形状：这是形状漂移，不能当"没有"。
			return {ok: false, data: null, message: 'receipt_bad_live_usage_day'};
		}
		return {
			ok: true,
			data: {
				ok: true,
				live: true,
				generated_at: str(body.generated_at) ?? '',
				source: source(body.source),
				day: String(body.day),
				missing,
				summary: summary as LiveUsageDay | null,
				sessions: sessionRows(body.sessions),
				turns: turnRows(body.turns),
				events_truncated: numOr(body.events_truncated),
			},
			message: '',
		};
	} catch (err) {
		return {ok: false, data: null, message: err instanceof Error ? err.message : String(err)};
	}
}
