import {describe, expect, it} from 'vitest';
import {
	clearRoundHeight,
	getRoundHeight,
	getRoundHeightOrDefault,
	setRoundHeight,
} from './roundHeights';

describe('roundHeights', () => {
	it('stores rounded positive heights and defaults to 120', () => {
		clearRoundHeight('r1');
		expect(getRoundHeightOrDefault('r1')).toBe(120);
		setRoundHeight('r1', 256.7);
		expect(getRoundHeight('r1')).toBe(257);
		setRoundHeight('r1', 0);
		expect(getRoundHeight('r1')).toBe(257);
		clearRoundHeight('r1');
		expect(getRoundHeight('r1')).toBeUndefined();
	});
});
