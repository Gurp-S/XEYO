/**
 * activityHeatmap.test.ts — 热力图纯计算的硬账。
 *
 * 1. 分档不能被最大值绑架（本机一天 4,933 笔、另一天 8 笔，等分会把 99 % 压成同档）；
 * 2. 「没跑」「读不出」「还没到」是三种格子，值分别是 0 / null / future；
 * 3. 日格合计 == 网格 total == 累计 total（同一份数据三处必须对得上）；
 * 4. 不读时钟：今天由参数给。
 */
import {describe, expect, it} from 'vitest';
import type {LiveUsageDay} from '@/lib/api/liveUsage';
import {
	ACTIVITY_WEEKS,
	activityLevels,
	buildActivityGrid,
	buildCumulative,
	formatChineseTokens,
} from './activityHeatmap';

const day = (d: string, over: Partial<LiveUsageDay> = {}): LiveUsageDay => ({
	day: d,
	accepted: null,
	requests: 1,
	prompt_tokens: 1000,
	cache_hit: 500,
	cache_miss: 500,
	hit_rate: 0.5,
	c2_count: 0,
	output: 100,
	tokens: 1100,
	cost_cny: 0.1,
	sessions: 1,
	turns: 1,
	hour_counts: Array.from({length: 24}, () => 0),
	hour_unknown: 0,
	by_model: [],
	...over,
});

describe('formatChineseTokens', () => {
	it('万 / 亿折算，整数不写小数尾巴', () => {
		expect(formatChineseTokens(1_082_056_006)).toBe('10.8亿');
		expect(formatChineseTokens(100_000_000)).toBe('1亿');
		expect(formatChineseTokens(12_345)).toBe('1.2万');
		expect(formatChineseTokens(10_000)).toBe('1万');
		expect(formatChineseTokens(999)).toBe('999');
		expect(formatChineseTokens(0)).toBe('0');
	});

	it('读不出说"数据里没有"，不写 0（0 会被读成"这一天没跑"）', () => {
		expect(formatChineseTokens(null)).toBe('数据里没有');
		expect(formatChineseTokens(undefined)).toBe('数据里没有');
		expect(formatChineseTokens(Number.NaN)).toBe('数据里没有');
	});
});

describe('activityLevels', () => {
	it('全零 / 空 ⇒ null（没有可分档的值，界面不许画任何有色格）', () => {
		expect(activityLevels([])).toBeNull();
		expect(activityLevels([0, 0, null])).toBeNull();
	});

	it('分布塌成一点：那一格仍要落在最高档，不能因为三档相等掉到 3', () => {
		const cuts = activityLevels([0, 0, 5000])!;
		expect(cuts[2]).toBeLessThan(5000);
	});

	it('分位单调递增，且 0 值不参与分位', () => {
		const cuts = activityLevels([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100])!;
		const [a, b, c] = cuts;
		expect(a).toBeLessThan(b);
		expect(b).toBeLessThan(c);
	});
});

