/**
 * 重挂流（reattach）落盘守卫：回放事件把整表回写历史时，绝不能把没加载过的
 * 会话历史覆盖掉。这里钉住两条：冷会话先补齐历史再订阅；补齐失败时宁可只在
 * 内存里显示，也不写 IndexedDB。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';

const loadMessages = vi.fn();
const replaceMessages = vi.fn();
const streamTurnEvents = vi.fn();
const fetchSessionTask = vi.fn();

vi.mock('@/lib/db', async importOriginal => {
	const real = await importOriginal<typeof import('@/lib/db')>();
	return {
		...real,
		loadMessages: (sessionId: string) => loadMessages(sessionId),
		replaceMessages: (sessionId: string, messages: unknown[]) =>
			replaceMessages(sessionId, messages),
	};
});

vi.mock('@/lib/api', async importOriginal => {
	const real = await importOriginal<typeof import('@/lib/api')>();
	return {
		...real,
		fetchSessionTask: (sessionId: string) => fetchSessionTask(sessionId),
		streamTurnEvents: (sessionId: string, cursor: number, handlers: unknown) =>
			streamTurnEvents(sessionId, cursor, handlers),
		readTurnCursor: () => 0,
	};
});

vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: Object.assign(() => ({}), {
		getState: () => ({apiKey: 'test-key', smoothness: true}),
		setState: vi.fn(),
	}),
	isSmoothnessOn: (v?: unknown) => v !== false,
}));

const {useChatStore} = await import('../chatStore');

const SID = 'sess_reattach_guard';
type Row = {id?: string; toolUseId?: string};

function historyRows(count: number) {
	return Array.from({length: count}, (_, i) => ({
		id: `m${i}`,
		role: i % 2 === 0 ? ('user' as const) : ('assistant' as const),
		text: `row ${i}`,
		createdAt: 1000 + i,
	}));
}

function seedStore(loaded: boolean) {
	useChatStore.setState({
		sessions: [
			{
				id: SID,
				spaceId: 'space_default',
				title: 't',
				createdAt: 1,
				updatedAt: 1,
			},
		] as never,
		activeId: SID,
		historyById: {[SID]: {messages: [], cursor: 0}} as never,
		messagesById: loaded ? {[SID]: historyRows(12)} : ({} as never),
		messagesLoadingIds: {},
		sessionStreams: {},
	});
}

describe('reattach 落盘守卫', () => {
	beforeEach(() => {
		loadMessages.mockReset();
		replaceMessages.mockReset();
		streamTurnEvents.mockReset();
		fetchSessionTask.mockReset();
		fetchSessionTask.mockResolvedValue({
			status: 'running',
			busy: true,
			turn_id: 'turn-1',
			goal_text: '',
			stop_reason: '',
		});
		replaceMessages.mockResolvedValue(undefined);
	});

	it('冷会话先加载历史，回放的工具卡接在真实历史之后', async () => {
		const prior = historyRows(12);
		loadMessages.mockResolvedValue(prior);
		seedStore(false);
		streamTurnEvents.mockImplementation(
			async (_sid: string, _cursor: number, handlers: {onToolCall: (ev: unknown) => void}) => {
				handlers.onToolCall({name: 'Read', input: {file_path: 'a.ts'}, toolUseId: 'c1'});
			},
		);

		await useChatStore.getState().reattachStream(SID);

		expect(loadMessages).toHaveBeenCalledWith(SID);
		expect(replaceMessages).toHaveBeenCalledTimes(1);
		const [writtenSession, written] = replaceMessages.mock.calls[0] as unknown as [
			string,
			Row[],
		];
		expect(writtenSession).toBe(SID);
		expect(written.length).toBe(prior.length + 1);
		expect(written.slice(0, prior.length).map(m => m.id)).toEqual(prior.map(m => m.id));
		expect(written[prior.length]?.toolUseId).toBe('c1');
	});

	it('历史加载失败时不开始重放，避免把冷会话变成不完整历史', async () => {
		seedStore(false);
		loadMessages.mockRejectedValue(new Error('idb down'));
		streamTurnEvents.mockImplementation(
			async (_sid: string, _cursor: number, handlers: {onToolCall: (ev: unknown) => void}) => {
				handlers.onToolCall({name: 'Read', input: {}, toolUseId: 'c1'});
			},
		);

		await useChatStore.getState().reattachStream(SID);

		expect(replaceMessages).not.toHaveBeenCalled();
		expect(streamTurnEvents).not.toHaveBeenCalled();
		expect(useChatStore.getState().messagesById[SID]).toBeUndefined();
	});

	it('回填中的会话先等完整历史，再接收重放事件', async () => {
		const prior = historyRows(12);
		seedStore(true);
		useChatStore.setState({messagesLoadingIds: {[SID]: true}} as never);
		loadMessages.mockResolvedValue(prior);
		streamTurnEvents.mockImplementation(
			async (_sid: string, _cursor: number, handlers: {onToolCall: (ev: unknown) => void}) => {
				handlers.onToolCall({name: 'Read', input: {}, toolUseId: 'c1'});
			},
		);

		await useChatStore.getState().reattachStream(SID);

		expect(loadMessages).toHaveBeenCalledWith(SID);
		const written = replaceMessages.mock.calls.at(-1)?.[1] as unknown as Row[];
		expect(written).toHaveLength(prior.length + 1);
		expect(written.slice(0, prior.length).map(row => row.id)).toEqual(
			prior.map(row => row.id),
		);
		expect(written.at(-1)?.toolUseId).toBe('c1');
	});
});
