import {describe, expect, it} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {
	collectMessagesToPersist,
	seedPersistedMessages,
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
	it('persists equal-length edits outside the last 48 characters', () => {
		const before = msg('m', 'old' + 'x'.repeat(100));
		const after = {...before, text: 'new' + 'x'.repeat(100)};
		expect(collectMessagesToPersist([after], seedPersistedMessages([before])).toWrite).toEqual([after]);
	});
	it('persists equal-length tool argument changes', () => {
		const before = msg('m', 'done', {toolInput: '{"path":"a.py"}'});
		const after = {...before, toolInput: '{"path":"b.py"}'};
		expect(collectMessagesToPersist([after], seedPersistedMessages([before])).toWrite).toEqual([after]);
	});
	it('persists metadata but ignores runtime queue state', () => {
		const before = msg('m', 'done', {mediaRefs: ['old'], checkpointId: 'old'});
		const after = {...before, mediaRefs: ['new'], checkpointId: 'new'};
		expect(collectMessagesToPersist([after], seedPersistedMessages([before])).toWrite).toEqual([after]);
		expect(collectMessagesToPersist([{...before, queueState: 'queued'}], seedPersistedMessages([before])).toWrite).toEqual([]);
	});
	it('keeps saved snapshots independent of later in-place media edits', () => {
		const before = msg('m', 'done', {mediaRefs: ['old']});
		const saved = seedPersistedMessages([before]);
		before.mediaRefs![0] = 'new';
		expect(collectMessagesToPersist([before], saved).toWrite).toEqual([before]);
	});
	it('compares copies precisely and catches separator collisions', () => {
		const before = msg('m', 'done', {toolName: 'a|b', toolStatus: 'done'});
		expect(collectMessagesToPersist([{...before}], seedPersistedMessages([before])).toWrite).toEqual([]);
		const after = {...before, reasoningBefore: 'new reasoning', createdAt: 2, toolUseId: 'call-new'};
		expect(collectMessagesToPersist([after], seedPersistedMessages([before])).toWrite).toEqual([after]);
	});
	it('persists growing text', () => {
		const before = msg('a', 'hello');
		const after = msg('a', 'hello world');
		expect(collectMessagesToPersist([after], seedPersistedMessages([before])).toWrite).toEqual([after]);
	});

	it('collectMessagesToPersist only returns changed messages', () => {
		const base = [msg('u1', 'hi', {role: 'user'}), msg('a1', 'partial')];
		const fps = seedPersistedMessages(base);
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
		const fps = seedPersistedMessages(base);
		const {toWrite} = collectMessagesToPersist(base, fps);
		expect(toWrite).toEqual([]);
	});
});
