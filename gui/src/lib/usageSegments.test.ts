import {describe, expect, it} from 'vitest';
import {
	computeUsageSegments,
	segmentWidths,
	CONTEXT_CATEGORY_COLORS,
	type ContextBreakdownRow,
} from './usageSegments';

/**
 * 分段条契约（2026-09-09 钉死）。
 *
 * 背景：顶栏用量预览曾把「最近一枪的输出 token」算进「上下文构成」条，
 * 导致构成之和与窗口占用率对不上（输出不属于上下文窗口占用）。
 * 本文件同时钉死权威段与回退段的口径。
 */

function row(
	category: string,
	tokens: number,
	over: Partial<ContextBreakdownRow> = {},
): ContextBreakdownRow {
	return {category, label: category, tokens, ...over};
}

describe('computeUsageSegments — 权威段（contextBreakdown）', () => {
	it('分母 = 窗口，share = tokens / 窗口', () => {
		const {segments, denominator, authoritative} = computeUsageSegments({
			contextBreakdown: [row('system', 4_000), row('conversation', 6_000)],
			contextLimit: 100_000,
			contextTokens: 10_000,
		});
		expect(authoritative).toBe(true);
		expect(denominator).toBe(100_000);
		expect(segments.map(s => s.share)).toEqual([4, 6]);
	});

	it('窗口未知时分母退化为各段之和（口径变「占已用」）', () => {
		const {segments, denominator} = computeUsageSegments({
			contextBreakdown: [row('system', 3_000), row('conversation', 1_000)],
		});
		expect(denominator).toBe(4_000);
		expect(segments.map(s => s.share)).toEqual([75, 25]);
	});

	it('各类别取稳定配色', () => {
		const {segments} = computeUsageSegments({
			contextBreakdown: [row('system', 1), row('tool_definitions', 1)],
			contextLimit: 100,
		});
		expect(segments[0].color).toBe(CONTEXT_CATEGORY_COLORS.system);
		expect(segments[1].color).toBe(CONTEXT_CATEGORY_COLORS.tool_definitions);
	});

	it('未知类别回退到 system 灰，不崩', () => {
		const {segments} = computeUsageSegments({
			contextBreakdown: [row('unknown_category', 10)],
			contextLimit: 100,
		});
		expect(segments[0].color).toBe('#8a8f98');
	});

	it('rules 超软预算：橙色 + label 加后缀（仅 rules 类别生效）', () => {
		const {segments} = computeUsageSegments({
			contextBreakdown: [
				row('rules', 500, {soft_over: true}),
				row('system', 500, {soft_over: true}),
			],
			contextLimit: 1_000,
		});
		expect(segments[0].color).toBe('#c47a3a');
		expect(segments[0].label).toBe('rules（超软预算）');
		// 非 rules 类别即使带 soft_over 也不变色、不加后缀。
		expect(segments[1].color).toBe(CONTEXT_CATEGORY_COLORS.system);
		expect(segments[1].label).toBe('system');
	});

	it('chars 透传（悬停明细显示字符数）', () => {
		const {segments} = computeUsageSegments({
			contextBreakdown: [row('system', 1_000, {chars: 3_400})],
			contextLimit: 10_000,
		});
		expect(segments[0].chars).toBe(3_400);
	});
});

