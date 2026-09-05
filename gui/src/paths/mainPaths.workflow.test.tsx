/**
 * 主路径部件集成（no-e2e · jsdom）：
 * 真实 chatStore + 真实 MessageList 组件，mock 传输层（@/lib/api）与持久层（@/lib/db）。
 * 覆盖主路径：发（send）/ 停（stop）。权限 / reattach / 回溯按同一骨架后续补齐。
 * 门禁哲学与拆除脚本一致：失败即红。
 */
import {render, screen} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {ChatStreamHandlers} from '@/lib/api';
import {DEFAULT_SPACE_ID, replaceMessages} from '@/lib/db';
import {sessionStreamActive} from '@/lib/sessionStreams';
import type {ChatSession, ChatSpace} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {MessageList} from '@/components/MessageList';

vi.stubGlobal('IntersectionObserver', undefined);

class ResizeObserverStub {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

// jsdom 未实现 <dialog>.showModal/close（回溯确认弹窗需要）
if (typeof HTMLDialogElement !== 'undefined') {
	HTMLDialogElement.prototype.showModal = () => {};
	HTMLDialogElement.prototype.close = () => {};
}

vi.mock('@/components/MarkdownView', async (importOriginal) => {
	const actual = await importOriginal<
		typeof import('@/components/MarkdownView')
	>();
	return {
		...actual,
		MarkdownView: ({content}: {content: string}) => (
			<div data-testid="md">{content}</div>
		),
	};
});

// 注意：streamSendSlice 的 onDelta 会调用本模块的 advanceTypewriterShown，
// mock 必须保留真实导出（importOriginal 展开），只覆盖 hook 本身；
// 否则流式首 delta 即抛错 → send 走 catch 清流（无 assistant 消息）。
vi.mock('@/hooks/useStreamTypewriter', async (importOriginal) => {
	const actual = await importOriginal<
		typeof import('@/hooks/useStreamTypewriter')
	>();
	return {
		...actual,
		useStreamTypewriter: (t: string) => t,
		typewriterStep: () => 1,
	};
});

vi.mock('@/hooks/useDebounced', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@/hooks/useDebounced')>();
	return {
		...actual,
		useDebounced: (v: unknown) => v,
	};
});

const streamChat = vi.fn();
const interruptChat = vi.fn();
const setWorkspace = vi.fn();
const previewRollback = vi.fn();
const executeRollback = vi.fn();
const resolveRollbackRecovery = vi.fn();
const loadServerSessionMessages = vi.fn();
const listServerSessions = vi.fn(
	async (): Promise<
		{id: string; title: string; createdAt: number; updatedAt: number}[]
	> => [],
);

vi.mock('@/lib/api', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		streamChat: (...args: unknown[]) => streamChat(...args),
		interruptChat: (...args: unknown[]) => interruptChat(...args),
		setWorkspace: (...args: unknown[]) => setWorkspace(...args),
		previewRollback: (...args: unknown[]) => previewRollback(...args),
		executeRollback: (...args: unknown[]) => executeRollback(...args),
		resolveRollbackRecovery: (...args: unknown[]) =>
			resolveRollbackRecovery(...args),
		loadServerSessionMessages: (...args: unknown[]) =>
			loadServerSessionMessages(...args),
		listServerSessions: () => listServerSessions(),
		deleteServerSession: vi.fn(async () => true),
		fetchSessionTask: vi.fn(async () => null),
		streamTurnEvents: vi.fn(async () => undefined),
		abandonSessionRecovery: vi.fn(async () => true),
		readTurnCursor: vi.fn(() => 0),
		rememberTurnCursor: vi.fn(() => undefined),
	};
});

vi.mock('@/lib/db', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@/lib/db')>();
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
// 注意：组件会以 selector 调用 useSettingsStore（如 s => s.model），
// mock 必须像真 zustand 一样应用 selector，否则 model 成 {} 被 <span> 渲染即崩。
const settingsState = {
	apiKey: 'test-key',
	model: 'test-model',
	smoothness: true,
	openSettings,
	closeSettings: vi.fn(),
	settingsModalOpen: false,
};
vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: Object.assign(
		(sel?: (s: typeof settingsState) => unknown) =>
			typeof sel === 'function' ? sel(settingsState) : settingsState,
		{
			getState: () => settingsState,
			setState: vi.fn(),
		},
	),
	isSmoothnessOn: (v?: unknown) => v !== false,
}));

