/**
 * 排队消息投递后的转录顺序（事故回归）。
 *
 * 事故：排队消息在 settle 排水后进转录，客户端把「本地 ms」与「服务端 transcript ts」
 * 两套时钟混在一起按 createdAt 重排（`inboxSlice.refreshInbox` 的 ack 分支），
 * 结果「先发那轮的回复」被排到排队消息与其回复之后 —— 看起来像排队消息被直发。
 * 服务端 transcript 行序本身是对的（`GET /v1/sessions/{sid}/messages` 实测）。
 *
 * 不变量：转录顺序 = 数组位置（本地既有顺序 + 服务端尾行顺次追加），不按时间戳重排。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {InboxSnapshot} from '@/lib/api';
import {DEFAULT_SPACE_ID} from '@/lib/db';
import type {ChatMessage} from '@/lib/types';

const loadServerSessionMessages = vi.fn();
const inboxSnapshotApi = vi.fn(async (): Promise<InboxSnapshot | null> => ({
	autorun: true,
	coalesce: false,
	items: [],
}));
const acknowledgeInboxItemsApi = vi.fn(
	async (_sessionId: string, _queueIds: string[]) => true,
);

vi.mock('@/lib/api', () => ({
	streamChat: vi.fn(),
	interruptChat: vi.fn(),
	setWorkspace: vi.fn(),
	previewRollback: vi.fn(),
	executeRollback: vi.fn(),
	resolveRollbackRecovery: vi.fn(),
	loadServerSessionMessages: (sessionId: string) => loadServerSessionMessages(sessionId),
	inboxSnapshot: () => inboxSnapshotApi(),
	acknowledgeInboxItems: (sessionId: string, queueIds: string[]) =>
		acknowledgeInboxItemsApi(sessionId, queueIds),
	cancelInboxItem: vi.fn(async () => true),
	editInboxItem: vi.fn(async () => true),
	listServerSessions: vi.fn(async () => []),
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
		deleteMessageForSession: vi.fn(async () => undefined),
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

vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: Object.assign(() => ({}), {
		getState: () => ({
			apiKey: 'test-key',
			smoothness: true,
			openSettings: vi.fn(),
			closeSettings: vi.fn(),
			settingsModalOpen: false,
		}),
		setState: vi.fn(),
	}),
	isSmoothnessOn: (v?: unknown) => v !== false,
}));

import {useChatStore} from '../chatStore';

const SID = 'sess_order';
/** 本地行用客户端时钟（大）；服务端行用 transcript ts（无 ts 时退化成行号，小）。 */
const LOCAL_NOW = 1_790_000_000_000;

function userMessage(id: string, text: string, extra?: Partial<ChatMessage>): ChatMessage {
	return {id, role: 'user', text, createdAt: LOCAL_NOW, ...extra};
}

beforeEach(() => {
	vi.clearAllMocks();
	useChatStore.setState({
		hydrated: true,
		spaces: [
			{
				id: DEFAULT_SPACE_ID,
				name: 'ws',
				rootPath: 'D:\\proj',
				createdAt: LOCAL_NOW,
				updatedAt: LOCAL_NOW,
			},
		],
		sessions: [
			{
				id: SID,
				spaceId: DEFAULT_SPACE_ID,
				title: '新对话',
				createdAt: LOCAL_NOW,
				updatedAt: LOCAL_NOW,
			},
		],
		activeId: SID,
		activeSpaceId: DEFAULT_SPACE_ID,
		errorBanner: null,
		errorBannerSessionId: null,
		messagesById: {[SID]: []},
		historyById: {},
		sessionStreams: {},
		inboxBySession: {},
	});
});

describe('inbox ack 的转录顺序', () => {
	it('服务端尾行的 ts 更小也不得把它们排到本地行之前（按位置合并）', async () => {
		// 本地：第一轮 prompt/reply + 已被投递（release 移到末尾）的排队气泡。
		const prompt = userMessage('msg-user-1', 'ok: busy xxx');
		const reply = {
			id: 'msg-reply-1',
			role: 'assistant' as const,
			text: 'ok: ok: busy xxx',
			createdAt: LOCAL_NOW + 4_000,
		};
		const queued = userMessage('msg-queued', 'ORDER-MARK', {
			createdAt: LOCAL_NOW + 1_000,
		});
		useChatStore.setState({
			messagesById: {[SID]: [prompt, reply, queued]},
		});
		// 服务端：这条排队消息以同一个 id 落进 transcript（时间戳来自服务端 ts / 行号）。
		inboxSnapshotApi.mockResolvedValueOnce({
			autorun: true,
			coalesce: false,
			items: [
				{
					queue_id: 'q1',
					text: 'ORDER-MARK',
					media_refs: [],
					message_id: 'msg-queued',
					delivery_id: 'msg-queued',
					queued_at: LOCAL_NOW + 1_000,
					attempts: 0,
					state: 'delivered',
				},
			],
		} as unknown as InboxSnapshot);
		loadServerSessionMessages.mockResolvedValueOnce([
			{...prompt},
			{...reply},
			{id: 'msg-queued', role: 'user', text: 'ORDER-MARK', createdAt: 1_000},
			{
				id: 'msg-ok-queued',
				role: 'assistant',
				text: 'ok: ORDER-MARK',
				createdAt: 1_100,
			},
		]);

		await useChatStore.getState().refreshInbox(SID);

		const got = (useChatStore.getState().messagesById[SID] ?? []).map(m => m.id);
		expect(got).toEqual(['msg-user-1', 'msg-reply-1', 'msg-queued', 'msg-ok-queued']);
		// 反事实：按 createdAt 重排会得到完全不同的顺序（旧实现的形状）——
		// 这条断言保证用例真能咬住「不许按时间戳重排」这个不变量。
		const byTime = (useChatStore.getState().messagesById[SID] ?? [])
			.slice()
			.sort((a, b) => a.createdAt - b.createdAt)
			.map(m => m.id);
		expect(byTime).not.toEqual(got);
	});
});
