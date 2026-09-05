import {describe, expect, it} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {
	collectMessagesToPersist,
	messagePersistFingerprint,
	seedPersistFingerprints,
} from '@/lib/messagePersist';

function msg(id: string, text: string, extra?: Partial<ChatMessage>): ChatMessage {
	return {
		id,
		role: 'assistant',
		text,
		createdAt: 1,
		...extra,
	};
}

describe('messagePersist', () => {
	it('fingerprint changes when text grows', () => {
		const a = messagePersistFingerprint(msg('a', 'hello'));
		const b = messagePersistFingerprint(msg('a', 'hello world'));
		expect(a).not.toBe(b);
	});

	it('collectMessagesToPersist only returns changed messages', () => {
		const base = [msg('u1', 'hi', {role: 'user'}), msg('a1', 'partial')];
		const fps = seedPersistFingerprints(base);
		const updated = [
			base[0]!,
			msg('a1', 'partial answer'),
			msg('a2', 'new'),
		];
		const {toWrite} = collectMessagesToPersist(updated, fps);
		expect(toWrite.map(m => m.id)).toEqual(['a1', 'a2']);
	});

	it('collectMessagesToPersist skips unchanged messages', () => {
		const base = [msg('a1', 'done')];
		const fps = seedPersistFingerprints(base);
		const {toWrite} = collectMessagesToPersist(base, fps);
		expect(toWrite).toEqual([]);
	});
});