function space(partial?: Partial<ChatSpace>): ChatSpace {
	const now = Date.now();
	return {
		id: DEFAULT_SPACE_ID,
		name: 'XEYO code',
		rootPath: '',
		createdAt: now,
		updatedAt: now,
		...partial,
	};
}

function session(id: string, partial?: Partial<ChatSession>): ChatSession {
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

describe('主路径部件集成 — 发 / 停 / 权限 / reattach / 回溯', () => {
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

	it('发：空态 → 用户气泡上屏 → 助理流式落定（真实 store → 真实 MessageList）', async () => {
		render(<MessageList />);

		// 种子会话 messagesById 为空 → 空态 hero
		expect(screen.getByTestId('empty-quip')).toBeInTheDocument();

		await useChatStore.getState().sendMessage('你好');

		// 空态消失（hasRows）
		await vi.waitFor(() => {
			expect(screen.queryByTestId('empty-quip')).not.toBeInTheDocument();
		});
		// 用户气泡上屏
		expect(screen.getByText('你好')).toBeInTheDocument();

		// store 权威断言：user → assistant 顺序与内容
		const msgs = useChatStore.getState().messagesById['sess_test'] ?? [];
		expect(msgs[0]?.role).toBe('user');
		expect(msgs[0]?.text).toBe('你好');
		const assistant = msgs.find(m => m.role === 'assistant');
		expect(assistant?.text).toContain('Hello world');
		// 流已收尾
		expect(
			sessionStreamActive(useChatStore.getState(), 'sess_test'),
		).toBe(false);

		// 助理文本渲染（真实 XyStreamdown 直出，非 MarkdownView mock）
		await vi.waitFor(() => {
			expect(screen.getByText('Hello world')).toBeInTheDocument();
		});
	});

	it('空回复：模型 0 输出仅 onDone → 给出可见反馈而非静默（no-e2e 盲区回归）', async () => {
		// 复现真实场景：后端受理了回合，但模型流出 0 个 token 后正常收尾
		// （前端只能拿到 onDone，没有 onDelta）。修复前这里会只留用户气泡、
		// 无 assistant、无任何报错——即用户描述的“发送后无反应”。
		streamChat.mockImplementation(
			async (_sid: string, _text: string, handlers: ChatStreamHandlers) => {
				handlers.onDone();
			},
		);

		render(<MessageList />);
		await useChatStore.getState().sendMessage('请分析这个文件');

		// 流已收尾
		expect(
			sessionStreamActive(useChatStore.getState(), 'sess_test'),
		).toBe(false);

		// 不应静默消失：至少给出可见反馈（错误横幅 + 一条 system 说明）
		const st = useChatStore.getState();
		expect(st.errorBanner).toMatch(/空回复/);
		const msgs = st.messagesById['sess_test'] ?? [];
		expect(msgs.some(m => m.role === 'system' && /空回复/.test(m.text))).toBe(
			true,
		);
		// 且用户消息仍保留（回合已受理，不撤乐观追加）
		expect(msgs.some(m => m.role === 'user' && m.text === '请分析这个文件')).toBe(
			true,
		);
	});

	it('停：stopGeneration 中止流、解锁并通知后端 interrupt', async () => {
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

		render(<MessageList />);
		const pending = useChatStore.getState().sendMessage('stop me');

		await vi.waitFor(() => {
			expect(
				sessionStreamActive(useChatStore.getState(), 'sess_test'),
			).toBe(true);
		});

		await useChatStore.getState().stopGeneration();

		expect(await pending).toBe(true);
		expect(
			sessionStreamActive(useChatStore.getState(), 'sess_test'),
		).toBe(false);
		expect(interruptChat).toHaveBeenCalled();

		// UI 回到非加载态
		await vi.waitFor(() => {
			const st = useChatStore.getState().sessionStreams['sess_test'];
			expect(st?.isLoading ?? false).toBe(false);
		});
	});

	it('权限：tool ASK 挂起 → pendingPermission 可见 → resolved 清除 → 工具行落定', async () => {
		let releasePermission!: () => void;
		const permissionGate = new Promise<void>(resolve => {
			releasePermission = resolve;
		});
		streamChat.mockImplementation(
			async (
				_sid: string,
				_text: string,
				handlers: ChatStreamHandlers,
			) => {
				handlers.onDelta('写入文件');
				handlers.onToolCall?.({
					name: 'Write',
					input: {path: 'a.txt'},
					toolUseId: 'p1',
				});
				handlers.onPermissionPending?.({
					kind: 'permission_pending',
					requestId: 'req_1',
					toolName: 'Write',
					input: {path: 'a.txt'},
					reason: 'outbound',
					prompt: '允许写入 a.txt 吗？',
					choices: ['deny', 'remind', 'allow'],
				});
				// 挂起：等权限解析（后端批准后续推）
				await permissionGate;
				handlers.onPermissionResolved?.({
					kind: 'permission_resolved',
					requestId: 'req_1',
					approved: true,
					actor: 'user',
					reason: '',
				});
				handlers.onToolResult?.({
					name: 'Write',
					output: 'ok',
					is_error: false,
				});
				handlers.onDone();
			},
		);

		render(<MessageList />);
		const pending = useChatStore.getState().sendMessage('写入文件');

		// ASK 挂起态（权限弹窗数据在 store，弹窗本体在 app 层）
		await vi.waitFor(() => {
			const p = useChatStore.getState().pendingPermission;
			expect(p?.requestId).toBe('req_1');
			expect(p?.toolName).toBe('Write');
			expect(p?.sessionId).toBe('sess_test');
		});

		// 批准 → 后端续推 resolved + result
		releasePermission();
		expect(await pending).toBe(true);
		expect(useChatStore.getState().pendingPermission).toBeNull();

		// 工具行落定 done，DOM 呈现输出
		const tool = (useChatStore.getState().messagesById['sess_test'] ?? []).find(
			m => m.role === 'tool',
		);
		expect(tool?.toolStatus).toBe('done');
		expect(tool?.text).toBe('ok');
		// 工具行（activity 面板）以本地化动词呈现完成态（"Wrote a.txt"）
		await vi.waitFor(() => {
			expect(
				document.querySelector('.xy-activity-detail-inner')?.textContent,
			).toContain('Wrote');
		});
	});

	it('reattach：崩溃残留孤儿工具 → recoverStuckStream 收敛 → UI 呈现工具行', async () => {
		useChatStore.setState({
			sessionStreams: {},
			messagesById: {
				sess_test: [
					{id: 'u1', role: 'user', text: 'hi', createdAt: 1},
					{
						id: 't1',
						role: 'tool',
						toolName: 'TodoWrite',
						toolInput: '{"todos":[]}',
						toolStatus: 'running',
						text: '',
						createdAt: 2,
					},
				],
			},
		});
		render(<MessageList />);
		// 刷新前：running 工具行（activity 折叠行）在 UI
		expect(document.querySelector('.xy-activity-split')).not.toBeNull();

		useChatStore.getState().recoverStuckStream();

		const tool = (useChatStore.getState().messagesById['sess_test'] ?? []).find(
			m => m.id === 't1',
		);
		expect(tool?.toolStatus).toBe('error');
		expect(tool?.text).toContain(
			'interrupted (stream ended without tool result)',
		);
		expect(replaceMessages).toHaveBeenCalled();
		// 注：错误详情文本（interrupted…）折叠态不渲染（UI 改进点）；
		// DOM 层断言工具行仍在且呈现该工具的动词摘要（"Checked to-do list"）。
		expect(
			document.querySelector('.xy-activity-detail-inner')?.textContent,
		).toContain('to-do list');
	});

	it('回溯 v3：openDialog → RewindV3Dialog；v2 preview 已退役', async () => {
		const messages = [
			{id: 'm1', role: 'user' as const, text: 'old', createdAt: 1},
			{id: 'm2', role: 'assistant' as const, text: 'answer', createdAt: 2},
		];
		useChatStore.setState({messagesById: {sess_test: messages}});

		const {useRewindV3Store} = await import('@/stores/rewindV3Store');
		render(<MessageList />);

		useRewindV3Store.getState().openDialog('sess_test', 'm1', '回溯测试编辑');
		await vi.waitFor(() => {
			expect(screen.getByText('回溯到这条对话')).toBeInTheDocument();
		});
		expect(useRewindV3Store.getState().bySession.sess_test?.phase).toBe('dialog');
	});
});
