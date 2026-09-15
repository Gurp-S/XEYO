import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {ChatStreamHandlers} from '@/lib/api';
import {DEFAULT_SPACE_ID, SIDE_SPACE_ID} from '@/lib/db';
import type {
	ChatSession,
	ChatSpace,
} from '@/lib/types';
import {
	getSessionStream,
	patchSessionStream,
	sessionStreamActive,
} from '@/lib/sessionStreams';

const streamChat = vi.fn();
const interruptChat = vi.fn();
const setWorkspace = vi.fn();
const previewRollback = vi.fn();
const executeRollback = vi.fn();
const resolveRollbackRecovery = vi.fn();
const loadServerSessionMessages = vi.fn();
const listServerSessions = vi.fn(
	async (): Promise<{id: string; title: string; createdAt: number; updatedAt: number}[]> => [],
);

vi.mock('@/lib/api', () => ({
	streamChat: (...args: unknown[]) => streamChat(...args),
	interruptChat: (...args: unknown[]) => interruptChat(...args),
	setWorkspace: (...args: unknown[]) => setWorkspace(...args),
	previewRollback: (...args: unknown[]) => previewRollback(...args),
	executeRollback: (...args: unknown[]) => executeRollback(...args),
	resolveRollbackRecovery: (...args: unknown[]) => resolveRollbackRecovery(...args),
	loadServerSessionMessages: (...args: unknown[]) => loadServerSessionMessages(...args),
	listServerSessions: () => listServerSessions(),
	deleteServerSession: vi.fn(async () => true),
	fetchSessionTask: vi.fn(async () => null),
	streamTurnEvents: vi.fn(async () => undefined),
	abandonSessionRecovery: vi.fn(async () => true),
	readTurnCursor: vi.fn(() => 0),
	rememberTurnCursor: vi.fn(() => undefined),
}));

vi.mock('@/lib/db', async () => {
	const actual = await vi.importActual<typeof import('@/lib/db')>('@/lib/db');
	return {
		...actual,
		loadSpaces: vi.fn(),
		loadSessions: vi.fn(),
			loadMessages: vi.fn(),
			loadChatHistoryState: vi.fn(async () => null),
			loadRollbackState: vi.fn(async () => null),
			saveRollbackState: vi.fn(async () => undefined),
			clearRollbackState: vi.fn(async () => undefined),
			saveChatHistoryState: vi.fn(async () => undefined),
			clearChatHistoryState: vi.fn(async () => undefined),
			saveSession: vi.fn(async () => undefined),
		saveSpace: vi.fn(async () => undefined),
		replaceMessages: vi.fn(async () => undefined),
		upsertMessages: vi.fn(async () => undefined),
		patchMessages: vi.fn(async () => undefined),
		deleteSession: vi.fn(async () => undefined),
		deleteSpace: vi.fn(async () => undefined),
		deleteSpaceRecord: vi.fn(async () => undefined),
		markSessionDeleted: vi.fn(async () => undefined),
		markSpaceDeleted: vi.fn(async () => undefined),
		loadDeletedSessionIds: vi.fn(async () => new Set<string>()),
		loadDeletedSpaceIds: vi.fn(async () => new Set<string>()),
		loadDeletedSpacePaths: vi.fn(async () => new Set<string>()),
		clearSpacePathTombstone: vi.fn(async () => undefined),
		purgeTombstonedLocalRecords: vi.fn(async () => undefined),
		ensureDefaultSpace: vi.fn(),
	};
});

const openSettings = vi.fn();
vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: Object.assign(() => ({}), {
		getState: () => ({
			apiKey: 'test-key',
			smoothness: true,
			openSettings,
			closeSettings: vi.fn(),
			settingsModalOpen: false,
		}),
		setState: vi.fn(),
	}),
	isSmoothnessOn: (v?: unknown) => v !== false,
}));

import {
	deleteSpaceRecord,
	loadDeletedSessionIds,
	loadMessages,
	loadRollbackState,
	loadSessions,
	loadSpaces,
	markSessionDeleted,
	replaceMessages,
	saveSession,
	saveSpace,
	patchMessages,
	upsertMessages,
} from '@/lib/db';
import {deleteServerSession} from '@/lib/api';
import {useChatStore} from './chatStore';

function space(partial?: Partial<ChatSpace>): ChatSpace {
	const now = Date.now();
	return {
		id: DEFAULT_SPACE_ID,
		name: 'No remote',
		rootPath: '',
		createdAt: now,
		updatedAt: now,
		...partial,
	};
}

function session(
	id: string,
	partial?: Partial<ChatSession>,
): ChatSession {
	const now = Date.now();
	return {
		id,
		spaceId: DEFAULT_SPACE_ID,
		title: '新对话',
		createdAt: now,
		updatedAt: now,
		...partial,
	};
}

async function seedSession(id = 'sess_test') {
	const sp = space({rootPath: 'D:\\proj'});
	const sess = session(id);
	useChatStore.setState({
		hydrated: true,
		spaces: [sp],
		sessions: [sess],
		activeId: id,
		activeSpaceId: DEFAULT_SPACE_ID,
		errorBanner: null,
		errorBannerSessionId: null,
		messagesById: {[id]: []},
		historyById: {},
		rollbackById: {
			[id]: {
				status: 'idle',
				phase: 'idle',
				targetMessageId: null,
				editedText: '',
				plan: null,
				job: null,
				idempotencyKey: null,
				error: null,
			},
		},
		sessionStreams: {},
		sidebarOpen: true,
		collapsedSpaces: {},
	});
	return id;
}

