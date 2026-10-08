import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {ChatMessage} from '@/lib/types';

const db = vi.hoisted(() => ({patch: vi.fn(), replace: vi.fn()}));
vi.mock('@/lib/db', () => ({patchMessages: db.patch, replaceMessages: db.replace}));
vi.mock('./streamHelpers', () => ({scheduleThoughtSync: vi.fn(), flushThoughtSync: vi.fn()}));
import {createStreamPersistence} from './streamPersistence';

const row = (text: string, id = 'm'): ChatMessage => ({id, role: 'assistant', text, createdAt: 1});
function controller(seedMessages: ChatMessage[] = []) {
	let currentMessages = seedMessages;
	const persistence = createStreamPersistence({get: (() => ({sessions: [{id: 's'}], historyById: {}, messagesById: {s: currentMessages}})) as never,
		sessionId: 's', backendSessionId: 's', smoothStream: () => false, seedMessages});
	return {...persistence,
		write: (messages: ChatMessage[]) => {currentMessages = messages; persistence.write(messages);},
		onExit: (messages: ChatMessage[]) => {currentMessages = messages; persistence.onExit(messages);},
		setSnapshot: (messages: ChatMessage[]) => {currentMessages = messages;},
	};
}
async function settle() {
	for (let i = 0; i < 12; i++) await Promise.resolve();
}

describe('stream persistence successful commit', () => {
	beforeEach(() => {db.patch.mockReset().mockResolvedValue(undefined); db.replace.mockReset().mockResolvedValue(undefined);});
	it('retries the same snapshot after a failed patch', async () => {
		db.patch.mockRejectedValueOnce(new Error('storage unavailable'));
		const p = controller(); const messages = [row('answer')];
		p.write(messages); await settle(); p.write(messages); await settle();
		expect(db.patch).toHaveBeenCalledTimes(2);
		p.write(messages); await settle(); expect(db.patch).toHaveBeenCalledTimes(2);
	});
	it('retries a failed replacement on exit', async () => {
		db.replace.mockRejectedValueOnce(new Error('storage unavailable'));
		const p = controller([row('one'), row('two', 'n')]);
		p.write([row('one')]); await settle(); p.onExit([row('one')]); await settle();
		expect(db.replace).toHaveBeenCalledTimes(2);
	});
	it('serializes writes and coalesces pending snapshots to the latest', async () => {
		let finish!: () => void;
		db.patch.mockImplementationOnce(() => new Promise<void>(resolve => {finish = resolve;}));
		const p = controller(); p.write([row('one')]); await settle();
		p.write([row('two')]); p.write([row('three')]);
		expect(db.patch).toHaveBeenCalledTimes(1);
		finish(); await settle();
		expect(db.patch).toHaveBeenCalledTimes(2);
		expect(db.patch.mock.calls[1]![1]).toEqual([row('three')]);
	});
	it('replaces when IDs are removed even if total length stays equal', async () => {
		const p = controller([row('old')]); p.write([row('new', 'n')]); await settle();
		expect(db.replace).toHaveBeenCalledWith('s', [row('new', 'n')], expect.any(Function));
	});
	it('writes the latest snapshot if the in-flight write fails', async () => {
		let fail!: (error: Error) => void;
		db.patch.mockImplementationOnce(() => new Promise<void>((_, reject) => {fail = reject;}));
		const p = controller(); p.write([row('one')]); await settle();
		p.write([row('latest')]); fail(new Error('storage unavailable')); await settle();
		expect(db.patch).toHaveBeenCalledTimes(2);
		expect(db.patch.mock.calls[1]![1]).toEqual([row('latest')]);
		p.write([row('latest')]); await settle(); expect(db.patch).toHaveBeenCalledTimes(2);
	});
	it('an old turn cannot replay its pending snapshot after canonical queue backfill', async () => {
		let finish!: () => void;
		db.patch.mockImplementationOnce(() => new Promise<void>(resolve => {finish = resolve;}));
		const p = controller(); p.write([row('partial')]); await settle();
		p.write([row('old tail')]);
		p.setSnapshot([row('canonical'), row('next turn', 'next')]);
		finish(); await settle();
		expect(db.patch.mock.calls[1]![1]).toEqual([row('canonical'), row('next turn', 'next')]);
	});
	it('a database operation delayed before opening its transaction loses ownership after backfill', async () => {
		const p = controller(); p.write([row('old')]); await settle();
		const isCurrent = db.patch.mock.calls[0]![2] as () => boolean;
		expect(isCurrent()).toBe(true);
		p.setSnapshot([row('canonical')]);
		expect(isCurrent()).toBe(false);
	});
});
