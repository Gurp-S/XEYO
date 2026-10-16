import {describe, expect, it, vi} from 'vitest';
import {createThoughtSync, type SyncThought} from './thoughtSync';

const thought = (id: string): SyncThought => ({id, text: id, createdAt: 1});

describe('thought acknowledgement', () => {
	it('chunks large histories to the server limit and retries only unacknowledged rows', async () => {
		const send = vi.fn().mockResolvedValueOnce(500).mockResolvedValueOnce(null).mockResolvedValue(0);
		const sync = createThoughtSync(send);
		const rows = Array.from({length: 1001}, (_, i) => thought(String(i)));
		await sync('session', rows);
		await sync('session', rows);
		await sync('session', rows);
		expect(send.mock.calls.map(args => args[1].length)).toEqual([500, 500, 500, 1]);
		const acknowledged = [...send.mock.calls[0][1], ...send.mock.calls[2][1], ...send.mock.calls[3][1]];
		expect(new Set(acknowledged.map(t => t.id)).size).toBe(1001);
	});
	it('sends only new thoughts and treats zero written as successful deduplication', async () => {
		const send = vi.fn(async () => 0);
		const sync = createThoughtSync(send);
		await sync('session', [thought('one')]);
		await sync('session', [thought('one'), thought('two')]);
		await sync('session', [thought('one'), thought('two')]);
		expect(send.mock.calls.map(args => (args as unknown as [string, SyncThought[]])[1].map(t => t.id))).toEqual([['one'], ['two']]);
	});
	it('retries failed requests without marking them acknowledged', async () => {
		const send = vi.fn().mockResolvedValueOnce(null).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(1);
		const sync = createThoughtSync(send);
		await sync('session', [thought('one')]);
		await sync('session', [thought('one')]);
		await sync('session', [thought('one')]);
		await sync('session', [thought('one')]);
		expect(send).toHaveBeenCalledTimes(3);
	});
	it('serializes overlapping flushes and retains thoughts added during a request', async () => {
		let finish!: (n: number) => void;
		const send = vi.fn().mockImplementationOnce(() => new Promise<number>(resolve => {finish = resolve;})).mockResolvedValue(1);
		const sync = createThoughtSync(send);
		const first = sync('session', [thought('one')]);
		const next = sync('session', [thought('one'), thought('two')]);
		expect(send).toHaveBeenCalledTimes(1);
		finish(1);
		await Promise.all([first, next]);
		expect(send.mock.calls[1]?.[1]).toEqual([thought('two')]);
	});
	it('keeps acknowledgement identity per backend session', async () => {
		const send = vi.fn(async () => 1);
		const sync = createThoughtSync(send);
		await sync('first', [thought('one')]);
		await sync('second', [thought('one')]);
		expect(send).toHaveBeenCalledTimes(2);
	});
	it('honors a final flush received while an unsuccessful request is in flight', async () => {
		let finish!: (n: null) => void;
		const send = vi.fn().mockImplementationOnce(() => new Promise(resolve => {finish = resolve;})).mockResolvedValue(null);
		const sync = createThoughtSync(send);
		const first = sync('session', [thought('one')]);
		const final = sync('session', [thought('one')]);
		finish(null);
		await Promise.all([first, final]);
		expect(send).toHaveBeenCalledTimes(2);
		send.mockResolvedValue(1);
		await sync('session', [thought('one')]);
		await sync('session', [thought('one')]);
		expect(send).toHaveBeenCalledTimes(3);
	});
});
