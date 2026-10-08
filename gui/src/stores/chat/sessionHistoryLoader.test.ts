import {beforeEach, expect, it, vi} from 'vitest';
import type {ChatHistoryState, ChatMessage} from '@/lib/types';
import {loadSessionMessagesWithBackfill} from './preStoreHelpers';
import {rememberTranscriptSnapshot} from '@/lib/transcriptSnapshot';

const transport = vi.hoisted(() => ({server: vi.fn(), local: vi.fn(), replace: vi.fn(), backup: vi.fn(), task: vi.fn()}));
vi.mock('@/lib/api', async original => ({...await original<typeof import('@/lib/api')>(), loadServerSessionMessages: transport.server, fetchSessionTask: transport.task}));
vi.mock('@/lib/db', async original => ({...await original<typeof import('@/lib/db')>(), loadMessages: transport.local, replaceMessages: transport.replace, replaceMessagesWithHistoryBackup: transport.backup}));
beforeEach(() => {vi.resetAllMocks(); transport.local.mockResolvedValue([]);});
const row = (id: string): ChatMessage => ({id, role: 'user', text: id, createdAt: 1});
const history = (backend: string) => ({gui: {activeBranch: {branchId: 'root', backendSessionId: backend}}} as unknown as Record<string, ChatHistoryState>);
function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>(done => {resolve = done;});
	return {promise, resolve};
}

it('repairs a saved wrong order even when server and local row counts match', async () => {
	transport.local.mockResolvedValue([row('u1'), row('u2'), row('a1'), row('a2')]);
	transport.server.mockResolvedValue([row('u1'), row('a1'), row('u2'), row('a2')]);
	expect((await loadSessionMessagesWithBackfill('gui', history('old'))).map(m => m.id)).toEqual(['u1', 'a1', 'u2', 'a2']);
	expect(transport.replace).toHaveBeenCalled();
});

it('a new backend load does not reuse the old branch request or persist its late result', async () => {
	const old = deferred<ChatMessage[]>(); transport.server.mockImplementation((id: string) => id === 'old' ? old.promise : Promise.resolve([row('new')]));
	const oldWork = loadSessionMessagesWithBackfill('gui', history('old'));
	await vi.waitFor(() => expect(transport.server).toHaveBeenCalledWith('old'));
	const newWork = loadSessionMessagesWithBackfill('gui', history('new'));
	await vi.waitFor(() => expect(transport.server).toHaveBeenCalledWith('new'));
	expect((await newWork).map(m => m.id)).toEqual(['new']);
	old.resolve([row('old')]); await oldWork;
	expect(transport.replace.mock.calls.some(call => (call[1] as ChatMessage[]).some(m => m.id === 'old'))).toBe(false);
});

it('does not persist backfill after the caller loses its turn ownership', async () => {
	const server = deferred<ChatMessage[]>(); transport.server.mockReturnValue(server.promise);
	let current = true;
	const work = loadSessionMessagesWithBackfill('gui', history('old'), {isCurrent: () => current});
	await vi.waitFor(() => expect(transport.server).toHaveBeenCalled());
	current = false; server.resolve([row('old')]); await work;
	expect(transport.replace).not.toHaveBeenCalled();
});

it('a delayed old DB write loses ownership even after the newer load completes', async () => {
	const write = deferred<void>(); transport.replace.mockImplementationOnce(() => write.promise);
	transport.server.mockResolvedValueOnce([row('old')]).mockResolvedValueOnce([row('new')]);
	const oldWork = loadSessionMessagesWithBackfill('gui', history('old'));
	await vi.waitFor(() => expect(transport.replace).toHaveBeenCalled());
	const oldGuard = transport.replace.mock.calls[0]![2] as () => boolean;
	expect(oldGuard()).toBe(true);
	expect((await loadSessionMessagesWithBackfill('gui', history('new'))).map(m => m.id)).toEqual(['new']);
	expect(oldGuard()).toBe(false); write.resolve(); await oldWork;
});

it('retains queued input while correcting delivered transcript order', async () => {
	transport.local.mockResolvedValue([row('u1'), row('u2'), row('a1'), {...row('queued'), queueState: 'queued'}]);
	transport.server.mockResolvedValue([row('u1'), row('a1'), row('u2')]);
	expect((await loadSessionMessagesWithBackfill('gui', history('old'))).map(m => m.id)).toEqual(['u1', 'a1', 'u2', 'queued']);
});

it('does not truncate a locally retained answer when the server contains only a prefix', async () => {
	transport.local.mockResolvedValue([row('user'), row('answer')]); transport.server.mockResolvedValue([row('user')]);
	expect((await loadSessionMessagesWithBackfill('gui', history('old'))).map(m => m.id)).toEqual(['user', 'answer']);
});

it('retains undelivered input when later server history grows', async () => {
	transport.local.mockResolvedValue([row('u1'), row('a1'), {...row('held'), localUndelivered: true}]);
	transport.server.mockResolvedValue([row('u1'), row('a1'), row('u2'), row('a2')]);
	const messages = await loadSessionMessagesWithBackfill('gui', history('old'));
	expect(messages.map(message => message.id)).toEqual(['u1', 'a1', 'u2', 'a2', 'held']);
	expect(messages.find(message => message.id === 'held')?.localUndelivered).toBe(true);
});

it('an explicit rewind load removes the old suffix rather than resurrecting local rows', async () => {
	transport.local.mockResolvedValue([row('user'), row('old-answer')]); transport.server.mockResolvedValue([row('user')]);
	expect((await loadSessionMessagesWithBackfill('gui', history('old'), {preferServer: true})).map(m => m.id)).toEqual(['user']);
});

it.each([false, true])('incomplete history cannot remove local-only rows (preferServer=%s)', async preferServer => {
	transport.local.mockResolvedValue([row('local-user'), row('answer'), row('shared')]);
	const partial = rememberTranscriptSnapshot([row('shared'), row('server-tool-1'), row('server-tool-2'), row('server-tool-3')],
		{session_id: 'old', transcript_found: true, degraded: true, skipped_lines: 1, read_errors: []}, 'old');
	transport.server.mockResolvedValue(partial);
	const messages = await loadSessionMessagesWithBackfill('gui', history('old'), {preferServer});
	expect(messages.map(m => m.id)).toEqual(['local-user', 'answer', 'shared', 'server-tool-1', 'server-tool-2', 'server-tool-3']);
});

it('does not replace local history when the required backup fails', async () => {
	const local = [row('u1'), {...row('legacy'), role: 'assistant' as const}]; transport.local.mockResolvedValue(local);
	const server = rememberTranscriptSnapshot([row('u1'), {...row('server'), role: 'assistant' as const}],
		{session_id: 'old', transcript_found: true, degraded: false, skipped_lines: 0, read_errors: []}, 'old');
	transport.server.mockResolvedValue(server);
	transport.task.mockResolvedValue({ok: true, session_id: 'old', busy: false, waiting_permission: false, status: 'succeeded', turn_id: 't1', revision: 1, last_event_id: 1});
	transport.backup.mockRejectedValueOnce(new Error('QuotaExceededError'));
	expect(await loadSessionMessagesWithBackfill('gui', history('old'))).toEqual(local);
	expect(transport.backup).toHaveBeenCalledOnce(); expect(transport.replace).not.toHaveBeenCalled();
});