describe('computeUsageSegments — 回退段（无 breakdown）', () => {
	it('输出不计入上下文构成（本次修复的核心契约）', () => {
		const {segments} = computeUsageSegments({
			contextLimit: 100_000,
			contextTokens: 10_000,
			lastCacheHitTokens: 7_000,
			lastCacheMissTokens: 3_000,
		});
		expect(segments.map(s => s.key)).toEqual(['fb-hit', 'fb-miss', 'fb-rem']);
		expect(segments.some(s => s.key === 'fb-out')).toBe(false);
	});

	it('窗口已知：整根条 = 窗口，命中 + 未命中 + 剩余 === 窗口', () => {
		const {segments, denominator} = computeUsageSegments({
			contextLimit: 100_000,
			contextTokens: 10_000,
			lastCacheHitTokens: 7_000,
			lastCacheMissTokens: 3_000,
		});
		expect(denominator).toBe(100_000);
		const sum = segments.reduce((a, s) => a + s.value, 0);
		expect(sum).toBe(100_000);
		expect(segments.map(s => s.share)).toEqual([7, 3, 90]);
	});

	it('窗口未知：整根条 = 本轮输入，没有剩余段', () => {
		const {segments, denominator} = computeUsageSegments({
			lastCacheHitTokens: 7_000,
			lastCacheMissTokens: 3_000,
		});
		expect(denominator).toBe(10_000);
		expect(segments.map(s => s.key)).toEqual(['fb-hit', 'fb-miss']);
		expect(segments.map(s => s.share)).toEqual([70, 30]);
	});

	it('只有命中或只有未命中也算有效回退（另一段为 0 仍渲染）', () => {
		const {segments} = computeUsageSegments({lastCacheHitTokens: 500});
		expect(segments.map(s => s.value)).toEqual([500, 0]);
		const {segments: missOnly} = computeUsageSegments({lastCacheMissTokens: 500});
		expect(missOnly.map(s => s.value)).toEqual([0, 500]);
	});

	it('两者皆缺失 → 无分段（不渲染空条）', () => {
		const {segments} = computeUsageSegments({contextLimit: 100_000});
		expect(segments).toEqual([]);
	});

	it('输入超过窗口时剩余段钳到 0，不出现负值', () => {
		const {segments} = computeUsageSegments({
			contextLimit: 1_000,
			contextTokens: 2_000,
			lastCacheHitTokens: 1_500,
			lastCacheMissTokens: 500,
		});
		expect(segments.find(s => s.key === 'fb-rem')?.value).toBe(0);
	});
});

describe('computeUsageSegments — 优先级与健壮性', () => {
	it('权威段优先于回退段（breakdown 非空时忽略 last*）', () => {
		const {authoritative, segments} = computeUsageSegments({
			contextBreakdown: [row('system', 100)],
			contextLimit: 1_000,
			lastCacheHitTokens: 999,
			lastCacheMissTokens: 1,
		});
		expect(authoritative).toBe(true);
		expect(segments.map(s => s.key)).toEqual(['system-0']);
	});

	it('空 breakdown 数组走回退，不等价于「有权威段」', () => {
		const {authoritative} = computeUsageSegments({
			contextBreakdown: [],
			lastCacheHitTokens: 10,
		});
		expect(authoritative).toBe(false);
	});

	it('负数与 NaN 钳到 0（不渲染负宽度）', () => {
		const {segments} = computeUsageSegments({
			contextBreakdown: [row('system', -100), row('conversation', Number.NaN)],
			contextLimit: 1_000,
		});
		expect(segments.map(s => s.value)).toEqual([0, 0]);
	});

	it('contextLimit 为 0 / 负数视为未测量，不拿来当分母', () => {
		const {denominator} = computeUsageSegments({
			contextBreakdown: [row('system', 4_000)],
			contextLimit: 0,
		});
		expect(denominator).toBe(4_000);
	});
});

describe('segmentWidths — 渲染宽度钳制', () => {
	it('最窄 0.5%（保证可hover到），最宽 98%', () => {
		const {segments, denominator} = computeUsageSegments({
			contextBreakdown: [row('system', 1), row('conversation', 999_999)],
			contextLimit: 1_000_000,
		});
		expect(segmentWidths(segments, denominator)).toEqual([0.5, 98]);
	});

	it('分母为 0 时不产生 NaN / Infinity', () => {
		expect(segmentWidths([], 0)).toEqual([]);
		const widths = segmentWidths(
			[{key: 'a', value: 0, color: '#000', label: 'a', tokens: 0, share: 0}],
			0,
		);
		expect(widths.every(w => Number.isFinite(w))).toBe(true);
	});
});
