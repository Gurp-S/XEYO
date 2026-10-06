import {beforeEach, describe, expect, it, vi} from 'vitest';
import {handleComposerSlash, lastUserMessage, runSlashCommand} from '@/lib/slashCommands';
import type {ChatMessage} from '@/lib/types';
import {toast} from '@/lib/toast';

// mock fetch 以捕获 /v1/slash 的 server 命令调用
const fetchMock = vi.fn(async () =>
	new Response(JSON.stringify({handled: true, message: 'done'}), {
		status: 200,
		headers: {'content-type': 'application/json'},
	}),
);

const chatState = {
	appendLocalNote: vi.fn(),
	sendMessage: vi.fn(),
	sessionStreams: {},
	messagesById: {} as Record<string, ChatMessage[]>,
	sessionGoalById: {} as Record<string, unknown>,
};

// /goal 的投影同步是网络动作：测试里替掉它，只验"反馈落在哪个表面"。
const syncGoal = vi.hoisted(() => vi.fn());

vi.mock('@/lib/goalSync', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/goalSync')>();
	return {...actual, syncGoalAfterCommand: syncGoal};
});

vi.mock('@/lib/api', async () => {
	const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
	return {
		...actual,
		fetchSkills: vi.fn(async () => ({ok: true, skills: []})),
	};
});

vi.mock('@/stores/chatStore', () => ({
	useChatStore: {
		getState: () => chatState,
	},
}));

describe('runSlashCommand dispatch', () => {
	const opts = {
		sessionId: 'sess_1',
		backendSessionId: 'b_sess_1',
		workspace: '/ws',
		onNewSession: vi.fn(),
		onRetryLast: vi.fn(),
	};

	beforeEach(() => {
		vi.clearAllMocks();
		chatState.sessionStreams = {};
		chatState.messagesById = {};
		chatState.sessionGoalById = {};
		syncGoal.mockResolvedValue({ok: true, note: ''});
		globalThis.fetch = fetchMock as unknown as typeof fetch;
	});

	it('treats plain text as not-slash', async () => {
		const out = await runSlashCommand('hello world', opts);
		expect(out.status).toBe('not-slash');
	});

	it('returns unknown for an unregistered command', async () => {
		const out = await runSlashCommand('/nonsense-cmd-xyz', opts);
		expect(out.status).toBe('unknown');
		if (out.status !== 'unknown') return;
		expect(out.name).toBe('nonsense-cmd-xyz');
	});

	it('routes /run to a send prompt', async () => {
		const out = await runSlashCommand('/run echo hi', opts);
		expect(out.status).toBe('send');
		if (out.status !== 'send') return;
		expect(out.text).toContain('/run');
		expect(out.text).toContain('echo hi');
	});

	it('calls /v1/slash for a server command and echoes result', async () => {
		fetchMock.mockResolvedValueOnce(
			new Response(JSON.stringify({handled: true, message: 'exported'}), {
				status: 200,
				headers: {'content-type': 'application/json'},
			}),
		);
		const out = await runSlashCommand('/export file.md', opts);
		expect(out.status).toBe('server');
		if (out.status !== 'server') return;
		expect(out.text).toBe('exported');
		expect(fetchMock).toHaveBeenCalledOnce();
	});

	it('enforces idle-only commands even when the caller omitted sessionBusy', async () => {
		chatState.sessionStreams = {
			sess_1: {isLoading: true, abortRef: {signal: {aborted: false}}},
		};
		const onNewSession = vi.fn();
		const out = await runSlashCommand('/clear', {...opts, onNewSession});

		expect(out.status).toBe('rejected');
		expect(onNewSession).not.toHaveBeenCalled();
	});

	it('handleComposerSlash notes unknown commands without consuming the draft', async () => {
		const consumed = await handleComposerSlash('/nonsense-cmd-xyz', opts);
		expect(consumed).toBe(false);
		expect(chatState.appendLocalNote).toHaveBeenCalled();
	});

	it('/goal 设上了就不在转录里落卡：目标条带就是回执', async () => {
		chatState.sessionGoalById = {sess_1: {goal: {status: 'active'}, driver: null}};
		const info = vi.spyOn(toast, 'info').mockImplementation(() => {});
		const consumed = await handleComposerSlash('/goal 重构登录模块并跑通测试', opts);
		expect(consumed).toBe(true);
		expect(chatState.appendLocalNote).not.toHaveBeenCalled();
		// 成功不啰嗦：条带出现本身就是反馈。
		expect(info).not.toHaveBeenCalled();
		info.mockRestore();
	});

	it('/goal 没设上（缺参数/投影无目标）→ 说一句 toast，但仍然不落转录卡', async () => {
		syncGoal.mockResolvedValue({ok: false, note: '投影里没有活跃目标'});
		const info = vi.spyOn(toast, 'info').mockImplementation(() => {});
		const consumed = await handleComposerSlash('/goal', opts);
		expect(consumed).toBe(true);
		expect(chatState.appendLocalNote).not.toHaveBeenCalled();
		expect(info).toHaveBeenCalled();
		info.mockRestore();
	});

	it('handleComposerSlash returns false for non-slash text', async () => {
		const consumed = await handleComposerSlash('not a slash', opts);
		expect(consumed).toBe(false);
	});

	it('retries the latest delivered prompt instead of a still-queued prompt', () => {
		chatState.messagesById.sess_1 = [
			{id: 'sent', role: 'user', text: 'earlier request', createdAt: 1},
			{
				id: 'queued',
				role: 'user',
				text: 'later request',
				queueState: 'queued',
				createdAt: 2,
			},
		];

		expect(lastUserMessage('sess_1')).toEqual({
			text: 'earlier request',
			mediaRefs: [],
		});
	});
});
