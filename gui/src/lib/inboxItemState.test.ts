import {describe, expect, it} from 'vitest';
import {
	assignInboxQueuePositions,
	canMutateInboxItem,
	prioritizeInboxPreview,
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

describe('prioritizeInboxPreview', () => {
	it('keeps actionable and in-flight items ahead of transcript-sync receipts', () => {
		const sorted = prioritizeInboxPreview([
			{queue_id: 'receipt', state: 'syncing' as const},
			{queue_id: 'queue-a', state: 'queued' as const},
			{queue_id: 'retry', state: 'stuck' as const},
			{queue_id: 'delivery', state: 'delivering' as const},
			{queue_id: 'queue-b', state: 'queued' as const},
		]);

		expect(sorted.map(({queue_id}) => queue_id)).toEqual([
			'queue-a',
			'queue-b',
			'retry',
			'delivery',
			'receipt',
		]);
	});
});