describe('chatStore dialogue — normal', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		setWorkspace.mockResolvedValue('/tmp');
		interruptChat.mockResolvedValue(undefined);
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('Hello');
				handlers.onDelta(' world');
				handlers.onDone();
			},
		);
		await seedSession();
	});

	it('rejects empty / whitespace-only send', async () => {
		expect(await useChatStore.getState().sendMessage('')).toBe(false);
		expect(await useChatStore.getState().sendMessage('   \n\t')).toBe(
			false,
		);
		expect(useChatStore.getState().messagesById.sess_test).toEqual([]);
		expect(streamChat).not.toHaveBeenCalled();
	});

	it('optimistically shows user message before stream finishes', async () => {
		let release!: () => void;
		const gate = new Promise<void>(r => {
			release = r;
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				await gate;
				handlers.onDelta('ok');
				handlers.onDone();
			},
		);

		const pending = useChatStore.getState().sendMessage('你好');
		await vi.waitFor(() => {
			expect(getSessionStream(useChatStore.getState(), 'sess_test').isLoading).toBe(
				true,
			);
		});
		const mid = useChatStore.getState();
		const midStream = getSessionStream(mid, 'sess_test');
		expect(sessionStreamActive(mid, 'sess_test')).toBe(true);
		expect(mid.messagesById.sess_test?.some(m => m.text === '你好')).toBe(
			true,
		);
		expect(midStream.statusText).toBe('thinking…');

		release();
		expect(await pending).toBe(true);
		const done = useChatStore.getState();
		expect(sessionStreamActive(done, 'sess_test')).toBe(false);
		expect(
			done.messagesById.sess_test?.some(
				m => m.role === 'assistant' && m.text === 'ok',
			),
		).toBe(true);
	});

	it('coalesces deltas into assistant text on done', async () => {
		expect(await useChatStore.getState().sendMessage('ping')).toBe(true);
		const msgs = useChatStore.getState().messagesById.sess_test ?? [];
		const asst = msgs.find(m => m.role === 'assistant');
		expect(asst?.text).toBe('Hello world');
		expect(getSessionStream(useChatStore.getState(), 'sess_test').streamingText).toBe('');
	});

	it('updates session title from first user message', async () => {
		await useChatStore.getState().sendMessage('给这个对话起个标题测试');
		const sess = useChatStore
			.getState()
			.sessions.find(s => s.id === 'sess_test');
		expect(sess?.title).toContain('给这个对话起个标题');
	});
});

