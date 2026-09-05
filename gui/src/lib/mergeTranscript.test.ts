import {describe, expect, it} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {
	collectSyncableThoughts,
	isSyncableThought,
	markThoughtFinalized,
	markThoughtStreaming,
	mergeTranscriptWithLocalThoughts,
} from '@/lib/mergeTranscript';

function thought(
	id: string,
	text: string,
	createdAt: number,
	thoughtMs?: number,
): ChatMessage {
	return {
		id,
		role: 'assistant',
		text,
		isThought: true,
		thoughtMs,
		createdAt,
	};
}

describe('mergeTranscript', () => {
	it('isSyncableThought excludes in-flight streaming thoughts', () => {
		markThoughtStreaming('thought-s1-1');
		expect(isSyncableThought(thought('thought-s1-1', 'live', 100))).toBe(
			false,
		);
		markThoughtFinalized('thought-s1-1');
		expect(isSyncableThought(thought('thought-s1-1', 'live', 100))).toBe(
			true,
		);
		expect(
			isSyncableThought(thought('thought-stream-s1', 'legacy', 100)),
		).toBe(false);
		expect(isSyncableThought(thought('thought-abc', 'done', 100))).toBe(true);
	});

	it('collectSyncableThoughts keeps finalized thoughts only', () => {
		markThoughtStreaming('thought-s1-1');
		const msgs: ChatMessage[] = [
			thought('thought-s1-1', 'streaming', 50),
			thought('thought-1', 'reason A', 100, 500),
			{id: 'u1', role: 'user', text: 'hi', createdAt: 80},
		];
		expect(collectSyncableThoughts(msgs)).toEqual([
			{id: 'thought-1', text: 'reason A', thoughtMs: 500, createdAt: 100},
		]);
		markThoughtFinalized('thought-s1-1');
	});

	it('mergeTranscriptWithLocalThoughts inserts missing thoughts by createdAt', () => {
		const server: ChatMessage[] = [
			{id: 'u1', role: 'user', text: 'hi', createdAt: 100},
			{id: 'a1', role: 'assistant', text: 'answer', createdAt: 300},
		];
		const local: ChatMessage[] = [
			...server,
			thought('thought-1', 'thinking…', 200, 1200),
		];
		const merged = mergeTranscriptWithLocalThoughts(server, local);
		expect(merged.map(m => m.id)).toEqual(['u1', 'thought-1', 'a1']);
		expect(merged[1]?.isThought).toBe(true);
	});

	it('mergeTranscriptWithLocalThoughts skips thoughts already on server', () => {
		const server: ChatMessage[] = [
			{id: 'u1', role: 'user', text: 'hi', createdAt: 100},
			thought('thought-1', 'from server', 200),
		];
		const local: ChatMessage[] = [
			...server,
			thought('thought-2', 'local only', 250),
		];
		const merged = mergeTranscriptWithLocalThoughts(server, local);
		expect(merged.map(m => m.id)).toEqual(['u1', 'thought-1', 'thought-2']);
	});
});
