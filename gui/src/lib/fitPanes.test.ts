import {describe, expect, it} from 'vitest';
import {shrinkOpenPanes} from '@/lib/fitPanes';

describe('shrinkOpenPanes', () => {
	it('keeps preferred widths when the row has room', () => {
		expect(shrinkOpenPanes(1200, 180, [248, 360, 248])).toEqual([
			248, 360, 248,
		]);
	});

	it('scales panes so chat min still fits', () => {
		const used = shrinkOpenPanes(800, 180, [248, 360, 248]);
		const sum = used.reduce((a, b) => a + b, 0);
		expect(sum).toBeCloseTo(620, 5);
		expect(used[1]).toBeGreaterThan(used[0]);
	});
});