describe('chatStore dialogue — errors & busy', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		setWorkspace.mockResolvedValue('/tmp');
		interruptChat.mockResolvedValue(undefined);
		await seedSession();
	});

	it('surfaces stream onError as banner and unlocks UI', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onError('Missing API key');
			},
		);
		expect(await useChatStore.getState().sendMessage('x')).toBe(true);
		const msgs = useChatStore.getState().messagesById.sess_test ?? [];
		expect(msgs.some(m => m.role === 'user' && m.text === 'x')).toBe(true);
		expect(useChatStore.getState().errorBanner).toMatch(/API key/i);
		expect(
			msgs.some(m => m.role === 'system' && m.text.includes('API key')),
		).toBe(false);
		expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(false);
	});

	it('keeps partial assistant text when error mid-stream', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('partial');
				handlers.onError('boom');
			},
		);
		await useChatStore.getState().sendMessage('x');
		const texts = (useChatStore.getState().messagesById.sess_test ?? []).map(
			m => m.text,
		);
		expect(texts).toContain('partial');
		expect(useChatStore.getState().errorBanner).toMatch(/boom/i);
		expect(texts.some(t => t.includes('boom'))).toBe(false);
	});

	it('queues second send while streaming (busy) and notifies inbox', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				// 队列请求：后端立即 202（不依赖回合结束）。
				handlers.onQueued?.({queueId: 'q-2', position: 1});
			},
		);
		// 预置 live 流：isLoading + 未 dead 的 abortRef → busy & live 均真。
		useChatStore.setState(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, 'sess_test', {
				isLoading: true,
				streamingText: '',
				streamingShown: '',
				abortRef: new AbortController(),
				remoteStreaming: false,
				turnDetached: false,
				draining: false,
			}),
		}));

		// 不再被拒：走排队路径（乐观气泡 + 后端 202 → inbox chip）。
		expect(await useChatStore.getState().sendMessage('two')).toBe(true);
		await vi.waitFor(() => {
			const inbox = useChatStore.getState().inboxBySession.sess_test ?? [];
			expect(inbox.some(item => item.text === 'two' && item.state === 'queued')).toBe(
				true,
			);
		});
		const users = (useChatStore.getState().messagesById.sess_test ?? [])
			.filter(m => m.role === 'user')
			.map(m => m.text);
		expect(users).toEqual(['two']);
	});

	it('updates tool row in place on result (no call/result remount pair)', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('before ');
				handlers.onToolCall?.({name: 'echo', input: {text: 'hi'}});
				handlers.onToolResult?.({
					name: 'echo',
					output: 'hi',
					is_error: false,
				});
				handlers.onDelta('after');
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('run tool')).toBe(
			true,
		);
		const msgs = useChatStore.getState().messagesById.sess_test ?? [];
		const tools = msgs.filter(m => m.role === 'tool');
		expect(tools).toHaveLength(1);
		expect(tools[0]).toMatchObject({
			toolName: 'echo',
			toolInput: '{"text":"hi"}',
			toolStatus: 'done',
			text: 'hi',
		});
	});

	it('pairs parallel same-name tools by toolUseId', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onToolCall?.({
					name: 'Grep',
					input: {pattern: 'a'},
					toolUseId: 'call-a',
				});
				handlers.onToolCall?.({
					name: 'Grep',
					input: {pattern: 'b'},
					toolUseId: 'call-b',
				});
				handlers.onToolResult?.({
					name: 'Grep',
					output: 'hits-b',
					is_error: false,
					toolUseId: 'call-b',
				});
				handlers.onToolResult?.({
					name: 'Grep',
					output: 'hits-a',
					is_error: false,
					toolUseId: 'call-a',
				});
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('parallel grep')).toBe(
			true,
		);
		const tools = (useChatStore.getState().messagesById.sess_test ?? [])
			.filter(m => m.role === 'tool');
		expect(tools).toHaveLength(2);
		const byId = Object.fromEntries(
			tools.map(t => [t.toolUseId, t]),
		);
		expect(byId['call-a']?.text).toBe('hits-a');
		expect(byId['call-b']?.text).toBe('hits-b');
		expect(byId['call-a']?.toolInput).toContain('"pattern":"a"');
		expect(byId['call-b']?.toolInput).toContain('"pattern":"b"');
	});

	it('marks running tools waiting on done and accepts late tool_result', async () => {
		let lateResult: ChatStreamHandlers['onToolResult'] | undefined;
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				lateResult = handlers.onToolResult;
				handlers.onToolCall?.({
					name: 'WebSearch',
					input: {query: 'x'},
					toolUseId: 'ws-1',
				});
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('search')).toBe(true);
		const mid = useChatStore.getState().messagesById.sess_test ?? [];
		const waiting = mid.find(m => m.role === 'tool');
		expect(waiting?.toolStatus).toBe('waiting');
		expect(waiting?.text).toBe('');
		expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(
			false,
		);

		lateResult?.({
			name: 'WebSearch',
			output: 'provider: bing\n1. ok',
			is_error: false,
			toolUseId: 'ws-1',
		});
		const done = (useChatStore.getState().messagesById.sess_test ?? []).find(
			m => m.id === waiting?.id,
		);
		expect(done?.toolStatus).toBe('done');
		expect(done?.text).toContain('provider: bing');
	});

	it('coalesces multiple tool events into one zustand set per frame when smoothness is on', async () => {
		const queued: FrameRequestCallback[] = [];
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
			queued.push(cb);
			return queued.length;
		});
		vi.stubGlobal('cancelAnimationFrame', (id: number) => {
			const i = id - 1;
			if (queued[i]) {
				queued[i] = () => undefined;
			}
		});
		let release = () => {};
		const gate = new Promise<void>(resolve => {
			release = resolve;
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onToolCall?.({name: 'echo', input: {text: 'a'}});
				handlers.onToolCall?.({name: 'echo', input: {text: 'b'}});
				handlers.onToolCall?.({name: 'echo', input: {text: 'c'}});
				await gate;
				handlers.onDone();
			},
		);
		try {
			const pending = useChatStore.getState().sendMessage('run tools');
			await vi.waitFor(() => {
				expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(
					true,
				);
			});
			let sets = 0;
			const unsub = useChatStore.subscribe(() => {
				sets += 1;
			});
			expect(queued.length).toBeGreaterThan(0);
			const batch = queued.splice(0);
			for (const cb of batch) {
				cb(0);
			}
			unsub();
			expect(sets).toBe(1);
			const tools = (useChatStore.getState().messagesById.sess_test ?? [])
				.filter(m => m.role === 'tool');
			expect(tools).toHaveLength(3);
			release();
			expect(await pending).toBe(true);
		} finally {
			vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
				cb(0);
				return 1;
			});
			vi.stubGlobal('cancelAnimationFrame', () => {});
		}
	});

	it('coalesces persistHot IDB writes after debounce and idle', async () => {
		const queued: FrameRequestCallback[] = [];
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
			queued.push(cb);
			return queued.length;
		});
		vi.stubGlobal('cancelAnimationFrame', (id: number) => {
			const i = id - 1;
			if (queued[i]) {
				queued[i] = () => undefined;
			}
		});
		vi.stubGlobal('requestIdleCallback', undefined);
		vi.mocked(replaceMessages).mockClear();
		vi.mocked(patchMessages).mockClear();
		vi.mocked(upsertMessages).mockClear();
		let release = () => {};
		const gate = new Promise<void>(resolve => {
			release = resolve;
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onToolCall?.({name: 'echo', input: {text: 'a'}});
				handlers.onToolCall?.({name: 'echo', input: {text: 'b'}});
				await gate;
				handlers.onDone();
			},
		);
		try {
			const pending = useChatStore.getState().sendMessage('persist tools');
			await vi.waitFor(() => {
				expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(
					true,
				);
			});
			expect(queued.length).toBeGreaterThan(0);
			vi.useFakeTimers();
			for (const cb of queued.splice(0)) {
				cb(0);
			}
			const beforeIdle = vi.mocked(patchMessages).mock.calls.length;
			await vi.advanceTimersByTimeAsync(400);
			await vi.advanceTimersByTimeAsync(1);
			expect(vi.mocked(patchMessages).mock.calls.length).toBe(
				beforeIdle + 1,
			);
			vi.useRealTimers();
			release();
			expect(await pending).toBe(true);
		} finally {
			vi.useRealTimers();
			vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
				cb(0);
				return 1;
			});
			vi.stubGlobal('cancelAnimationFrame', () => {});
		}
	});

	it('advances streamingShown in the same zustand set as streamingText', async () => {
		const queued: FrameRequestCallback[] = [];
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
			queued.push(cb);
			return queued.length;
		});
		vi.stubGlobal('cancelAnimationFrame', (id: number) => {
			const i = id - 1;
			if (queued[i]) {
				queued[i] = () => undefined;
			}
		});
		let release = () => {};
		const gate = new Promise<void>(resolve => {
			release = resolve;
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('abcdefghijklmnopqrstuvwxyz');
				await gate;
				handlers.onDone();
			},
		);
		try {
			const pending = useChatStore.getState().sendMessage('go');
			await vi.waitFor(() => {
				expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(
					true,
				);
			});
			let sets = 0;
			const unsub = useChatStore.subscribe(() => {
				sets += 1;
			});
			expect(queued.length).toBeGreaterThan(0);
			const batch = queued.splice(0);
			for (const cb of batch) {
				cb(0);
			}
			unsub();
			expect(sets).toBe(1);
			const st = useChatStore.getState();
			const stream = getSessionStream(st, 'sess_test');
			expect(stream.streamingText).toBe('abcdefghijklmnopqrstuvwxyz');
			expect(stream.streamingShown.length).toBeGreaterThan(0);
			expect(stream.streamingShown.length).toBeLessThanOrEqual(
				stream.streamingText.length,
			);
			expect(stream.streamingText.startsWith(stream.streamingShown)).toBe(true);
			release();
			while (queued.length > 0) {
				const rest = queued.splice(0);
				for (const cb of rest) {
					cb(0);
				}
			}
			expect(await pending).toBe(true);
		} finally {
			vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
				cb(0);
				return 1;
			});
			vi.stubGlobal('cancelAnimationFrame', () => {});
		}
	});

	it('allows send while another session is streaming', async () => {
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_other', {
				isLoading: true,
				streamingText: 'leftover',
				abortRef: new AbortController(),
			}),
			sessions: [
				session('sess_test'),
				session('sess_other', {spaceId: DEFAULT_SPACE_ID}),
			],
			messagesById: {sess_test: [], sess_other: []},
			activeId: 'sess_test',
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('ok');
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('after folder')).toBe(
			true,
		);
		expect(interruptChat).not.toHaveBeenCalled();
		expect(
			useChatStore
				.getState()
				.messagesById.sess_test?.some(m => m.text === 'after folder'),
		).toBe(true);
	});

	it('recovers stale isLoading without streamingSessionId', async () => {
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				statusText: 'stuck',
			}),
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('recovered');
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('go')).toBe(true);
		expect(
			useChatStore
				.getState()
				.messagesById.sess_test?.some(m => m.text === 'go'),
		).toBe(true);
	});

	it('recovers ghost same-session stream when abort is already dead', async () => {
		const dead = new AbortController();
		dead.abort();
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				streamingText: 'stuck mid-tool',
				abortRef: dead,
				statusText: 'thinking…',
			}),
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('again');
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('retry')).toBe(true);
		expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(false);
	});

	it('stopGeneration always clears loading even without wait for SSE', async () => {
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				streamingText: 'partial',
				abortRef: new AbortController(),
			}),
		});
		await useChatStore.getState().stopGeneration();
		const st = useChatStore.getState();
		expect(sessionStreamActive(st, 'sess_test')).toBe(false);
		expect(getSessionStream(st, 'sess_test').abortRef).toBeNull();
	});

	it('appendRemoteMessage mirrors remote user text', () => {
		useChatStore.getState().appendRemoteMessage('user', '[远程]\n你是谁');
		const msgs = useChatStore.getState().messagesById.sess_test ?? [];
		expect(msgs.at(-1)?.text).toBe('[远程]\n你是谁');
		expect(msgs.at(-1)?.source).toBe('remote');
	});

	it('appendRemoteMessage creates a session when none is active', () => {
		useChatStore.setState({
			sessions: [],
			activeId: null,
			messagesById: {},
		});
		useChatStore.getState().appendRemoteMessage('user', '[远程]\nhello');
		const st = useChatStore.getState();
		expect(st.activeId).toBeTruthy();
		const msgs = st.messagesById[st.activeId!] ?? [];
		expect(msgs.at(-1)?.text).toBe('[远程]\nhello');
	});

	it('applyRemoteToolCall flushes thinking then shows a running tool', () => {
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				remoteStreaming: true,
				streamingText: '先分析一下',
				statusText: '',
			}),
		});
		useChatStore.getState().applyRemoteToolCall('Screenshot', {monitor: 1});
		const st = useChatStore.getState();
		const msgs = st.messagesById.sess_test ?? [];
		expect(msgs.some(m => m.role === 'assistant' && m.text === '先分析一下')).toBe(
			true,
		);
		const tool = msgs.find(m => m.role === 'tool');
		expect(tool?.toolName).toBe('Screenshot');
		expect(tool?.toolStatus).toBe('running');
		expect(getSessionStream(st, 'sess_test').streamingText).toBe('');
		useChatStore
			.getState()
			.applyRemoteToolResult('Screenshot', 'Captured primary display.');
		const after = useChatStore.getState().messagesById.sess_test ?? [];
		const done = after.find(m => m.role === 'tool');
		expect(done?.toolStatus).toBe('done');
		expect(done?.text).toContain('Captured');
	});

	it('commitRemoteStream dedupes by last.text not content', () => {
		useChatStore.getState().appendRemoteMessage(
			'assistant',
			'Hello world this is a long reply',
		);
		const before = useChatStore.getState().messagesById.sess_test ?? [];
		useChatStore.getState().commitRemoteStream(
			'Hello world this is a long reply',
		);
		const after = useChatStore.getState().messagesById.sess_test ?? [];
		expect(after).toHaveLength(before.length);
		expect(after.at(-1)?.text).toBe('Hello world this is a long reply');
	});

	it('recoverStuckStream does not kill live remote stream', () => {
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				abortRef: null,
				remoteStreaming: true,
				streamingText: 'hel',
			}),
		});
		useChatStore.getState().recoverStuckStream();
		const st = useChatStore.getState();
		const stream = getSessionStream(st, 'sess_test');
		expect(stream.remoteStreaming).toBe(true);
		expect(stream.streamingText).toBe('hel');
		expect(stream.isLoading).toBe(true);
	});

	it('recoverStuckStream clears dead abort locks and preserves streaming tail', () => {
		const dead = new AbortController();
		dead.abort();
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				abortRef: dead,
				remoteStreaming: false,
				streamingText: 'partial summary',
			}),
			messagesById: {
				sess_test: [{id: 'u1', role: 'user', text: 'hi', createdAt: 1}],
			},
		});
		useChatStore.getState().recoverStuckStream();
		const st = useChatStore.getState();
		expect(sessionStreamActive(st, 'sess_test')).toBe(false);
		const asst = st.messagesById.sess_test?.find(m => m.role === 'assistant');
		expect(asst?.text).toBe('partial summary');
	});

	it('recoverStuckStream does not settle running tools on a live local stream', () => {
		const live = new AbortController();
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: true,
				abortRef: live,
				remoteStreaming: false,
			}),
			messagesById: {
				sess_test: [
					{
						id: 't1',
						role: 'tool',
						toolName: 'Read',
						toolInput: '{"file_path":"a.ts"}',
						toolStatus: 'running',
						text: '',
						createdAt: 2,
					},
				],
			},
		});
		useChatStore.getState().recoverStuckStream();
		const st = useChatStore.getState();
		const tool = st.messagesById.sess_test?.find(m => m.id === 't1');
		expect(tool?.toolStatus).toBe('running');
		expect(tool?.text).toBe('');
		expect(getSessionStream(st, 'sess_test').isLoading).toBe(true);
		expect(interruptChat).not.toHaveBeenCalled();
	});

	it('recoverStuckStream does not kill draining stream or its running tools', () => {
		useChatStore.setState({
			sessionStreams: patchSessionStream({}, 'sess_test', {
				isLoading: false,
				abortRef: null,
				draining: true,
				streamingText: 'hello world this is a long reply for drain',
			}),
			messagesById: {
				sess_test: [
					{
						id: 't1',
						role: 'tool',
						toolName: 'Read',
						toolStatus: 'running',
						text: '',
						createdAt: 1,
					},
				],
			},
		});
		useChatStore.getState().recoverStuckStream();
		const st = useChatStore.getState();
		expect(getSessionStream(st, 'sess_test').draining).toBe(true);
		const tool = st.messagesById.sess_test?.find(m => m.id === 't1');
		expect(tool?.toolStatus).toBe('running');
		expect(interruptChat).not.toHaveBeenCalled();
	});

	it('recoverStuckStream does not stamp waiting tools while late-result timer is armed', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onToolCall?.({
					name: 'Read',
					input: {file_path: 'a.ts'},
					toolUseId: 'r1',
				});
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('read')).toBe(true);
		const waiting = (useChatStore.getState().messagesById.sess_test ?? []).find(
			m => m.role === 'tool',
		);
		expect(waiting?.toolStatus).toBe('waiting');
		useChatStore.getState().recoverStuckStream();
		const tool = (useChatStore.getState().messagesById.sess_test ?? []).find(
			m => m.id === waiting?.id,
		);
		expect(tool?.toolStatus).toBe('waiting');
		expect(tool?.text).toBe('');
	});

	it('recoverStuckStream settles orphan running tools after crash', () => {
		useChatStore.setState({
			sessionStreams: {},
			messagesById: {
				sess_test: [
					{
						id: 'u1',
						role: 'user',
						text: 'hi',
						createdAt: 1,
					},
					{
						id: 't1',
						role: 'tool',
						toolName: 'TodoWrite',
						toolInput: '{"todos":[]}',
						toolStatus: 'running',
						text: '',
						createdAt: 2,
					},
					{
						id: 'e1',
						role: 'system',
						text: 'liveTodosOrNull is not defined',
						createdAt: 3,
					},
				],
			},
		});
		useChatStore.getState().recoverStuckStream();
		const msgs = useChatStore.getState().messagesById.sess_test ?? [];
		expect(msgs.some(m => m.text.includes('liveTodosOrNull'))).toBe(false);
		const tool = msgs.find(m => m.id === 't1');
		expect(tool?.toolStatus).toBe('error');
		expect(tool?.text).toContain('interrupted (stream ended without tool result)');
		expect(tool?.text).not.toMatch(/crash/i);
		expect(replaceMessages).toHaveBeenCalled();
	});

	it('workspace sync failure blocks send', async () => {
		useChatStore.setState({
			spaces: [space({rootPath: 'D:\\proj'})],
		});
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		setWorkspace.mockRejectedValue(new Error('pool has no cwd'));
		expect(await useChatStore.getState().sendMessage('still works')).toBe(
			false,
		);
		expect(streamChat).not.toHaveBeenCalled();
		expect(useChatStore.getState().errorBanner).toMatch(/无法绑定工作区/);
	});

		it('IDB replaceMessages failure still keeps optimistic user bubble', async () => {
			vi.mocked(replaceMessages).mockRejectedValueOnce(new Error('idb down'));
			streamChat.mockImplementation(
				async (
					_sid: string,
					_text: string,
					handlers: ChatStreamHandlers,
				) => {
					handlers.onDelta('a');
					handlers.onDone();
				},
			);
			expect(await useChatStore.getState().sendMessage('persist?')).toBe(true);
			await Promise.resolve();
			await Promise.resolve();
			const msgs = useChatStore.getState().messagesById.sess_test ?? [];
			expect(msgs.some(m => m.text === 'persist?')).toBe(true);
		});

	});

