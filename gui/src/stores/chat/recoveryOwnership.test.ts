import {beforeEach, expect, it, vi} from 'vitest';
import type {ChatStreamHandlers} from '@/lib/api';
import type {ChatState} from './preStoreHelpers';
import {createStreamRecoverySlice, recoverAfterDisconnect} from './streamRecoverySlice';
import {createBusyStreamProjection} from './busyStreamProjection';
import {getSessionStream} from '@/lib/sessionStreams';
import {waitingToolTimers, WAITING_TOOL_TIMEOUT_MS} from './streamHelpers';

const transport = vi.hoisted(() => ({task: vi.fn(), stream: vi.fn(), messages: vi.fn(), replace: vi.fn(), interrupt: vi.fn(), abandon: vi.fn()}));
vi.mock('@/lib/api', async original => ({...await original<typeof import('@/lib/api')>(),
	fetchSessionTask: transport.task, streamTurnEvents: transport.stream, loadServerSessionMessages: transport.messages, interruptChat: transport.interrupt, abandonSessionRecovery: transport.abandon}));
vi.mock('@/lib/db', async original => ({...await original<typeof import('@/lib/db')>(), replaceMessages: transport.replace}));
beforeEach(() => vi.resetAllMocks());

function fixture() {
	let state = {sessions: [{id: 'gui'}], activeId: 'gui',
		historyById: {gui: {activeBranch: {branchId: 'root', backendSessionId: 'old'}}},
		messagesById: {gui: [{id: 'new-user', role: 'user', text: 'new branch', createdAt: 1}]},
		messagesLoadingIds: {}, sessionStreams: {}, recoveryBySession: {}, sessionGoalById: {}, sessionJobsById: {},
		setPendingAsk: vi.fn(), setPendingPermission: vi.fn(), setPendingPlan: vi.fn(),
	} as unknown as ChatState;
	const get = () => state;
	const set: Parameters<typeof createStreamRecoverySlice>[0] = update => {
		state = {...state, ...(typeof update === 'function' ? update(state) : update)};
	};
	const branch = () => set({historyById: {gui: {activeBranch: {branchId: 'next', backendSessionId: 'new'}}} as never});
	return {get, set, branch};
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>(done => {resolve = done;});
	return {promise, resolve};
}
const running = {busy: true, status: 'running', turn_id: 'old-turn'};
const finished = {busy: false, status: 'succeeded'};

it('failed recovery abandonment preserves its recovery prompt', async () => {
	const f = fixture(); const recovery = {turnId: 'old-turn', goalText: 'old', stopReason: 'restart'};
	f.set({recoveryBySession: {gui: recovery}}); transport.abandon.mockResolvedValue(false);
	await createStreamRecoverySlice(f.set, f.get).abandonRecovery('gui');
	expect(f.get().recoveryBySession.gui).toBe(recovery);
});

it.each(['branch', 'recovery'])('late recovery abandonment preserves a new %s', async scope => {
	const f = fixture(); f.set({recoveryBySession: {gui: {turnId: 'old-turn', goalText: 'old', stopReason: 'restart'}}});
	const receipt = deferred<boolean>(); transport.abandon.mockReturnValue(receipt.promise);
	const work = createStreamRecoverySlice(f.set, f.get).abandonRecovery('gui');
	if (scope === 'branch') f.branch();
	const recovery = {turnId: 'new-turn', goalText: 'new', stopReason: 'restart'}; f.set({recoveryBySession: {gui: recovery}});
	receipt.resolve(true); await work;
	expect(f.get().recoveryBySession.gui).toBe(recovery);
});

it('an accepted continuation cannot clear a subsequent recovery prompt', async () => {
	const f = fixture(); f.set({recoveryBySession: {gui: {turnId: 'old-turn', goalText: 'old', stopReason: 'restart'}}});
	const accepted = deferred<boolean>(); const sending = vi.fn(() => accepted.promise); f.set({sendMessage: sending});
	const work = createStreamRecoverySlice(f.set, f.get).continueRecovery('gui');
	const recovery = {turnId: 'new-turn', goalText: 'new', stopReason: 'restart'}; f.set({recoveryBySession: {gui: recovery}});
	(sending.mock.calls[0] as unknown as unknown[])[4] && ((sending.mock.calls[0] as unknown as unknown[])[4] as () => void)();
	accepted.resolve(true); await work;
	expect(f.get().recoveryBySession.gui).toBe(recovery);
});

it('does not start an old backend subscription after a branch switch during task lookup', async () => {
	const f = fixture(); const task = deferred<typeof running>();
	transport.task.mockReturnValueOnce(task.promise);
	const work = createStreamRecoverySlice(f.set, f.get).reattachStream('gui');
	f.branch(); task.resolve(running);
	expect(await work).toBe(false);
	expect(transport.stream).not.toHaveBeenCalled();
	expect(f.get().messagesById.gui?.[0]?.text).toBe('new branch');
});

