import {beforeEach, describe, expect, it} from 'vitest';
import {clearRoundHeight, setRoundHeight} from './roundHeights';
import {
	anchorScrollTop,
	captureViewportAnchor,
	computeRoundPrefix,
	mergeIntervals,
	roundIndexAtOffset,
	roundWindowFor,
} from './roundVirtual';

const ids = ['r1', 'r2', 'r3', 'r4', 'r5'];

describe('roundVirtual', () => {
	beforeEach(() => {
		for (const id of ids) {
			clearRoundHeight(id);
		}
	});

	it('computeRoundPrefix sums cached heights with the 120 default', () => {
		setRoundHeight('r1', 100);
		setRoundHeight('r2', 50);
		expect(computeRoundPrefix(ids)).toEqual([0, 100, 150, 270, 390, 510]);
	});

	it('computeRoundPrefix on empty ids yields [0]', () => {
		expect(computeRoundPrefix([])).toEqual([0]);
	});

	it('roundIndexAtOffset finds the covering round and clamps past the end', () => {
		setRoundHeight('r1', 100);
		const prefix = computeRoundPrefix(ids);
		expect(roundIndexAtOffset(prefix, 0)).toBe(0);
		expect(roundIndexAtOffset(prefix, 99)).toBe(0);
		expect(roundIndexAtOffset(prefix, 100)).toBe(1);
		expect(roundIndexAtOffset(prefix, 219)).toBe(1);
		expect(roundIndexAtOffset(prefix, 220)).toBe(2);
		// 总高 580 → 越界返回 count（=5）
		expect(roundIndexAtOffset(prefix, 580)).toBe(5);
		expect(roundIndexAtOffset(prefix, 99999)).toBe(5);
	});

	it('roundWindowFor covers the viewport plus overscan', () => {
		for (const id of ids) {
			setRoundHeight(id, 200);
		}
		const prefix = computeRoundPrefix(ids);
		expect(roundWindowFor(prefix, 0, 200, 100)).toEqual({start: 0, end: 2});
		expect(roundWindowFor(prefix, 400, 200, 0)).toEqual({start: 2, end: 4});
		expect(roundWindowFor(prefix, 800, 200, 0)).toEqual({start: 4, end: 5});
	});

	it('roundWindowFor handles empty and zero viewport inputs', () => {
		expect(roundWindowFor([0], 100, 200, 50)).toEqual({start: 0, end: 0});
		for (const id of ids) {
			setRoundHeight(id, 200);
		}
		const prefix = computeRoundPrefix(ids);
		// viewport 0 → 兜底 720：bottom = 400+720 越过末尾 → 到 count
		expect(roundWindowFor(prefix, 400, 0, 0)).toEqual({start: 2, end: 5});
	});

	it('mergeIntervals merges overlapping and keeps disjoint segments sorted', () => {
		expect(
			mergeIntervals([
				{start: 3, end: 5},
				{start: 0, end: 2},
				{start: 1, end: 4},
			]),
		).toEqual([{start: 0, end: 5}]);
		expect(
			mergeIntervals([
				{start: 0, end: 1},
				{start: 3, end: 4},
			]),
		).toEqual([
			{start: 0, end: 1},
			{start: 3, end: 4},
		]);
		expect(mergeIntervals([])).toEqual([]);
	});

	it('captureViewportAnchor records the covering round and in-round fraction', () => {
		for (const id of ids) {
			setRoundHeight(id, 200);
		}
		const prefix = computeRoundPrefix(ids); // [0,200,400,600,800,1000]
		// scrollTop 落在 round2（400..600）内 150px 处。
		expect(captureViewportAnchor(prefix, 550)).toEqual({index: 2, frac: 0.75});
		// 顶边：位于 round0 起点。
		expect(captureViewportAnchor(prefix, 0)).toEqual({index: 0, frac: 0});
	});

	it('captureViewportAnchor returns null when scrollTop is past the estimated end', () => {
		for (const id of ids) {
			setRoundHeight(id, 200);
		}
		const prefix = computeRoundPrefix(ids); // 总高 1000
		// 越过末尾 → 无有效锚点，避免越界补偿把用户拽飞。
		expect(captureViewportAnchor(prefix, 1000)).toBeNull();
		expect(captureViewportAnchor(prefix, 99999)).toBeNull();
	});

	it('anchorScrollTop is identity when the prefix is unchanged', () => {
		for (const id of ids) {
			setRoundHeight(id, 200);
		}
		const prefix = computeRoundPrefix(ids);
		const anchor = captureViewportAnchor(prefix, 550)!;
		expect(anchorScrollTop(prefix, anchor)).toBe(550);
	});

	it('anchorScrollTop keeps the same content point when heights above grow', () => {
		for (const id of ids) {
			setRoundHeight(id, 200);
		}
		// 旧前缀：[0,200,400,600,800,1000]，锚点 = round2 @ 0.75（内容点 550）。
		const oldPrefix = computeRoundPrefix(ids);
		const anchor = captureViewportAnchor(oldPrefix, 550)!;
		// round0 实测长高 200→580：之后坐标 +380，同一内容点由 550 移到 930。
		const newPrefix = [0, 580, 780, 980, 1180, 1380];
		expect(anchorScrollTop(newPrefix, anchor)).toBe(930);
	});
});