describe('chatStore dialogue — extreme', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		setWorkspace.mockResolvedValue('/tmp');
		await seedSession();
	});

	it('handles huge user payload without dropping optimistic UI', async () => {
		const huge = '汉'.repeat(50_000);
		streamChat.mockImplementation(
			async (
				_sid: string,
				text: string,
				handlers: ChatStreamHandlers,
			) => {
				expect(text.length).toBe(50_000);
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage(huge)).toBe(true);
		expect(
			useChatStore.getState().messagesById.sess_test?.[0]?.text.length,
		).toBe(50_000);
	});

	it('handles many tiny deltas', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				for (let i = 0; i < 200; i++) {
					handlers.onDelta(String(i % 10));
				}
				handlers.onDone();
			},
		);
		await useChatStore.getState().sendMessage('flood');
		const asst = useChatStore
			.getState()
			.messagesById.sess_test?.find(m => m.role === 'assistant');
		expect(asst?.text.length).toBe(200);
	});

	it('stopGeneration aborts and unlocks via AbortError path', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('ab');
				await new Promise<void>((_resolve, reject) => {
					handlers.signal?.addEventListener('abort', () => {
						const err = new Error('aborted');
						err.name = 'AbortError';
						reject(err);
					});
				});
			},
		);
		const pending = useChatStore.getState().sendMessage('stop me');
		await vi.waitFor(() => {
			expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(
				true,
			);
		});
		await useChatStore.getState().stopGeneration();
		expect(await pending).toBe(true);
		expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(false);
		expect(interruptChat).toHaveBeenCalled();
	});

	it('stopGeneration keeps and persists the partial assistant tail', async () => {
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('部分输出的尾巴');
				await new Promise<void>((_resolve, reject) => {
					handlers.signal?.addEventListener('abort', () => {
						const err = new Error('aborted');
						err.name = 'AbortError';
						reject(err);
					});
				});
			},
		);
		const pending = useChatStore.getState().sendMessage('现在测试纯文字');
		await vi.waitFor(() => {
			expect(
				getSessionStream(useChatStore.getState(), 'sess_test').streamingText,
			).toContain('部分输出');
		});
		await useChatStore.getState().stopGeneration();
		expect(await pending).toBe(true);
		const msgs = useChatStore.getState().messagesById.sess_test ?? [];
		expect(msgs.some(m => m.role === 'assistant' && m.text.includes('部分输出的尾巴'))).toBe(
			true,
		);
	});

	it('createSideSession uses virtual space and selectSession keeps activeSpaceId', async () => {
		useChatStore.setState({
			sessions: [session('sess_main', {title: '主'})],
			activeId: 'sess_main',
			activeSpaceId: DEFAULT_SPACE_ID,
			messagesById: {},
		});
		const sid = await useChatStore.getState().createSideSession();
		expect(sid.startsWith('side-')).toBe(true);
		const st = useChatStore.getState();
		expect(st.activeId).toBe(sid);
		expect(st.activeSpaceId).toBe(DEFAULT_SPACE_ID);
		expect(st.sessions.find(s => s.id === sid)?.spaceId).toBe(SIDE_SPACE_ID);

		// 切回主会话后再进侧聊：activeSpaceId 不被侧聊接管
		await useChatStore.getState().selectSession(sid);
		expect(useChatStore.getState().activeId).toBe(sid);
		expect(useChatStore.getState().activeSpaceId).toBe(DEFAULT_SPACE_ID);
	});

	it('side sessions can send without a workspace bound', async () => {
		useChatStore.setState({
			sessions: [],
			activeId: null,
			activeSpaceId: DEFAULT_SPACE_ID,
			spaces: [space({rootPath: ''})],
			messagesById: {},
			historyById: {},
			errorBanner: null,
			errorBannerSessionId: null,
		});
		await useChatStore.getState().createSideSession();
		const sid = useChatStore.getState().activeId!;
		expect(sid.startsWith('side-')).toBe(true);
		streamChat.mockImplementation(
			async (
				_sid: string,
				_msgs: unknown,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('x');
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('你好呀')).toBe(true);
		const st = useChatStore.getState();
		expect(st.errorBannerSessionId).toBeNull();
		expect(st.errorBanner).toBeNull();
	});

	it('removeSession during stream clears lock and does not resurrect', async () => {
		let release!: () => void;
		const gate = new Promise<void>(r => {
			release = r;
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('x');
				await gate;
				handlers.onDone();
			},
		);
		const pending = useChatStore.getState().sendMessage('doomed');
		await vi.waitFor(() => {
			expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(
				true,
			);
		});
		await useChatStore.getState().removeSession('sess_test');
		release();
		await pending;
		expect(markSessionDeleted).toHaveBeenCalledWith('sess_test');
		expect(deleteServerSession).toHaveBeenCalledWith('sess_test');
		expect(useChatStore.getState().sessions).toEqual([]);
		expect(sessionStreamActive(useChatStore.getState(), 'sess_test')).toBe(false);
		expect(useChatStore.getState().messagesById.sess_test).toBeUndefined();
	});

	it('auto-creates session when activeId missing', async () => {
		useChatStore.setState({
			activeId: null,
			sessions: [],
			messagesById: {},
			spaces: [space({rootPath: 'D:\\proj'})],
			activeSpaceId: DEFAULT_SPACE_ID,
		});
		streamChat.mockImplementation(
			async (
				sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				expect(sid).toEqual(expect.any(String));
				handlers.onDelta('n');
				handlers.onDone();
			},
		);
		expect(await useChatStore.getState().sendMessage('first')).toBe(true);
		const st = useChatStore.getState();
		expect(st.sessions.length).toBe(1);
		expect(st.activeId).toBeTruthy();
		expect(
			st.messagesById[st.activeId!]?.some(m => m.text === 'first'),
		).toBe(true);
	});

	it('selectSession does not clobber in-memory messages with empty IDB', async () => {
		vi.mocked(loadMessages).mockResolvedValue([]);
		await useChatStore.getState().sendMessage('keep me');
		const before = useChatStore.getState().messagesById.sess_test ?? [];
		expect(before.length).toBeGreaterThan(0);
		await useChatStore.getState().selectSession('sess_test');
		expect(useChatStore.getState().messagesById.sess_test).toEqual(before);
		expect(loadMessages).not.toHaveBeenCalled();
	});
});

