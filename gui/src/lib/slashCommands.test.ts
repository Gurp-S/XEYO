import {beforeEach, describe, expect, it, vi} from 'vitest';
import {handleComposerSlash, runSlashCommand} from '@/lib/slashCommands';

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
};

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

	it('handleComposerSlash consumes unknown command and notes it', async () => {
		const consumed = await handleComposerSlash('/nonsense-cmd-xyz', opts);
		expect(consumed).toBe(true);
		expect(chatState.appendLocalNote).toHaveBeenCalled();
	});

	it('handleComposerSlash returns false for non-slash text', async () => {
		const consumed = await handleComposerSlash('not a slash', opts);
		expect(consumed).toBe(false);
	});
});
