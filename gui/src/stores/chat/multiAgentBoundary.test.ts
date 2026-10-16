import {beforeEach, expect, it, vi} from 'vitest';
import {createStore} from 'zustand/vanilla';
import {createMultiAgentSlice, createMultiAgentStreamHandlers} from './multiAgentSlice';
import type {ChatState} from './preStoreHelpers';
import {cancelSessionAgent, loadAgentDetail, retrySessionAgent} from '@/lib/api';

vi.mock('@/lib/api', () => ({cancelSessionAgent: vi.fn(), loadAgentDetail: vi.fn(), retrySessionAgent: vi.fn(), listSessionAgents: vi.fn().mockResolvedValue([])}));
beforeEach(() => vi.clearAllMocks());
function fixture() {
    return createStore<ChatState>((set, get) => ({
        sessions: [{id: 's'}], historyById: {},
        ...createMultiAgentSlice(set, get),
        multiAgentTasksBySession: {s: [{uid: 'u', agentId: 'a', attemptId: '1', taskId: 't', desc: 'd', status: 'running'}]},
    } as unknown as ChatState));
}
function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>(r => {resolve = r;});
    return {promise, resolve};
}
it('drops a transcript fetched before a backend branch switch', async () => {
    const store = fixture();
    const response = deferred<{status: string; messages: []}>();
    vi.mocked(loadAgentDetail).mockReturnValueOnce(response.promise);
    const pending = store.getState().ensureAgentTranscript('s', 'a');
    store.setState({historyById: {s: {activeBranch: {branchId: 'next', backendSessionId: 'next'}}} as never});
    response.resolve({status: 'done', messages: []});
    expect(await pending).toBe(false);
    expect(store.getState().agentTranscriptsById['s::a']).toBeUndefined();
});
it('late cancellation cannot mark a replacement attempt', async () => {
    const store = fixture();
    const response = deferred<boolean>();
    vi.mocked(cancelSessionAgent).mockReturnValueOnce(response.promise);
    const pending = store.getState().cancelAgentTask('s', 'a');
    store.setState(s => ({multiAgentTasksBySession: {s: [{...s.multiAgentTasksBySession.s[0], attemptId: '2'}]}}));
    response.resolve(true);
    await pending;
    expect(store.getState().multiAgentTasksBySession.s[0].cancelRequested).not.toBe(true);
    expect(cancelSessionAgent).toHaveBeenCalledWith('s', 'a', '1');
});
it('serializes retry buttons and drops a response after branch replacement', async () => {
    const store = fixture();
    const response = deferred<Awaited<ReturnType<typeof retrySessionAgent>>>();
    vi.mocked(retrySessionAgent).mockReturnValueOnce(response.promise);
    const pending = store.getState().retryAgentTask('s', 'a');
    expect(await store.getState().retryAgentTask('s', 'a')).toBe(false);
    expect(retrySessionAgent).toHaveBeenCalledTimes(1);
    store.setState({historyById: {s: {activeBranch: {branchId: 'next', backendSessionId: 'next'}}} as never});
    response.resolve({ok: true, agentId: 'a', status: 'done', resultPreview: 'old'});
    expect(await pending).toBe(false);
    expect(store.getState().multiAgentTasksBySession.s[0].result).not.toBe('old');
});
it('ignores progress from an earlier attempt sharing the card uid', () => {
    const store = fixture();
    const handlers = createMultiAgentStreamHandlers({get: store.getState, set: store.setState, sessionId: 's'});
    handlers.onMultiAgentProgress({uid: 'u', agentId: 'a', taskId: 't', attemptId: 'old', status: 'failed'} as Parameters<typeof handlers.onMultiAgentProgress>[0]);
    expect(store.getState().multiAgentTasksBySession.s[0].status).toBe('running');
});
it('does not regress a durable terminal card with a delayed start frame', () => {
    const store = fixture();
    store.setState(s => ({multiAgentTasksBySession: {s: [{...s.multiAgentTasksBySession.s[0], status: 'done', runtimeUpdatedAt: 100}]}}));
    const handlers = createMultiAgentStreamHandlers({get: store.getState, set: store.setState, sessionId: 's'});
    handlers.onMultiAgentTask({uid: 'u', taskId: 't', agentId: 'a', attemptId: 'old', attemptStartedAt: 10, desc: 'd', status: 'running'});
    expect(store.getState().multiAgentTasksBySession.s[0].status).toBe('done');
    handlers.onMultiAgentTask({uid: 'u', taskId: 't', agentId: 'a', attemptId: '1', attemptStartedAt: 20, desc: 'd', status: 'running'});
    expect(store.getState().multiAgentTasksBySession.s[0].status).toBe('done');
    handlers.onMultiAgentTask({uid: 'u2', taskId: 't', agentId: 'a', attemptId: '2', attemptStartedAt: 200, desc: 'd', status: 'running'});
    expect(store.getState().multiAgentTasksBySession.s).toHaveLength(1);
    expect(store.getState().multiAgentTasksBySession.s[0].attemptId).toBe('2');
});
