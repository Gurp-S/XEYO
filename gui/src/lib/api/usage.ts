/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec api8: usage，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 */
import {
	useSettingsStore,
} from '@/stores/settingsStore';
import {
	apiUrl,
} from '@/lib/apiBase';
import {
	fetchWithTimeout,
	formatErrorDetail,
} from './core';

export async function healthCheck(): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(apiUrl('/health'));
		return res.ok;
	} catch {
		return false;
	}
}

export type VendorModelMode = {id: string; label?: string};

export type VendorModel = {
	id: string;
	label?: string;
	owned_by?: string;
	created?: number;
	context_length?: number | null;
	max_output_tokens?: number | null;
	pricing?: Record<string, unknown> | null;
	modes?: {
		thinking?: VendorModelMode[] | unknown;
		reasoning_effort?: VendorModelMode[] | unknown;
		[k: string]: unknown;
	};
};

export type VendorModelsReport = {
	object?: string;
	source?: string;
	vendor_ok?: boolean;
	vendor_error?: string;
	data: VendorModel[];
};

// 厂商 /models 只在拉列表时携带 context_length，而 streamChat 每次请求都要带
// context_limit；缓存持久化到 localStorage，避免重启后未重开模型选择器就拿不到窗口。
export const VENDOR_CONTEXT_LIMIT_KEY = 'xeyo.vendor_context_limits.v1';

export function loadVendorContextLimits(): Map<string, number> {
	const map = new Map<string, number>();
	try {
		const raw = globalThis.localStorage?.getItem(VENDOR_CONTEXT_LIMIT_KEY) ?? null;
		const parsed: unknown = raw ? JSON.parse(raw) : null;
		if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
			for (const [key, value] of Object.entries(parsed)) {
				const n = Number(value);
				if (Number.isFinite(n) && n > 0) {
					map.set(key, Math.floor(n));
				}
			}
		}
	} catch {
		// 存档损坏即从空重建，不影响会话
	}
	return map;
}

export const vendorContextLimitCache = loadVendorContextLimits();

export function persistVendorContextLimits(): void {
	try {
		globalThis.localStorage?.setItem(
			VENDOR_CONTEXT_LIMIT_KEY,
			JSON.stringify(Object.fromEntries(vendorContextLimitCache)),
		);
	} catch {
		// 存储不可用（隐私模式/已满）：仅放弃持久化
	}
}

export function vendorModelCacheKey(provider: string, baseUrl: string, model: string): string {
	return `${provider}|${baseUrl.replace(/\/+$/, '')}|${model}`;
}

export function rememberVendorContextLimits(
	provider: string,
	baseUrl: string,
	models: VendorModel[],
): void {
	let changed = false;
	for (const row of models) {
		const limit = Number(row.context_length ?? 0);
		if (row.id && Number.isFinite(limit) && limit > 0) {
			const key = vendorModelCacheKey(provider, baseUrl, row.id);
			const next = Math.floor(limit);
			if (vendorContextLimitCache.get(key) !== next) {
				vendorContextLimitCache.set(key, next);
				changed = true;
			}
		}
	}
	if (changed) {
		persistVendorContextLimits();
	}
}

export function getCachedModelContextLimit(
	provider: string,
	baseUrl: string,
	model: string,
): number | undefined {
	return vendorContextLimitCache.get(vendorModelCacheKey(provider, baseUrl, model));
}

export async function fetchVendorModels(opts?: {
	apiKey?: string;
	provider?: string;
	baseUrl?: string;
}): Promise<VendorModelsReport> {
	const s = useSettingsStore.getState();
	const headers: Record<string, string> = {
		'X-Provider': opts?.provider ?? s.provider,
		'X-Base-Url': opts?.baseUrl ?? s.resolvedBaseUrl(),
	};
	const key = (opts?.apiKey ?? s.apiKey).trim();
	if (key) {
		headers.Authorization = `Bearer ${key}`;
	}
	const res = await fetchWithTimeout(apiUrl('/v1/models'), {headers});
	if (!res.ok) {
		return {
			vendor_ok: false,
			vendor_error: `HTTP ${res.status}`,
			data: [],
		};
	}
	const body = (await res.json()) as VendorModelsReport;
	const data = Array.isArray(body.data) ? body.data : [];
	rememberVendorContextLimits(headers['X-Provider'], headers['X-Base-Url'], data);
	return {
		...body,
		data,
	};
}

/**
 * v4 聚合口径（对齐 DeepSeek Harness usage-stats，2026-09-09 B1）：
 * totals / series / models 每层只有三分类 + hit_rate + 成功结算 requests，
 * 无金额、无吞吐大数。input_total = hit + miss（官方 prompt_tokens 语义），
 * 是唯一允许的合计；output 与输入分列，禁止相加。
 */
export type UsageBucket = {
	requests: number;
	input_hit: number;
	input_miss: number;
	output: number;
	input_total: number;
	/** 缓存命中率 hit/(hit+miss)×100，一位小数；无输入时为 null。 */
	hit_rate: number | null;
};

export type UsageDayPoint = UsageBucket & {
	day: string;
};

export type UsageModelBlock = UsageBucket & {
	provider: string;
	model: string;
	series: UsageDayPoint[];
};

export type UsageReport = {
	days: string[];
	totals: UsageBucket;
	source?: 'vendor' | 'local' | 'mixed' | string;
	vendor_ok?: boolean;
	vendor_error?: string;
	series: UsageDayPoint[];
	models: UsageModelBlock[];
	keys: string[];
};

export async function fetchUsage(query: {
	days: number;
	model?: string;
	provider?: string;
	key_fp?: string;
	apiKey?: string;
	baseUrl?: string;
}): Promise<UsageReport> {
	const s = useSettingsStore.getState();
	const qs = new URLSearchParams();
	qs.set('days', String(query.days));
	if (query.model) {
		qs.set('model', query.model);
	}
	if (query.provider) {
		qs.set('provider', query.provider);
	}
	if (query.key_fp) {
		qs.set('key_fp', query.key_fp);
	}
	const headers: Record<string, string> = {
		'X-Provider': query.provider ?? s.provider,
		'X-Base-Url': query.baseUrl ?? s.resolvedBaseUrl(),
	};
	const key = (query.apiKey ?? s.apiKey).trim();
	if (key) {
		headers.Authorization = `Bearer ${key}`;
	}
	const res = await fetchWithTimeout(apiUrl(`/v1/usage?${qs.toString()}`), {
		headers,
		cache: 'no-store',
	});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return (await res.json()) as UsageReport;
}

export type UsageBalance = {
	available: boolean;
	is_available?: boolean | null;
	currency?: string;
	total_balance?: string;
	granted_balance?: string;
	topped_up_balance?: string;
	reason?: string;
};

export async function fetchUsageBalance(opts?: {
	apiKey?: string;
	provider?: string;
	baseUrl?: string;
}): Promise<UsageBalance> {
	const s = useSettingsStore.getState();
	const headers: Record<string, string> = {
		'X-Provider': opts?.provider ?? s.provider,
		'X-Base-Url': opts?.baseUrl ?? s.resolvedBaseUrl(),
	};
	const key = (opts?.apiKey ?? s.apiKey).trim();
	if (key) {
		headers.Authorization = `Bearer ${key}`;
	}
	const res = await fetchWithTimeout(apiUrl('/v1/usage/balance'), {
		headers,
		cache: 'no-store',
	});
	if (!res.ok) {
		return {available: false, reason: `HTTP ${res.status}`};
	}
	return (await res.json()) as UsageBalance;
}

/** 设置 agent 工作区根目录（一个文件夹 = 一个工作区）。 */
