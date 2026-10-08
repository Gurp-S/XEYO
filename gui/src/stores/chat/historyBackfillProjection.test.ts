import {expect, it} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {projectHistoryBackfill} from './historyBackfillProjection';

const row = (id: string): ChatMessage => ({id, role: 'user', text: id, createdAt: 1});

it('applies canonical removals and retains local changes made during the read', () => {
	const snapshot = [row('u'), {...row('legacy'), role: 'assistant' as const}];
	const pending = {...row('pending'), localUndelivered: true};
	const loaded = [row('u'), {...row('answer'), role: 'assistant' as const}];
	const result = projectHistoryBackfill(snapshot, [...snapshot, pending], loaded);
	expect(result.map(message => message.id)).toEqual(['u', 'answer', 'pending']);
	expect(result[2]?.localUndelivered).toBe(true);
});
