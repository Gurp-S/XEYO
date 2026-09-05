import {describe, expect, it} from 'vitest';
import {
	EMPTY_QUIPS,
	pickEmptyQuip,
	resetEmptyQuipState,
} from './emptyQuips';

describe('emptyQuips', () => {
	it('picks a known longer quip', () => {
		resetEmptyQuipState();
		const q = pickEmptyQuip(() => 0);
		expect(EMPTY_QUIPS).toContain(q);
		expect(q.length).toBeGreaterThan(15);
	});

	it('has a large pool to cut down repeats', () => {
		expect(EMPTY_QUIPS.length).toBeGreaterThanOrEqual(60);
		const unique = new Set(EMPTY_QUIPS);
		expect(unique.size).toBe(EMPTY_QUIPS.length);
	});

	it('avoids the immediately previous line', () => {
		resetEmptyQuipState();
		const first = pickEmptyQuip(() => 0);
		// 强制与 lastIndex (0) 相同槽位；picker 应跳开。
		const second = pickEmptyQuip(() => 0);
		expect(second).not.toBe(first);
	});
});
