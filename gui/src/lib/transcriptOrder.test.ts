import {expect, it} from 'vitest';
import {mergeTranscript} from './transcriptOrder';
import type {ChatMessage} from './types';

const user: ChatMessage = {id: 'input', role: 'user', text: 'pending', createdAt: 1};

it('preserves retained input markers when a merged backfill is projected again', () => {
	const retained = {...user, localUndelivered: true};
	const queued = {...user, id: 'queued', queueState: 'queued' as const};
	const result = mergeTranscript([retained, queued], [retained, queued]);
	expect(result[0]?.localUndelivered).toBe(true);
	expect(result[1]?.queueState).toBe('queued');
});

it('clears retained input markers only when a delivered row arrives', () => {
	const result = mergeTranscript([{...user, localUndelivered: true, queueState: 'queued'}], [user]);
	expect(result[0]?.localUndelivered).toBeUndefined();
	expect(result[0]?.queueState).toBeUndefined();
});
