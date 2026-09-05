import {afterEach, describe, expect, it} from 'vitest';
import {highlightCode} from '@/lib/highlightClient';
import {isLayoutBusy, popLayoutBusy, pushLayoutBusy} from '@/lib/layoutBusy';

describe('highlightCode queue', () => {
	afterEach(() => {
		while (isLayoutBusy()) {
			popLayoutBusy();
		}
	});

	it('defers posts while layout is busy', async () => {
		pushLayoutBusy();
		let settled = false;
		const pending = highlightCode('javascript', 'const a = 1').then(html => {
			settled = true;
			return html;
		});
		await Promise.resolve();
		expect(settled).toBe(false);
		popLayoutBusy();
		await pending;
		expect(settled).toBe(true);
	});
});
