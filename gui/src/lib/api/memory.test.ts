import {beforeEach, describe, expect, it, vi} from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('./core', () => ({fetchWithTimeout: request}));
vi.mock('@/lib/apiBase', () => ({apiUrl: (path: string) => path}));
import {syncUiThoughtsToServer} from './memory';

const thoughts = [{id: 'one', text: 'result', createdAt: 1000}];
describe('thought sync HTTP acknowledgement', () => {
	beforeEach(() => request.mockReset());
	it('distinguishes successful deduplication from transport and protocol failure', async () => {
		request.mockResolvedValueOnce({ok: true, json: async () => ({ok: true, written: 0})});
		expect(await syncUiThoughtsToServer('session', thoughts)).toBe(0);
		request.mockResolvedValueOnce({ok: false});
		expect(await syncUiThoughtsToServer('session', thoughts)).toBeNull();
		request.mockRejectedValueOnce(new Error('offline'));
		expect(await syncUiThoughtsToServer('session', thoughts)).toBeNull();
		request.mockResolvedValueOnce({ok: true, json: async () => ({written: 0})});
		expect(await syncUiThoughtsToServer('session', thoughts)).toBeNull();
	});
});