it('finished old recovery cannot replace new branch history', async () => {
	const f = fixture(); f.set({sessionStreams: {gui: {isLoading: true, abortRef: new AbortController()}} as never});
	const task = deferred<typeof finished>(); transport.task.mockReturnValueOnce(task.promise);
	transport.messages.mockResolvedValueOnce([{id: 'old-user', role: 'user', text: 'OLD HISTORY', createdAt: 1}]);
	const work = recoverAfterDisconnect(f.set, f.get, 'gui', 'old');
	f.branch(); task.resolve(finished); await work;
	expect(f.get().messagesById.gui?.[0]?.text).toBe('new branch');
	expect(transport.messages).not.toHaveBeenCalled();
	expect(transport.replace).not.toHaveBeenCalled();
});

it('old recovery cannot clear the controller or messages of a new turn in the same branch', async () => {
	const f = fixture(); const oldController = new AbortController();
	f.set({sessionStreams: {gui: {isLoading: true, abortRef: oldController, turnId: 'old-turn'}} as never});
	const task = deferred<typeof finished>(); transport.task.mockReturnValueOnce(task.promise);
	const work = recoverAfterDisconnect(f.set, f.get, 'gui', 'old');
	oldController.abort(); const currentController = new AbortController();
	f.set({sessionStreams: {gui: {isLoading: true, abortRef: currentController, turnId: 'new-turn'}} as never});
	task.resolve(finished); await work;
	expect(f.get().sessionStreams.gui?.abortRef).toBe(currentController);
	expect(f.get().sessionStreams.gui?.isLoading).toBe(true);
	expect(f.get().messagesById.gui?.[0]?.text).toBe('new branch');
	expect(transport.replace).not.toHaveBeenCalled();
});

it.each(['branch', 'turn'])('late delta, tool, dialog and done callbacks do not change a new %s', async scope => {
	const f = fixture(); transport.task.mockResolvedValueOnce(running);
	let handlers!: ChatStreamHandlers; const stream = deferred<void>();
	transport.stream.mockImplementationOnce(async (_sid, _cursor, next) => {handlers = next; await stream.promise;});
	const work = createStreamRecoverySlice(f.set, f.get).reattachStream('gui');
	await vi.waitFor(() => expect(handlers).toBeDefined());
	if (scope === 'branch') f.branch();
	else f.set({sessionStreams: {gui: {isLoading: true, abortRef: new AbortController(), turnId: 'new-turn'}} as never});
	const before = f.get();
	handlers.onDelta('OLD BRANCH RESPONSE', 'old-reply');
	handlers.onToolCall?.({name: 'Read', input: '{}', toolUseId: 'old-tool'});
	handlers.onAskUserPending?.({kind: 'ask_user_pending', requestId: 'old-ask', question: 'old question', options: [], questions: []});
	handlers.onDone(); stream.resolve(); await work;
	expect(f.get()).toBe(before);
	expect(transport.replace).not.toHaveBeenCalled();
	expect(f.get().setPendingAsk).not.toHaveBeenCalled();
});

it('a late gap backfill cannot overwrite a newer turn after the stream closes', async () => {
	const f = fixture(); transport.task.mockResolvedValueOnce(running);
	const messages = deferred<never[]>(); transport.messages.mockReturnValueOnce(messages.promise);
	transport.stream.mockImplementationOnce(async (_sid, _cursor, handlers: ChatStreamHandlers) => {
		handlers.onStreamGap?.({} as never); handlers.onDone();
	});
	await createStreamRecoverySlice(f.set, f.get).reattachStream('gui');
	const controller = new AbortController();
	f.set({sessionStreams: {gui: {isLoading: true, abortRef: controller, turnId: 'new-turn'}} as never});
	messages.resolve([{id: 'old', role: 'assistant', text: 'OLD GAP HISTORY', createdAt: 1}] as never[]);
	await Promise.resolve(); await Promise.resolve();
	expect(f.get().sessionStreams.gui?.abortRef).toBe(controller);
	expect(f.get().messagesById.gui?.[0]?.text).toBe('new branch');
	expect(transport.replace).not.toHaveBeenCalled();
});