describe('chatStore hydrate', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

		it('resets cached in-progress rollback state during hydrate', async () => {
			const sp = space();
			const sess = session('sess_cached');
			vi.mocked(loadSpaces).mockResolvedValue([sp]);
			vi.mocked(loadSessions).mockResolvedValue([sess]);
			vi.mocked(loadMessages).mockResolvedValue([]);
			vi.mocked(loadRollbackState).mockResolvedValue({
				status: 'ready',
				phase: 'ready',
				targetMessageId: 'm1',
				editedText: 'edited',
				plan: null,
				job: null,
				idempotencyKey: null,
				error: null,
			});
			useChatStore.setState({hydrated: false, activeId: null, sessions: [], spaces: [], messagesById: {}});
			await useChatStore.getState().hydrate();
			expect(useChatStore.getState().rollbackById.sess_cached?.phase).toBe('idle');
			expect(loadRollbackState).toHaveBeenCalledWith('sess_cached');
		});

		it('v2 rollback retired: hydrate 一律 idle,未决态由 rewindV3 接管', async () => {
			// V2 前端已退役(spaceSessionSlice):启动不再 surface v2 的
			// committed_resend_failed,统一置 idle;重发失败接管方=rewindV3Store。
			const sp = space();
			const sess = session('sess_recover');
			vi.mocked(loadSpaces).mockResolvedValue([sp]);
			vi.mocked(loadSessions).mockResolvedValue([sess]);
			vi.mocked(loadMessages).mockResolvedValue([]);
			vi.mocked(loadRollbackState).mockResolvedValue({
				status: 'error',
				phase: 'committed_resend_failed',
				targetMessageId: 'm1',
				editedText: 'edited',
				plan: null,
				job: {session_id: 'sess_recover', plan_id: 'p1', job_id: 'j1', status: 'committed', created_at: 1, updated_at: 1, applied_operation_ids: []},
				idempotencyKey: 'idem_1',
				error: '未能重新发送',
			});
			useChatStore.setState({hydrated: false, activeId: null, sessions: [], spaces: [], messagesById: {}});
			await useChatStore.getState().hydrate();
			expect(useChatStore.getState().rollbackById.sess_recover?.phase).toBe(
				'idle',
			);
			expect(useChatStore.getState().errorBanner).toBeNull();
		});

	it('skips tombstoned sessions when importing from server', async () => {
		const sp = space();
		vi.mocked(loadSpaces).mockResolvedValue([sp]);
		vi.mocked(loadSessions).mockResolvedValue([]);
		vi.mocked(loadMessages).mockResolvedValue([]);
		vi.mocked(loadDeletedSessionIds).mockResolvedValue(new Set(['sess_dead']));
		listServerSessions.mockResolvedValue([
			{id: 'sess_dead', title: 'gone', createdAt: 1, updatedAt: 1},
		]);
		useChatStore.setState({
			hydrated: false,
			spaces: [],
			sessions: [],
			messagesById: {},
			activeId: null,
		});
		await useChatStore.getState().hydrate();
		expect(saveSession).not.toHaveBeenCalled();
		expect(useChatStore.getState().sessions).toEqual([]);
	});

		it('loads spaces/sessions/messages', async () => {
		const sp = space();
		const sess = session('sess_h');
		vi.mocked(loadSpaces).mockResolvedValue([sp]);
		vi.mocked(loadSessions).mockResolvedValue([sess]);
		vi.mocked(loadMessages).mockResolvedValue([
			{
				id: 'm1',
				role: 'user',
				text: 'hi',
				createdAt: 1,
			},
		]);
		useChatStore.setState({
			hydrated: false,
			spaces: [],
			sessions: [],
			messagesById: {},
			activeId: null,
		});
		await useChatStore.getState().hydrate();
		expect(useChatStore.getState().hydrated).toBe(true);
		expect(useChatStore.getState().activeId).toBe('sess_h');
		expect(useChatStore.getState().messagesById.sess_h?.[0]?.text).toBe(
			'hi',
		);
		expect(saveSession).not.toHaveBeenCalled();
	});
});

