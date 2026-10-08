import {beforeEach, expect, it, vi} from 'vitest';
import {createInboxSlice} from './inboxSlice';
import type {ChatState} from './preStoreHelpers';

const io = vi.hoisted(() => ({edit: vi.fn(), cancel: vi.fn(), update: vi.fn(), remove: vi.fn()}));
vi.mock('@/lib/api', async original => ({...await original<typeof import('@/lib/api')>(), editInboxItem: io.edit, cancelInboxItem: io.cancel}));
vi.mock('@/lib/db', async original => ({...await original<typeof import('@/lib/db')>(), updateMessageText: io.update, deleteMessageForSession: io.remove}));
beforeEach(() => {vi.resetAllMocks(); io.update.mockResolvedValue(undefined); io.remove.mockResolvedValue(undefined);});
function fixture() {
	let state = {sessions: [{id: 'gui'}], historyById: {gui: {activeBranch: {branchId: 'root', backendSessionId: 'old'}}},
		inboxBySession: {gui: [{queue_id: 'q', message_id: 'shared', text: 'old', state: 'queued'}]},
		messagesById: {gui: [{id: 'shared', role: 'user', text: 'old', createdAt: 1, queueState: 'queued'}]},
	} as unknown as ChatState;
	const get = () => state;
	const set = (patch: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => {state = {...state, ...typeof patch === 'function' ? patch(state) : patch};};
	return {get, set, slice: createInboxSlice(set, get), branch: () => set({historyById: {gui: {activeBranch: {branchId: 'fork', backendSessionId: 'new'}}} as never,
		messagesById: {gui: [{id: 'shared', role: 'user', text: 'NEW BRANCH', createdAt: 2}]}, inboxBySession: {gui: []}})};
}
function deferred() {let resolve!: (ok: boolean) => void; const promise = new Promise<boolean>(done => {resolve = done;}); return {promise, resolve};}

it.each(['edit', 'cancel'] as const)('late %s receipt cannot alter a new branch or write it to storage', async action => {
	const f = fixture(); const response = deferred(); io[action].mockReturnValue(response.promise);
	const work = action === 'edit' ? f.slice.editInboxItem('gui', 'q', 'changed') : f.slice.cancelInboxItem('gui', 'q');
	f.branch(); const before = f.get(); response.resolve(true); await work;
	expect(f.get()).toBe(before); expect(io.update).not.toHaveBeenCalled(); expect(io.remove).not.toHaveBeenCalled();
});

it.each(['edit', 'cancel'] as const)('%s database write is scoped after a delayed DB open', async action => {
	const f = fixture(); io[action].mockResolvedValue(true);
	await (action === 'edit' ? f.slice.editInboxItem('gui', 'q', 'changed') : f.slice.cancelInboxItem('gui', 'q'));
	const writer = action === 'edit' ? io.update : io.remove;
	const guard = writer.mock.calls[0]?.at(-1);
	expect(typeof guard).toBe('function'); expect(guard()).toBe(true);
	f.branch(); expect(guard()).toBe(false);
});
