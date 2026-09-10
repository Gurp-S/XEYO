import {describe, expect, it} from 'vitest';
import {
	formatCacheHitPercent,
	formatTokenCount,
	formatUsageChipPreview,
} from './formatUsage';

/**
 * chip 文案契约（顶栏用量预览的对外口径，2026-09-09 钉死）。
 *
 * 参数固定为三个位置量：累计消耗 / 累计输出 / 窗口占用%。
 * 这三个数属于两类口径（账单类 vs 快照类），测试只保证「拼装规则」稳定，
 * 不保证三者语义一致——语义差异见 ChatHeader 注释与下方分段条契约。
 */
describe('formatUsageChipPreview（顶栏 chip 拼装规则）', () => {
	it('三值齐备：消耗 / 输出 · 占用%', () => {
		expect(formatUsageChipPreview(1_234, 456, '42.3')).toBe(
			'1.23k tok / 456 tok · 42.3%',
		);
	});

	it('累计输出缺失时省略中段，只留 消耗 · 占用%', () => {
		expect(formatUsageChipPreview(1_234, null, '42.3')).toBe('1.23k tok · 42.3%');
		expect(formatUsageChipPreview(1_234, undefined, '42.3')).toBe(
			'1.23k tok · 42.3%',
		);
	});

	it('累计消耗缺失显示破折号，不显示 0', () => {
		expect(formatUsageChipPreview(null, 456, '42.3')).toBe('— / 456 tok · 42.3%');
		expect(formatUsageChipPreview(undefined, null, '42.3')).toBe('— · 42.3%');
	});

	it('占用率未知时写「占用待确认」，不写 0%', () => {
		expect(formatUsageChipPreview(1_234, 456, null)).toBe(
			'1.23k tok / 456 tok · 占用待确认',
		);
		expect(formatUsageChipPreview(1_234, 456)).toBe(
			'1.23k tok / 456 tok · 占用待确认',
		);
	});

	it('累计消耗为 0 是有效值（区别于缺失）', () => {
		expect(formatUsageChipPreview(0, 0, '0.0')).toBe('0 tok / 0 tok · 0.0%');
	});

	it('NaN / Infinity 视为缺失（不渲染 NaN tok）', () => {
		expect(formatUsageChipPreview(Number.NaN, Number.NaN, null)).toBe(
			'— · 占用待确认',
		);
		expect(formatUsageChipPreview(Number.POSITIVE_INFINITY, 1, null)).toBe(
			'— / 1 tok · 占用待确认',
		);
	});
});

describe('formatTokenCount（单位与精度）', () => {
	it('千以下用原始整数 + tok', () => {
		expect(formatTokenCount(0)).toBe('0 tok');
		expect(formatTokenCount(999)).toBe('999 tok');
	});

	it('千位进位到 k（两位小数）', () => {
		expect(formatTokenCount(1_000)).toBe('1.00k tok');
		expect(formatTokenCount(1_234)).toBe('1.23k tok');
	});

	it('M / B / T 逐级进位', () => {
		expect(formatTokenCount(2_500_000)).toBe('2.50M tok');
		expect(formatTokenCount(3_000_000_000)).toBe('3.00B tok');
	});

	it('负数与非法值钳到 0（累计量不该出现负值）', () => {
		expect(formatTokenCount(-1)).toBe('0 tok');
		expect(formatTokenCount(Number.NaN)).toBe('0 tok');
	});
});

describe('formatCacheHitPercent（一位小数）', () => {
	it('无计费输入返回 null', () => {
		expect(formatCacheHitPercent(0, 0)).toBeNull();
	});

	it('全命中返回 100', () => {
		expect(formatCacheHitPercent(10_000, 0)).toBe('100');
	});

	it('常规命中率显示一位小数', () => {
		// 471808 / (471808 + 81756) ≈ 85.2%
		expect(formatCacheHitPercent(471_808, 81_756)).toBe('85.2');
		// 0 命中
		expect(formatCacheHitPercent(0, 6_831)).toBe('0.0');
		// 80%
		expect(formatCacheHitPercent(80, 20)).toBe('80.0');
	});

	it('一位小数撞 100% 时给高精度 99.9x，不谎报 100', () => {
		// 99.95% → 一位小数 100.0 → 高精度 < 100
		const high = formatCacheHitPercent(999_500, 500);
		expect(high).not.toBeNull();
		expect(high).not.toBe('100');
		expect(high).toMatch(/^99\.\d+$/);
	});

	it('99.x% 边界仍是常规一位小数，更接近全命中才走高精度', () => {
		// 99.4% → 一位小数 99.4（未撞 100）
		expect(formatCacheHitPercent(994_000, 6_000)).toBe('99.4');
		// 99.999% → 撞 100 → 高精度
		const near = formatCacheHitPercent(999_990, 10)!;
		expect(near.startsWith('99.9')).toBe(true);
	});

	it('写档计入未命中（DeepSeek 下 miss 已含 write）', () => {
		// 分母 = hit + miss（DeepSeek 无独立 write 桶）
		expect(formatCacheHitPercent(500, 500)).toBe('50.0');
	});
});