describe('buildActivityGrid · 每天', () => {
	// 10-01 是周五：同一周里 10-02/10-03 落在"还没到"那一档，三种格子才同时存在。
	const today = '2026-10-01';
	const days = [
		day('2026-09-29', {tokens: 9000}),
		day('2026-09-30', {tokens: 5000}),
		day('2026-10-01', {tokens: 100}),
	];

	it('列 = 53 周、每列 7 格，格子的日期连续且以周日开头', () => {
		const grid = buildActivityGrid(days, 'day', today);
		expect(grid.columns).toHaveLength(ACTIVITY_WEEKS);
		expect(grid.columns.every(c => c.length === 7)).toBe(true);
		// 每列第一格是周日（getUTCDay()==0）。
		for (const column of grid.columns) {
			expect(new Date(`${column[0]!.start}T00:00:00Z`).getUTCDay()).toBe(0);
		}
		// 最后一列覆盖到今天。
		expect(grid.columns[grid.columns.length - 1]!.some(c => c.start === today)).toBe(true);
	});

	it('三种格子：有活动 / 没跑 / 还没到，值分别是数字 / 0 / null+future', () => {
		const grid = buildActivityGrid(days, 'day', today);
		const flat = grid.columns.flat();
		const busy = flat.find(c => c.start === '2026-09-30')!;
		const idle = flat.find(c => c.start === '2026-09-20')!;
		const future = flat.find(c => c.start === '2026-10-02')!;

		expect(busy.value).toBe(5000);
		expect(busy.has_data).toBe(true);
		expect(busy.level).toBeGreaterThan(0);

		// 「没跑」是 0（灰格），不是 null（读不出）——两者混了就画不出"这台机器空着"。
		expect(idle.value).toBe(0);
		expect(idle.has_data).toBe(false);
		expect(idle.level).toBe(0);

		expect(future.future).toBe(true);
		expect(future.value).toBeNull();
		expect(future.level).toBe(0);
	});

	it('档位随值单调：最大的一天档位不低于最小的一天', () => {
		const grid = buildActivityGrid(days, 'day', today);
		const flat = grid.columns.flat();
		const l100 = flat.find(c => c.start === '2026-10-01')!.level;
		const l9000 = flat.find(c => c.start === '2026-09-29')!.level;
		expect(l9000).toBeGreaterThanOrEqual(l100);
		expect(l9000).toBe(4);
	});

	it('total 等于所有日格之和，也等于累计序列的总量', () => {
		const grid = buildActivityGrid(days, 'day', today);
		const sum = grid.columns
			.flat()
			.reduce((acc, c) => acc + (c.value ?? 0), 0);
		expect(grid.total).toBe(sum);
		expect(buildCumulative(days).total).toBe(sum);
		expect(grid.active_cells).toBe(3);
	});

	it('月份轴递增、不重复，且不落在月中', () => {
		const grid = buildActivityGrid(days, 'day', today);
		expect(grid.months.length).toBeGreaterThan(4);
		const columns = grid.months.map(m => m.column);
		expect(columns).toEqual([...columns].sort((a, b) => a - b));
		expect(new Set(columns).size).toBe(columns.length);
	});

	it('账本为空：整张图不画，而不是画 371 个假零', () => {
		const grid = buildActivityGrid([], 'day', today);
		expect(grid.columns).toEqual([]);
		expect(grid.total).toBe(0);
	});
});

describe('buildActivityGrid · 每周', () => {
	it('一列一格，值 = 该周日-周六 7 天之和', () => {
		const days = [
			day('2026-09-28', {tokens: 100}),
			day('2026-09-29', {tokens: 200}),
			day('2026-10-03', {tokens: 40}),
		];
		const grid = buildActivityGrid(days, 'week', '2026-10-03');
		expect(grid.columns.every(c => c.length === 1)).toBe(true);
		// 网格按周日开列：2026-09-27 是周日，那一周盖到 10-03，三天都在里面。
		const week = grid.columns.find(c => c[0]!.start === '2026-09-27')![0]!;
		expect(week.value).toBe(340);
		expect(week.days_with_data).toBe(3);
		expect(week.label).toContain('~');
	});
});

describe('buildCumulative', () => {
	it('单调不减，末值 = 总量；tokens 读不出的天不进合计', () => {
		const days = [
			day('2026-10-02', {tokens: 200}),
			day('2026-10-03', {tokens: null}),
			day('2026-10-01', {tokens: 100}),
		];
		const s = buildCumulative(days);
		expect(s.points.map(p => p.total)).toEqual([100, 300]);
		expect(s.total).toBe(300);
		expect(s.days_with_data).toBe(2);
		expect(s.days_without_tokens).toBe(1);
		expect(s.from).toBe('2026-10-01');
		expect(s.to).toBe('2026-10-02');
	});

	it('空账本：没有点、没有区间，不编一个 0 出来', () => {
		const s = buildCumulative([]);
		expect(s.points).toEqual([]);
		expect(s.total).toBe(0);
		expect(s.from).toBeNull();
		expect(s.to).toBeNull();
	});
});
