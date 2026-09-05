import {describe, expect, it} from 'vitest';
import {formatCacheHitPercent} from './formatUsage';

describe('formatCacheHitPercent（一位小数；口径对齐 DSH cacheHitPercent）', () => {
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

	it('与 DSH 语义一致：写档计入未命中（DeepSeek 下 miss 已含 write）', () => {
		// 分母 = hit + miss（DeepSeek 无独立 write 桶）
		expect(formatCacheHitPercent(500, 500)).toBe('50.0');
	});
});
