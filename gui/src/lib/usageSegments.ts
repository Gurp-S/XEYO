/**
 * usageSegments.ts — 顶栏用量预览「上下文构成分段条」的纯计算。
 *
 * 从 ChatHeader.tsx 抽出的原因：分段条是唯一同时混用了
 * 「账单口径累计量」「快照口径最近一枪」「字符估算折算」三种数据的 UI 元素，
 * 且曾把输出 token 混进上下文构成条。抽成纯函数后才能用单测钉死口径。
 *
 * 两类分段：
 * - 权威分段（contextBreakdown）：后端 `_scale_breakdown` 按字符占比把厂商
 *   prompt_tokens 摊到 7 个类别，sum === context_tokens。
 * - 回退分段（lastHit/lastMiss）：无 breakdown 时用最近一枪的缓存拆分。
 *   **输出不计入**：输出 token 不属于「上下文窗口占用」，把它放进同一根条
 *   会让构成之和超出窗口占用率（2026-09-09 修正）。
 */

/** 上下文构成类的稳定配色（与预览一致）。 */
export const CONTEXT_CATEGORY_COLORS: Record<string, string> = {
	system: '#8a8f98',
	rules: '#7d9a86',
	memory_behavior: '#5a7d8c',
	tool_definitions: '#6ea8c9',
	memory_index: '#c7a24b',
	summary: '#d06a8f',
	conversation: '#c9574f',
	remaining: 'transparent',
};

export type UsageSegment = {
	key: string;
	value: number;
	color: string;
	label: string;
	tokens: number;
	chars?: number;
	share: number;
};

export type ContextBreakdownRow = {
	category: string;
	label: string;
	tokens: number;
	chars?: number;
	soft_over?: boolean;
};

export type UsageSegmentsInput = {
	/** 后端按类别下发的 token 拆分（权威分段）。空数组 = 走回退。 */
	contextBreakdown?: ContextBreakdownRow[] | null;
	/** 已测量才有值：厂商窗口上限。 */
	contextLimit?: number | null;
	/** 已测量才有值：最近一枪的输入 token。 */
	contextTokens?: number | null;
	/** 最近一枪的缓存命中/未命中（单轮，非累计）。 */
	lastCacheHitTokens?: number | null;
	lastCacheMissTokens?: number | null;
};

export type UsageSegmentsResult = {
	segments: UsageSegment[];
	/** 分段占比的分母：权威段用窗口，回退段用条总长。 */
	denominator: number;
	/** 是否使用权威分段（false = 回退分段）。 */
	authoritative: boolean;
};

function nonNeg(value: number | null | undefined): number {
	return value != null && Number.isFinite(value) ? Math.max(0, value) : 0;
}

/**
 * 计算分段条。「权威段」与「回退段」的差别只体现在数据来源与分母，
 * 两者都保证各段 value 之和 === 分母（回退段在窗口已知时含 remaining 补足）。
 */
export function computeUsageSegments(
	input: UsageSegmentsInput,
): UsageSegmentsResult {
	const {
		contextBreakdown,
		contextLimit = null,
		contextTokens = null,
		lastCacheHitTokens = null,
		lastCacheMissTokens = null,
	} = input;

	const measuredContext =
		contextLimit != null && contextLimit > 0 && contextTokens != null;

	const breakdown = contextBreakdown ?? [];
	if (breakdown.length > 0) {
		// 权威段分母 = 窗口；缺窗口时退化为各段之和（此时占比口径变为「占已用」）。
		const sum = breakdown.reduce((a, b) => a + nonNeg(b.tokens), 0);
		const denominator = measuredContext
			? contextLimit!
			: sum > 0
				? sum
				: 1;
		const segments = breakdown.map((b, index) => {
			const tokens = nonNeg(b.tokens);
			const chars = Math.max(0, Number(b.chars) || 0);
			const softOver = Boolean(b.soft_over) && b.category === 'rules';
			return {
				key: `${b.category}-${index}`,
				value: tokens,
				color: softOver
					? '#c47a3a'
					: CONTEXT_CATEGORY_COLORS[b.category] || '#8a8f98',
				label: softOver ? `${b.label}（超软预算）` : b.label,
				tokens,
				chars,
				share: Math.min(100, Math.round((tokens / denominator) * 100)),
			};
		});
		return {segments, denominator, authoritative: true};
	}

	// 回退段：只有输入（命中/未命中）属于上下文构成。
	const hit = lastCacheHitTokens;
	const miss = lastCacheMissTokens;
	const hasSplit = hit != null || miss != null;
	if (!hasSplit) {
		return {segments: [], denominator: 1, authoritative: false};
	}
	const hitTokens = nonNeg(hit);
	const missTokens = nonNeg(miss);
	const usedInput = hitTokens + missTokens;
	// 窗口已知时整根条 = 窗口（含剩余）；否则整根条 = 本轮输入。
	const denominator = measuredContext ? contextLimit! : Math.max(1, usedInput);

	const raw: Omit<UsageSegment, 'share'>[] = [
		{
			key: 'fb-hit',
			value: hitTokens,
			color: 'var(--xy-chart-soft)',
			label: '输入 · 命中缓存',
			tokens: hitTokens,
		},
		{
			key: 'fb-miss',
			value: missTokens,
			color: 'var(--xy-chart-mid)',
			label: '输入 · 未命中',
			tokens: missTokens,
		},
	];
	if (measuredContext) {
		const remaining = Math.max(0, contextLimit! - usedInput);
		raw.push({
			key: 'fb-rem',
			value: remaining,
			color: 'transparent',
			label: '剩余上下文窗口',
			tokens: remaining,
		});
	}
	const segments = raw.map(s => ({
		...s,
		share: Math.min(100, Math.round((s.value / denominator) * 100)),
	}));
	return {segments, denominator, authoritative: false};
}

/** 渲染宽度（%），带命中用的最窄 0.5% 钳制与 98% 上限。 */
export function segmentWidths(
	segments: UsageSegment[],
	denominator: number,
): number[] {
	const denom = denominator > 0 ? denominator : 1;
	return segments.map(s =>
		Math.max(0.5, Math.min(98, (s.value / denom) * 100)),
	);
}
