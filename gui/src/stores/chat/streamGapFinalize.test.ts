/**
 * 发送路径的 `stream_gap` 收尾契约：引擎在这条连接上丢了帧 ⇒ 本地尾巴是缺段，
 * 绝不能拿它提交最终消息，必须改用服务端 transcript。
 *
 * 引擎侧记洞与终止帧见 `python/engine/turn_runner.py`（门：
 * `tests/test_stream_subscriber_overflow.py`）；恢复路径的同源实现见
 * `streamRecoverySlice.ts`。本档钉的是**发送路径**——此前它对 `stream_gap`
 * 根本没有分支，界面会把截断的尾巴当完整答案留下（还要用户手动重试、整枪重付）。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';

const streamChat = vi.fn();
const loadServerSessionMessages = vi.fn();
const replaceMessages = vi.fn();

vi.mock('@/lib/db', async importOriginal => {
	const real = await importOriginal<typeof import('@/lib/db')>();
	return {
		...real,
		loadMessages: () => Promise.resolve([]),
		replaceMessages: (sessionId: string, messages: unknown[]) =>
			replaceMessages(sessionId, messages),
	};
});

vi.mock('@/lib/api', async importOriginal => {
	const real = await importOriginal<typeof import('@/lib/api')>();
	return {
		...real,
		streamChat: (sessionId: string, msgs: unknown, handlers: Handlers) =>
			streamChat(sessionId, msgs, handlers),
		loadServerSessionMessages: (sessionId: string) =>
			loadServerSessionMessages(sessionId),
		// 发送前会把工作区绑到后端；jsdom 里没有 origin，真实 fetch 必失败。
		setWorkspace: () => Promise.resolve({ok: true}),
	};
});

vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: Object.assign(() => ({}), {
		getState: () => ({apiKey: 'test-key', smoothness: true}),
		setState: vi.fn(),
	}),
	isSmoothnessOn: () => true,
}));

type Handlers = {
	onAccepted?: (status: number) => void;
	onDelta?: (chunk: string) => void;
	onStreamGap?: () => void;
	onDone?: () => void;
	onError?: (message: string, opts?: {kind?: string}) => void;
};

const {useChatStore} = await import('../chatStore');

const SID = 'sess_gap_finalize';

const SERVER_ROWS = [
	{id: 'a1', role: 'assistant', text: '完整答案全文', createdAt: 2000},
];

function seedStore() {
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
		spaces: [
			{
				id: 'space_default',
				name: 'ws',
				rootPath: 'D:/xeyo-test-ws',
				createdAt: 1,
				updatedAt: 1,
			},
		] as never,
		historyById: {[SID]: {messages: [], cursor: 0}} as never,
		messagesById: {},
		messagesLoadingIds: {},
		sessionStreams: {},
	});
}

async function settle() {
	for (let i = 0; i < 6; i++) {
		await new Promise(resolve => setTimeout(resolve, 0));
	}
}

function storedTexts() {
	const rows = useChatStore.getState().messagesById[SID] as
		| {text?: string}[]
		| undefined;
	return (rows ?? []).map(row => String(row.text ?? ''));
}

describe('发送路径遇到 stream_gap 改用服务端 transcript 收尾', () => {
	beforeEach(() => {
		streamChat.mockReset();
		loadServerSessionMessages.mockReset();
		replaceMessages.mockReset();
		replaceMessages.mockResolvedValue(undefined);
		seedStore();
	});

	it('流里报了洞 ⇒ 提交服务端正文，本地缺段绝不留档', async () => {
		streamChat.mockImplementation(
			async (_sid: string, _msgs: unknown, h: Handlers) => {
				h.onAccepted?.(200);
				h.onDelta?.('前半');
				h.onStreamGap?.();
				h.onDone?.();
			},
		);
		loadServerSessionMessages.mockResolvedValue(SERVER_ROWS as never);

		const sent = await useChatStore.getState().sendMessage('问题', []);
		await settle();

		expect(sent).toBe(true);
		expect(loadServerSessionMessages).toHaveBeenCalled();
		const texts = storedTexts();
		expect(texts).toContain('完整答案全文');
		expect(texts.some(t => t === '前半')).toBe(false);
	});

	it('反向校准：没有洞就不回拉 transcript，照旧提交本地尾巴', async () => {
		streamChat.mockImplementation(
			async (_sid: string, _msgs: unknown, h: Handlers) => {
				h.onAccepted?.(200);
				h.onDelta?.('完整答案全文');
				h.onDone?.();
			},
		);

		const sent = await useChatStore.getState().sendMessage('问题', []);
		await settle();

		expect(sent).toBe(true);
		expect(loadServerSessionMessages).not.toHaveBeenCalled();
		expect(storedTexts()).toContain('完整答案全文');
	});

	it('拉不到服务端记录时退回本地提交，绝不静默卡住', async () => {
		streamChat.mockImplementation(
			async (_sid: string, _msgs: unknown, h: Handlers) => {
				h.onAccepted?.(200);
				h.onDelta?.('能看到的尾巴');
				h.onStreamGap?.();
				h.onDone?.();
			},
		);
		loadServerSessionMessages.mockResolvedValue([] as never);

		await useChatStore.getState().sendMessage('问题', []);
		await settle();

		expect(storedTexts()).toContain('能看到的尾巴');
	});
});
