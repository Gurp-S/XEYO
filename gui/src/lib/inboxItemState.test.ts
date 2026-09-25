import {describe, expect, it} from 'vitest';
import {
	assignInboxQueuePositions,
	canMutateInboxItem,
} from './inboxItemState';

describe('canMutateInboxItem', () => {
	it.each(['queued', 'stuck'] as const)('allows %s items', state => {
		expect(canMutateInboxItem(state)).toBe(true);
	});

	it.each(['delivering', 'syncing'] as const)('locks %s items', state => {
		expect(canMutateInboxItem(state)).toBe(false);
	});
});

describe('assignInboxQueuePositions', () => {
	it('counts only messages that are waiting to be delivered', () => {
		const positioned = assignInboxQueuePositions([
			{queue_id: 'a', state: 'queued' as const},
			{queue_id: 'b', state: 'delivering' as const},
			{queue_id: 'c', state: 'stuck' as const},
			{queue_id: 'd', state: 'queued' as const},
			{queue_id: 'e', state: 'syncing' as const},
		]);

		expect(positioned.map(({position}) => position)).toEqual([1, 0, 0, 2, 0]);
	});
});