describe('chatStore openFolder — idempotent', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		setWorkspace.mockResolvedValue('/tmp');
		await seedSession();
	});

	it('reuses existing space for same path (slash/case variants)', async () => {
		const sp = space({
			id: 'space_xyai',
			name: 'xyai',
			rootPath: 'D:\\lea\\xyai',
		});
		useChatStore.setState({
			spaces: [space(), sp],
			activeSpaceId: DEFAULT_SPACE_ID,
		});
		const id1 = await useChatStore
			.getState()
			.openFolder('D:\\lea\\xyai');
		expect(id1).toBe('space_xyai');
		expect(saveSpace).not.toHaveBeenCalled();
		const id2 = await useChatStore
			.getState()
			.openFolder('\\\\?\\D:\\lea\\xyai');
		expect(id2).toBe('space_xyai');
		expect(
			useChatStore.getState().spaces.filter(s =>
				Boolean(s.rootPath && s.name === 'xyai'),
			),
		).toHaveLength(1);
	});

	it('concurrent opens of same folder resolve to one space', async () => {
		useChatStore.setState({spaces: [space()]});
		const [a, b] = await Promise.all([
			useChatStore.getState().openFolder('D:\\proj\\xyai'),
			useChatStore.getState().openFolder('D:/proj/xyai'),
		]);
		expect(a).toBe(b);
		expect(
			useChatStore
				.getState()
				.spaces.filter(s => s.rootPath && s.name === 'xyai'),
		).toHaveLength(1);
	});

	it('enterSpace focuses latest session instead of always creating', async () => {
		const sp = space({
			id: 'space_xyai',
			name: 'xyai',
			rootPath: 'D:\\lea\\xyai',
		});
		const older = session('sess_old', {
			spaceId: 'space_xyai',
			updatedAt: 1,
			title: '你好',
		});
		const newer = session('sess_new', {
			spaceId: 'space_xyai',
			updatedAt: 99,
			title: '新对话',
		});
		useChatStore.setState({
			spaces: [space(), sp],
			sessions: [older, newer, session('sess_test')],
			messagesById: {
				sess_old: [],
				sess_new: [],
				sess_test: [],
			},
			activeSpaceId: DEFAULT_SPACE_ID,
		});
		const id = await useChatStore.getState().enterSpace('space_xyai');
		expect(id).toBe('sess_new');
		expect(useChatStore.getState().activeId).toBe('sess_new');
		expect(saveSession).not.toHaveBeenCalled();
	});

	it('hydrate merges duplicate rootPath workspaces', async () => {
		const a = space({
			id: 'space_a',
			name: 'xyai',
			rootPath: 'D:\\lea\\xyai',
			updatedAt: 10,
		});
		const b = space({
			id: 'space_b',
			name: 'xyai',
			rootPath: 'd:/lea/xyai',
			updatedAt: 20,
		});
		const sessA = session('sess_a', {spaceId: 'space_a', updatedAt: 1});
		const sessB = session('sess_b', {spaceId: 'space_b', updatedAt: 2});
		vi.mocked(loadSpaces).mockResolvedValue([space(), a, b]);
		vi.mocked(loadSessions).mockResolvedValue([sessA, sessB]);
		vi.mocked(loadMessages).mockResolvedValue([]);
		useChatStore.setState({hydrated: false, spaces: [], sessions: []});
		await useChatStore.getState().hydrate();
		const spaces = useChatStore
			.getState()
			.spaces.filter(s => s.rootPath);
		expect(spaces).toHaveLength(1);
		expect(spaces[0]?.id).toBe('space_b');
		expect(
			useChatStore
				.getState()
				.sessions.every(s => s.spaceId === 'space_b'),
		).toBe(true);
		expect(deleteSpaceRecord).toHaveBeenCalledWith('space_a');
	});
});