it('an invalid old probe does not block immediate attachment to the new backend', async () => {
	const f = fixture(); const task = deferred<typeof running>();
	transport.task.mockReturnValueOnce(task.promise).mockResolvedValueOnce({...running, turn_id: 'new-turn'});
	transport.stream.mockImplementationOnce(async (_sid, _cursor, handlers: ChatStreamHandlers) => {
		handlers.onDelta('NEW RESPONSE', 'new-reply'); handlers.onDone();
	});
	const slice = createStreamRecoverySlice(f.set, f.get);
	const old = slice.reattachStream('gui'); f.branch();
	expect(await slice.reattachStream('gui')).toBe(true);
	task.resolve(running); expect(await old).toBe(false);
	expect(transport.stream.mock.calls.map(call => call[0])).toEqual(['new']);
	expect(f.get().messagesById.gui?.at(-1)?.text).toBe('NEW RESPONSE');
});

it('current finished recovery updates history, but its delayed DB write loses ownership on a new turn', async () => {
	const f = fixture(); f.set({sessionStreams: {gui: {isLoading: true, abortRef: new AbortController(), turnId: 'old-turn'}} as never});
	transport.task.mockResolvedValueOnce(finished);
	const rows = [{id: 'final', role: 'assistant', text: 'final response', createdAt: 1}];
	transport.messages.mockResolvedValueOnce(rows);
	expect(await recoverAfterDisconnect(f.set, f.get, 'gui', 'old')).toBe(true);
	expect(f.get().messagesById.gui).toBe(rows);
	expect(f.get().sessionStreams.gui?.isLoading).toBe(false);
	const writeAllowed = transport.replace.mock.calls[0]![2] as () => boolean;
	expect(writeAllowed()).toBe(true);
	f.set({sessionStreams: {gui: {isLoading: true, abortRef: new AbortController(), turnId: 'new-turn'}} as never});
	expect(writeAllowed()).toBe(false);
});

it.each(['branch', 'turn'])('busy-submit stream cannot finish or write tools into a newer %s', scope => {
	const f = fixture();
	const projection = createBusyStreamProjection(f.get, f.set, 'gui', getSessionStream(f.get(), 'gui'), 'new-user');
	projection.start(new AbortController()); projection.onDelta('old partial', 'old-output');
	if (scope === 'branch') f.branch();
	else f.set({sessionStreams: {gui: {isLoading: true, abortRef: new AbortController(), turnId: 'new-turn'}} as never});
	const before = f.get();
	projection.onDelta('old trailing delta', 'old-output');
	projection.onToolCall({name: 'Read', input: '{}', toolUseId: 'old-tool'});
	projection.onDone();
	expect(f.get()).toBe(before);
	projection.onAbort();
});

it('busy-submit connection loss releases its dead socket before recovery', () => {
	const f = fixture();
	const projection = createBusyStreamProjection(f.get, f.set, 'gui', getSessionStream(f.get(), 'gui'), 'new-user');
	projection.start(new AbortController());
	projection.onConnectionLost();
	expect(getSessionStream(f.get(), 'gui').abortRef).toBe(null);
	expect(getSessionStream(f.get(), 'gui').turnDetached).toBe(true);
	projection.onAbort();
});

it.each(['branch', 'turn'])('a late failed stop receipt cannot alter a newer %s', async scope => {
	const f = fixture();
	f.set({sessionStreams: {gui: {isLoading: true, streamingText: '', abortRef: new AbortController(), turnId: 'old-turn'}} as never});
	const receipt = deferred<{ok: boolean; message: string}>(); transport.interrupt.mockReturnValueOnce(receipt.promise);
	await createStreamRecoverySlice(f.set, f.get).stopGeneration();
	if (scope === 'branch') f.branch();
	else f.set({sessionStreams: {gui: {isLoading: true, abortRef: new AbortController(), turnId: 'new-turn', statusText: 'NEW TASK'}} as never});
	const before = f.get(); receipt.resolve({ok: false, message: 'network failure'});
	await receipt.promise; await Promise.resolve();
	expect(f.get()).toBe(before);
});

it('a stale stop timeout cannot delete a replacement timer registration', async () => {
	vi.useFakeTimers();
	try {
		const f = fixture();
		f.set({sessionStreams: {gui: {isLoading: true, streamingText: '', abortRef: new AbortController(), turnId: 'old-turn'}} as never,
			messagesById: {gui: [{id: 'tool', role: 'tool', text: '', createdAt: 1, toolStatus: 'running'}]}});
		transport.interrupt.mockResolvedValue({ok: true}); transport.messages.mockResolvedValue([]);
		await createStreamRecoverySlice(f.set, f.get).stopGeneration();
		waitingToolTimers.set('gui', 987654);
		vi.advanceTimersByTime(WAITING_TOOL_TIMEOUT_MS);
		expect(waitingToolTimers.get('gui')).toBe(987654);
	} finally {vi.clearAllTimers(); vi.useRealTimers(); waitingToolTimers.clear();}
});
