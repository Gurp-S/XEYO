import {beforeEach, expect, it, vi} from 'vitest';
import {ensureSessionHistory} from './sessionHistoryHydration';
import type {ChatState} from './preStoreHelpers';
import type {ChatHistoryState} from '@/lib/types';

const disk = vi.hoisted(() => vi.fn());
vi.mock('@/lib/db', async original => ({...await original<typeof import('@/lib/db')>(), loadChatHistoryState: disk}));
beforeEach(() => vi.resetAllMocks());
const saved = {activeBranch: {branchId: 'fork', backendSessionId: 'fork-backend'}, archivedBranches: []} as unknown as ChatHistoryState;
function fixture() {
	let state = {sessions: [{id: 'gui'}], historyById: {}, sessionStreams: {}} as unknown as ChatState;
	const get = () => state;
	const set: Parameters<typeof ensureSessionHistory>[0] = update => {state = {...state, ...typeof update === 'function' ? update(state) : update};};
	return {get, set};
}
function deferred<T>() {
	let resolve!: (value: T) => void; const promise = new Promise<T>(done => {resolve = done;});
	return {promise, resolve};
}

it('shares a pending identity restoration and restores the backend before callers continue', async () => {
	const f = fixture(); const read = deferred<ChatHistoryState>(); disk.mockReturnValueOnce(read.promise);
	const first = ensureSessionHistory(f.set, f.get, 'gui'); const second = ensureSessionHistory(f.set, f.get, 'gui');
	expect(disk).toHaveBeenCalledOnce(); read.resolve(saved);
	expect(await first).toBe(true); expect(await second).toBe(true);
	expect(f.get().historyById.gui?.activeBranch.backendSessionId).toBe('fork-backend');
});

it.each(['branch', 'turn'])('a late identity restoration cannot overwrite a new %s', async scope => {
	const f = fixture(); const read = deferred<ChatHistoryState>(); disk.mockReturnValueOnce(read.promise);
	const work = ensureSessionHistory(f.set, f.get, 'gui');
	if (scope === 'branch') f.set({historyById: {gui: {activeBranch: {branchId: 'new', backendSessionId: 'new-backend'}}} as never});
	else f.set({sessionStreams: {gui: {abortRef: new AbortController(), turnId: 'new-turn'}} as never});
	const before = f.get(); read.resolve(saved);
	expect(await work).toBe(false); expect(f.get()).toBe(before);
});