describe('chatStore drain — burst deltas must still commit (multi-agent summary)', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		setWorkspace.mockResolvedValue('/tmp');
		interruptChat.mockResolvedValue(undefined);
		await seedSession();
		useChatStore.setState({sessionStreams: {}});
	});

	it('commits the full streamed text when onDone enters drain path', async () => {
		// 手动泵 rAF：jsdom 环境下帧回调不保证触发，逐帧驱动排水循环。
		let rafQueue: FrameRequestCallback[] = [];
		const origRaf = window.requestAnimationFrame;
		window.requestAnimationFrame = (cb: FrameRequestCallback): number => {
			rafQueue.push(cb);
			return rafQueue.length;
		};

		try {
			// 4000 字符一次性到达 → backlog ≫64 → 必走 startDrain。
			streamChat.mockImplementation(
				async (
					_sid: string,
					_text: string,
					handlers: ChatStreamHandlers,
				) => {
					handlers.onDelta('多Agent结果摘要'.repeat(500));
					handlers.onDone();
				},
			);

			await useChatStore.getState().sendMessage('跑批');

			const afterDone = useChatStore.getState();
			const afterStream = getSessionStream(afterDone, 'sess_test');
			// 排水已启动：stream 锁释放、drain 标记生效；正文已在 startDrain 落盘以防刷新丢失。
			expect(afterStream.isLoading).toBe(false);
			expect(afterStream.draining).toBe(true);
			expect(
				useChatStore
					.getState()
					.messagesById.sess_test?.some(m => m.role === 'assistant'),
			).toBe(true);

			// 泵帧直到排水完成（96 码点/帧 × 数十帧）。
			for (let i = 0; i < 200; i += 1) {
				if (!getSessionStream(useChatStore.getState(), 'sess_test').draining) {
					break;
				}
				const queue = rafQueue;
				rafQueue = [];
				for (const cb of queue) {
					cb(0);
				}
				await Promise.resolve();
			}

			const done = useChatStore.getState();
			expect(getSessionStream(done, 'sess_test').draining).toBe(false);
			const asst = done.messagesById.sess_test?.find(
				m => m.role === 'assistant',
			);
			// 回归点：此前 out='' → 消息静默丢失；现在必须完整落盘。
			expect(asst?.text).toBe('多Agent结果摘要'.repeat(500));
			expect(getSessionStream(done, 'sess_test').streamingText).toBe('');
		} finally {
			window.requestAnimationFrame = origRaf;
		}
	});
});

