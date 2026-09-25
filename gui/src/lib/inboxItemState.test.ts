import {describe, expect, it} from 'vitest';
import {canMutateInboxItem} from './inboxItemState';

describe('canMutateInboxItem', () => {
	it.each(['queued', 'stuck'] as const)('allows %s items', state => {
		expect(canMutateInboxItem(state)).toBe(true);
	});

	it.each(['delivering', 'syncing'] as const)('locks %s items', state => {
		expect(canMutateInboxItem(state)).toBe(false);
	});
});
