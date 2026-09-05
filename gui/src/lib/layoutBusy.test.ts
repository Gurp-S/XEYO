import {afterEach, describe, expect, it} from 'vitest';
import {
	isLayoutBusy,
	popLayoutBusy,
	pushLayoutBusy,
	subscribeLayoutBusy,
} from '@/lib/layoutBusy';

describe('layoutBusy', () => {
	afterEach(() => {
		while (isLayoutBusy()) {
			popLayoutBusy();
		}
	});
	it('nests push/pop and notifies on the edges', () => {
		const seen: boolean[] = [];
		const stop = subscribeLayoutBusy(v => {
			seen.push(v);
		});
		expect(isLayoutBusy()).toBe(false);
		pushLayoutBusy();
		expect(isLayoutBusy()).toBe(true);
		pushLayoutBusy();
		expect(isLayoutBusy()).toBe(true);
		popLayoutBusy();
		expect(isLayoutBusy()).toBe(true);
		popLayoutBusy();
		expect(isLayoutBusy()).toBe(false);
		expect(seen).toEqual([true, false]);
		stop();
	});
});