describe('chatStore selectSession — optimistic switching', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	function twoSessions() {
		useChatStore.setState({
			hydrated: true,
			spaces: [space({rootPath: 'D:\\proj'})],
			sessions: [session('sess_a'), session('sess_b')],
			activeId: 'sess_a',
			activeSpaceId: DEFAULT_SPACE_ID,
			messagesById: {},
			messagesLoadingIds: {},
			historyById: {},
			sessionStreams: {},
			errorBanner: null,
			errorBannerSessionId: null,
		});
	}

	it('sets activeId synchronously for cold sessions (does not await messages)', async () => {
		twoSessions();
		vi.mocked(loadMessages).mockResolvedValue([
			{id: 'm1', role: 'user', text: 'hi', createdAt: 1},
		]);
		let resolveBackfill!: (v: unknown) => void;
		loadServerSessionMessages.mockImplementation(
			() =>
				new Promise(resolve => {
					resolveBackfill = resolve;
				}),
		);
		const pending = useChatStore.getState().selectSession('sess_b');
		// selectSession 首个 await 之前必须已落 activeId（乐观切换核心断言）
		expect(useChatStore.getState().activeId).toBe('sess_b');
		expect(useChatStore.getState().messagesLoadingIds.sess_b).toBe(true);
		await pending;
		// 本地 IDB 先行：不等服务端回填即可渲染
		await vi.waitFor(() => {
			expect(useChatStore.getState().messagesById.sess_b?.[0]?.text).toBe('hi');
		});
		// 回填仍挂起 → 装载标记保持
		expect(useChatStore.getState().messagesLoadingIds.sess_b).toBe(true);
		resolveBackfill(undefined);
		await vi.waitFor(() => {
			expect(useChatStore.getState().messagesLoadingIds.sess_b).toBeUndefined();
		});
		// 回填结果（本地内容）不丢
		expect(useChatStore.getState().messagesById.sess_b?.[0]?.text).toBe('hi');
	});

	it('does not write an empty local snapshot while backfill is pending', async () => {
		twoSessions();
		vi.mocked(loadMessages).mockResolvedValue([]);
		let resolveBackfill!: (v: unknown) => void;
		loadServerSessionMessages.mockImplementation(
			() =>
				new Promise(resolve => {
					resolveBackfill = resolve;
				}),
		);
		await useChatStore.getState().selectSession('sess_b');
		await vi.waitFor(() => {
			// 回填已开跑（意味着本地空快照阶段已过，但无内容可先行写入）
			expect(loadServerSessionMessages).toHaveBeenCalledWith('sess_b');
		});
		expect(useChatStore.getState().messagesById.sess_b).toBeUndefined();
		resolveBackfill(undefined);
		// 回填定夺：仍无人填充 → 写入最终结果（空）并清装载标记
		await vi.waitFor(() => {
			expect(useChatStore.getState().messagesById.sess_b).toEqual([]);
		});
		expect(useChatStore.getState().messagesLoadingIds.sess_b).toBeUndefined();
	});
});
