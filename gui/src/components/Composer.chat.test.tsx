import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {resetComposerDraftsForTests} from '@/lib/composerDrafts';
import {SIDE_SPACE_ID} from '@/lib/db';
import type {InboxQueuedItem} from '@/stores/chat/preStoreHelpers';
import {patchSessionStream} from '@/lib/sessionStreams';

const {chatState, sendMessage, stopGeneration, fetchSkills} = vi.hoisted(() => {
	const sendMessage = vi.fn();
	const stopGeneration = vi.fn();
	const fetchSkills = vi.fn(async () => ({
		ok: true,
		skills: [] as import('@/lib/api').SkillInfo[],
	}));
	const chatState = {
		activeId: 'sess_1' as string | null,
		// Composer 现在读 s.sessions / s.spaces（activeWorkspace 选择器）。
		sessions: [] as {
			id: string;
			spaceId?: string;
		}[],
		spaces: [] as {
			id: string;
			rootPath?: string;
		}[],
		sessionStreams: {} as Record<
			string,
			import('@/lib/sessionStreams').SessionStreamState
		>,
		agentMode: 'agent' as const,
		setAgentMode: vi.fn(),
		sendMessage,
		stopGeneration,
		composerInsertSeq: 0,
		composerFocusSeq: 0,
		lastComposerInsert: null as {
			name: string;
			text?: string;
			path?: string;
		} | null,
		pendingAsk: null,
		pendingPermission: null,
		pendingPlan: null,
		historyById: {} as Record<string, unknown>,
		// 工作区已加的 P1 mid-turn inbox：夹具形状必须等于生产的
		// InboxQueuedItem——旧形状（queueId）会让组件读不到字段而用例照样绿。
		inboxBySession: {} as Record<string, InboxQueuedItem[]>,
		refreshInbox: vi.fn(async () => {}),
		cancelInboxItem: vi.fn(async () => {}),
		resumeInbox: vi.fn(async () => {}),
		sessionGoalById: {} as Record<
			string,
			{
				goal: {
					goal_id: string;
					title: string;
					text: string;
					status: string;
					max_rounds: number;
					rounds: number;
					revision: number;
					blocked_reason: string;
					pending_complete: boolean;
				};
				driver: {
					activation: string;
					pending: boolean;
					active_round: number[] | null;
				};
			}
		>,
	};
	return {chatState, sendMessage, stopGeneration, fetchSkills};
});

vi.mock('@/stores/chatStore', () => {
	const useChatStore = (
		selector: (s: typeof chatState) => unknown,
	) => selector(chatState);
	useChatStore.getState = () => chatState;
	return {useChatStore};
});

vi.mock('@/lib/api', () => ({
	uploadFile: vi.fn(),
	uploadMedia: vi.fn(async () => ({uri: '', media_ref: ''})),
	mediaUrl: (ref: string) => `https://api.test/media/${ref.slice('xeyo-media://'.length, 12)}`,
	resumeInbox: vi.fn(async () => true),
	fetchSkills,
	fetchVendorModels: vi.fn(async () => ({
		vendor_ok: true,
		data: [
			{id: 'deepseek-v4-flash', created: 2, modes: {thinking: []}},
			{id: 'deepseek-v4-pro', created: 1, modes: {thinking: []}},
		],
	})),
}));

const {handleComposerSlash} = vi.hoisted(() => ({
	handleComposerSlash: vi.fn(async () => false),
}));

vi.mock('@/lib/slashCommands', async importOriginal => {
	// 只替换"命令执行"这一条 seam；cachedSlashSkills / loadSlashSkills 用真实实现，
	// 这样斜杠弹层的技能候选走真正的缓存与 ok:false 逻辑（其 fetchSkills 已被 mock）。
	const actual = await importOriginal<typeof import('@/lib/slashCommands')>();
	return {...actual, handleComposerSlash};
});

import {uploadFile} from '@/lib/api';
import {resetSlashSkillCacheForTests} from '@/lib/slashCommands';
import {useSettingsStore} from '@/stores/settingsStore';
import {Composer} from './Composer';

/** 排队条目夹具：默认「排队中」的纯文本消息，按用例覆盖需要的字段。 */
const queueItem = (
	over: Partial<InboxQueuedItem> & Pick<InboxQueuedItem, 'queue_id' | 'text'>,
): InboxQueuedItem => ({
	media_refs: [],
	message_id: null,
	queued_at: 1,
	attempts: 0,
	state: 'queued',
	position: 1,
	...over,
});

describe('Composer send UX', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		resetComposerDraftsForTests();
		resetSlashSkillCacheForTests();
		// 忙时键位是可翻转偏好：用例之间必须回到默认档，否则上一条设的 'steer'
		// 会让本条的裸 Enter 悄悄变成引导，两条用例同时绿却各测各的。
		// 走 update() 而不是 setState()：全局夹具里的 settingsStore 是替身，只有 update。
		useSettingsStore.getState().update({busyEnter: 'queue'});
		chatState.activeId = 'sess_1';
		// 排队 dock 的条目读 chatState.inboxBySession：用例之间必须清空，
		// 否则上一条塞进去的队列会让本条的条数断言跟着变。
		chatState.inboxBySession = {};
		// 89351af 之后，取不到工作区根路径的会话一律不出技能候选（不再回落服务端的
		// 全局 UI cwd）——夹具不给 space/rootPath，这条路径就永远空跑、用例假绿。
		chatState.sessions = [{id: 'sess_1', spaceId: 'space_1'}];
		chatState.spaces = [{id: 'space_1', rootPath: 'D:/proj'}];
		chatState.sessionStreams = {};
		sendMessage.mockResolvedValue(true);
	});

	afterEach(() => {
		cleanup();
		resetComposerDraftsForTests();
	});

	it('clears input only after sendMessage accepts', async () => {
		const user = userEvent.setup();
		let release!: (v: boolean) => void;
		sendMessage.mockImplementation(
			() =>
				new Promise<boolean>(r => {
					release = r;
				}),
		);

		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, 'hello');
		await user.keyboard('{Enter}');

		expect(ta).toHaveValue('hello');
		release(true);
		await waitFor(() => expect(ta).toHaveValue(''));
		expect(sendMessage).toHaveBeenCalledWith(
'hello',
			[],
			[],
			'agent',
			expect.any(Function),
			false,
			// Composer 始终传会话级思考等级 opts（空 = 自动/模型默认）。
			// sessionId / background 是 6967123 起的必带项：发送要归到**这个**会话，
			// 且当前会话就是活动会话时不得标成后台（否则清草稿会落到别的会话上）。
			{reasoningEffort: '', steerIfBusy: false, sessionId: 'sess_1', background: false},
		);
	});

	it('keeps draft when sendMessage returns false', async () => {
		const user = userEvent.setup();
		sendMessage.mockResolvedValue(false);
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, 'keep');
		await user.keyboard('{Enter}');
		await waitFor(() => expect(sendMessage).toHaveBeenCalled());
		expect(ta).toHaveValue('keep');
	});

	it('does not send empty / whitespace-only', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '   ');
		await user.keyboard('{Enter}');
		expect(sendMessage).not.toHaveBeenCalled();
	});

	it('shows ghost hint after a command token with blank args', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		// claim hint 语义：/goal 精确命中且参数空白 → 灰字提示（仅覆盖层，不进草稿）。
		await user.type(ta, '/goal ');
		expect(screen.getByText('请输入目标，智能体将持续执行')).toBeInTheDocument();
		// 参数一旦非空白，提示立即消失。
		await user.type(ta, '每天检查构建');
		expect(screen.queryByText('请输入目标，智能体将持续执行')).not.toBeInTheDocument();
		// 灰字不进草稿。
		expect(ta).toHaveValue('/goal 每天检查构建');
	});

	it('keyboard pick inserts bare token + hint, never the usage placeholder', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		// 截图同款流程：/goa → ↓ 选中 goal → Enter。
		await user.type(ta, '/goa');
		fireEvent.keyDown(ta, {key: 'ArrowDown'});
		fireEvent.keyDown(ta, {key: 'Enter'});
		// 只回填 "/goal "，usage 里的 <目标> 占位符绝不进草稿；灰字立即接管提示。
		await waitFor(() => expect(ta).toHaveValue('/goal '));
		expect(screen.getByText('请输入目标，智能体将持续执行')).toBeInTheDocument();
		expect(ta).not.toHaveValue(expect.stringContaining('<目标>'));
	});

	it('lists skills with badge and description in the slash flyout', async () => {
		fetchSkills.mockResolvedValueOnce({
			ok: true,
			skills: [
				{
					name: 'map',
					description: '画图技能',
					source: 'workspace',
					plugin: '',
					tags: [],
					model_hint: '',
				},
			],
		});
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '/');
		// 技能组：分组头 + 裸名 + 描述都可见；技能行 hover 高亮下标在命令组之前。
		await waitFor(() => expect(screen.getByText('map')).toBeInTheDocument());
		expect(screen.getByText('技能')).toBeInTheDocument();
		expect(screen.getByText('画图技能')).toBeInTheDocument();
		expect(screen.getByText('命令')).toBeInTheDocument();
	});

	it('取不到工作区根路径就不请求技能清单（不回落服务端全局 cwd）', async () => {
		// 89351af 的隔离边界：侧链会话没有工作区，若照旧发请求，/v1/skills 会回落到
		// 服务端的 UI cwd —— 那是"另一个项目的技能"，不能出现在侧聊候选里。
		chatState.sessions = [{id: 'sess_1', spaceId: SIDE_SPACE_ID}];
		const user = userEvent.setup();
		render(<Composer />);
		await user.type(screen.getByLabelText('消息输入'), '/');
		await waitFor(() => expect(screen.getByLabelText('消息输入')).toHaveValue('/'));
		expect(fetchSkills).not.toHaveBeenCalled();
	});

	it('routes slash commands to handleComposerSlash, not sendMessage', async () => {
		handleComposerSlash.mockResolvedValue(true);
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '/export a.md');
		await user.keyboard('{Enter}');
		await waitFor(() =>
			expect(handleComposerSlash).toHaveBeenCalledWith('/export a.md', expect.any(Object)),
		);
		expect(sendMessage).not.toHaveBeenCalled();
	});

	it('裸 /goal 两枪 Enter：先选中回填命令名，补参数前不会被执行', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '/goal');
		// 第一枪：弹层开着且首行恒高亮（DSH popup.ts 的 active:0 口径）→ Enter 归弹层。
		await user.keyboard('{Enter}');
		await waitFor(() => expect(ta).toHaveValue('/goal '));
		expect(handleComposerSlash).not.toHaveBeenCalled();
		expect(sendMessage).not.toHaveBeenCalled();
		// 第二枪：只打了命令名 → 参数守卫拦下，草稿留在框里，灰字继续提示该填什么。
		await user.keyboard('{Enter}');
		expect(handleComposerSlash).not.toHaveBeenCalled();
		expect(sendMessage).not.toHaveBeenCalled();
		expect(ta).toHaveValue('/goal ');
		expect(screen.getByText('请输入目标，智能体将持续执行')).toBeInTheDocument();
		// 正控：补上参数后同一条路径必须照常执行。
		await user.type(ta, '重构登录模块');
		await user.keyboard('{Enter}');
		await waitFor(() =>
			expect(handleComposerSlash).toHaveBeenCalledWith(
				'/goal 重构登录模块',
				expect.any(Object),
			),
		);
	});

	it('slash menu: ArrowDown + Enter picks the highlighted suggestion instead of sending', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '/exp');
		// ↑ 高亮第一项 → Enter 选中该行（回填 usage），绝不透传成发送。
		fireEvent.keyDown(ta, {key: 'ArrowDown'});
		fireEvent.keyDown(ta, {key: 'Enter'});
		await waitFor(() => expect((ta as HTMLTextAreaElement).value.startsWith('/export ')).toBe(true));
		expect(sendMessage).not.toHaveBeenCalled();
		expect(handleComposerSlash).not.toHaveBeenCalled();
	});

	it('弹层开着时 Enter 先选中；Esc 收起后 Enter 才透传给命令网关', async () => {
		handleComposerSlash.mockResolvedValue(true);
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '/status');
		// /status 不要参数也一样：弹层在场时 Enter 属于弹层，不是发送。
		fireEvent.keyDown(ta, {key: 'Enter'});
		await waitFor(() => expect(ta).toHaveValue('/status '));
		expect(handleComposerSlash).not.toHaveBeenCalled();
		// Esc 收起弹层 → 这一枪才透传给 onSend 的斜杠网关。
		fireEvent.keyDown(ta, {key: 'Escape'});
		fireEvent.keyDown(ta, {key: 'Enter'});
		await waitFor(() =>
			expect(handleComposerSlash).toHaveBeenCalledWith('/status', expect.any(Object)),
		);
	});

	it('IME composing Enter does not send', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '你好');
		fireEvent.keyDown(ta, {key: 'Enter', isComposing: true});
		expect(sendMessage).not.toHaveBeenCalled();
		expect(handleComposerSlash).not.toHaveBeenCalled();
	});

	it('粘贴非图片文件：与拖放同一条附件链上传，不许静默无动作', async () => {
		vi.mocked(uploadFile).mockResolvedValue({
			id: 'f1',
			filename: 'note.txt',
			bytes: 5,
			text: 'hello',
			path: '',
			truncated: false,
		});
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		const file = new File(['hello'], 'note.txt', {type: 'text/plain'});
		fireEvent.paste(ta, {
			clipboardData: {
				items: [{kind: 'file', type: 'text/plain', getAsFile: () => file}],
			},
		});
		await waitFor(() => expect(uploadFile).toHaveBeenCalledWith(file));
	});

	it('粘贴「文本+文件」混合内容：文件走附件链，文本也必须进输入框（两样都不丢）', async () => {
		// 「图/文件 + 说明文字」是最常见的剪贴板形态；此前 preventDefault 后只走
		// 文件链、文本被静默吞（DSH 两者都保）。此处以非图片文件做判据（图片链
		// 与文件链在 onPaste 内同分支走到 preventDefault，丢字机理相同）。
		vi.mocked(uploadFile).mockResolvedValue({
			id: 'f2',
			filename: 'mix.txt',
			bytes: 5,
			text: 'hello',
			path: '',
			truncated: false,
		});
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入') as HTMLTextAreaElement;
		const file = new File(['hello'], 'mix.txt', {type: 'text/plain'});
		fireEvent.paste(ta, {
			clipboardData: {
				items: [{kind: 'file', type: 'text/plain', getAsFile: () => file}],
				getData: (t: string) => (t === 'text/plain' ? 'MIXED-TEXT' : ''),
			},
		});
		await waitFor(() => expect(uploadFile).toHaveBeenCalledWith(file));
		expect(ta.value).toContain('MIXED-TEXT');
	});

	it('keeps input available while streaming and shows stop control', async () => {
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
			statusText: 'thinking…',
		});
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		expect(screen.getByLabelText('停止生成')).toBeInTheDocument();
		expect(screen.getByTitle('停止生成')).toBeInTheDocument();
		expect(ta).not.toBeDisabled();
		await user.type(ta, '继续输入');
		expect(ta).toHaveValue('继续输入');
		expect(sendMessage).not.toHaveBeenCalled();
	});

	it('steers on Ctrl+Enter while streaming, and says so', async () => {
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
			statusText: 'thinking…',
		});
		const user = userEvent.setup();
		render(<Composer />);
		// 手势必须可见：忙时键位提示写在输入行 placeholder 里（DSH 卡外没有第二行）。
		expect(screen.getByLabelText('消息输入')).toHaveAttribute(
			'placeholder',
			'Ctrl+Enter 引导本回合 · Enter 排队',
		);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '先看测试再改');
		await user.keyboard('{Control>}{Enter}{/Control}');
		const call = sendMessage.mock.calls.at(-1) as unknown[];
		expect(call?.[6]).toEqual(expect.objectContaining({steerIfBusy: true}));
	});

	it('plain Enter while streaming queues instead of steering', async () => {
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
		});
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '排到回合结束');
		await user.keyboard('{Enter}');
		const call = sendMessage.mock.calls.at(-1) as unknown[];
		expect(call?.[6]).toEqual(expect.objectContaining({steerIfBusy: false}));
	});

	it('长按 Enter（键盘自动重复）不连发，松开后一次才算发送', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '按住不放');
		fireEvent.keyDown(ta, {key: 'Enter', repeat: true});
		fireEvent.keyDown(ta, {key: 'Enter', repeat: true});
		// onSend 里 sendMessage 落在微任务上：不先排空，"还没调用"就成了假绿。
		await new Promise(resolve => {
			setTimeout(resolve, 0);
		});
		expect(sendMessage).not.toHaveBeenCalled();
		// 正控：同一个 textarea 上非重复的 Enter 必须发得出去，否则上面那条
		// 只是"谁都没发"，测不出 repeat 守卫。
		await user.keyboard('{Enter}');
		expect(sendMessage).toHaveBeenCalledTimes(1);
	});

	it('偏好翻成 steer 后两键取反，且状态条措辞跟着改', async () => {
		useSettingsStore.getState().update({busyEnter: 'steer'});
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
			statusText: 'thinking…',
		});
		const user = userEvent.setup();
		render(<Composer />);
		expect(screen.getByLabelText('消息输入')).toHaveAttribute(
			'placeholder',
			'Enter 引导本回合 · Ctrl+Enter 排队',
		);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '裸 Enter 就该插话');
		await user.keyboard('{Enter}');
		expect((sendMessage.mock.calls.at(-1) as unknown[])[6]).toEqual(
			expect.objectContaining({steerIfBusy: true}),
		);
		await user.type(ta, '加速键改回排队');
		await user.keyboard('{Control>}{Enter}{/Control}');
		expect((sendMessage.mock.calls.at(-1) as unknown[])[6]).toEqual(
			expect.objectContaining({steerIfBusy: false}),
		);
	});

	it('多条队列默认折叠成计数头，点开才逐行可见', async () => {
		chatState.inboxBySession = {
			sess_1: [
				queueItem({queue_id: 'q1', text: '第一条排队', position: 1}),
				queueItem({queue_id: 'q2', text: '第二条排队', position: 2}),
			],
		};
		const user = userEvent.setup();
		render(<Composer />);
		expect(screen.getByText('2 条排队消息')).toBeInTheDocument();
		expect(screen.queryByText('第一条排队')).not.toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: /2 条排队消息/}));
		expect(screen.getByText('第一条排队')).toBeInTheDocument();
		expect(screen.getByText('第二条排队')).toBeInTheDocument();
	});

	it('单条队列不出计数头，直接可见', () => {
		chatState.inboxBySession = {
			sess_1: [queueItem({queue_id: 'q1', text: '只有一条'})],
		};
		render(<Composer />);
		expect(screen.queryByText(/条排队消息/)).not.toBeInTheDocument();
		expect(screen.getByText('只有一条')).toBeInTheDocument();
	});

	it('行内编辑时列表强制展开、计数头禁用（看不见自己在改哪行就不许收）', async () => {
		chatState.inboxBySession = {
			sess_1: [
				queueItem({queue_id: 'q1', text: '第一条排队', position: 1}),
				queueItem({queue_id: 'q2', text: '第二条排队', position: 2}),
			],
		};
		const user = userEvent.setup();
		render(<Composer />);
		await user.click(screen.getByRole('button', {name: /2 条排队消息/}));
		await user.click(screen.getAllByTitle('编辑消息')[0]);
		expect(screen.getByLabelText('编辑排队消息')).toBeInTheDocument();
		expect(screen.getByRole('button', {name: /2 条排队消息/})).toBeDisabled();
		expect(screen.getByText('第二条排队')).toBeInTheDocument();
	});

	it('排队行的图片附件渲染成缩略图（media_refs 不再是零消费）', () => {
		const ref = `xeyo-media://${'b'.repeat(64)}`;
		chatState.inboxBySession = {
			sess_1: [queueItem({queue_id: 'q1', text: '带图排队', media_refs: [ref]})],
		};
		render(<Composer />);
		const img = screen.getByAltText('排队消息图片');
		expect(img.getAttribute('src')).toContain('/media/');
	});

	it('stop control calls stopGeneration', async () => {
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
		});
		const user = userEvent.setup();
		render(<Composer />);
		await user.click(screen.getByTitle('停止生成'));
		expect(stopGeneration).toHaveBeenCalled();
	});

	it('Escape stops generation while streaming', async () => {
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
		});
		const user = userEvent.setup();
		render(<Composer />);
		await user.keyboard('{Escape}');
		expect(stopGeneration).toHaveBeenCalled();
	});

	it('keeps independent drafts when switching sessions', async () => {
		const user = userEvent.setup();
		const {rerender} = render(<Composer />);
		const ta = screen.getByLabelText('消息输入');

		await user.type(ta, '你好');
		expect(ta).toHaveValue('你好');

		chatState.activeId = 'sess_2';
		rerender(<Composer />);
		await waitFor(() =>
			expect(screen.getByLabelText('消息输入')).toHaveValue(''),
		);

		await user.type(screen.getByLabelText('消息输入'), '你是谁');
		expect(screen.getByLabelText('消息输入')).toHaveValue('你是谁');

		chatState.activeId = 'sess_1';
		rerender(<Composer />);
		await waitFor(() =>
			expect(screen.getByLabelText('消息输入')).toHaveValue('你好'),
		);

		chatState.activeId = 'sess_2';
		rerender(<Composer />);
		await waitFor(() =>
			expect(screen.getByLabelText('消息输入')).toHaveValue('你是谁'),
		);
	});

	it('clears draft for session after successful send', async () => {
		const user = userEvent.setup();
		const {rerender} = render(<Composer />);
		const ta = screen.getByLabelText('消息输入');
		await user.type(ta, '发送后清空');
		await user.keyboard('{Enter}');
		await waitFor(() => expect(ta).toHaveValue(''));

		chatState.activeId = 'sess_2';
		rerender(<Composer />);
		chatState.activeId = 'sess_1';
		rerender(<Composer />);
			await waitFor(() =>
				expect(screen.getByLabelText('消息输入')).toHaveValue(''),
			);
		});

		it('opens the quick menu without changing the existing file picker flow', async () => {
			const user = userEvent.setup();
			const {container} = render(<Composer />);
			const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
			const fileClick = vi.spyOn(fileInput, 'click');

			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			expect(screen.getByRole('menu')).toBeInTheDocument();
			expect(screen.getByRole('menuitemradio', {name: /Plan/})).toBeInTheDocument();
			expect(screen.getByRole('menuitemradio', {name: /Ask/})).toBeInTheDocument();
			expect(screen.getByRole('menuitem', {name: 'Files'})).toBeInTheDocument();

			await user.click(screen.getByRole('menuitemradio', {name: /Plan/}));
			expect(screen.queryByRole('menu')).not.toBeInTheDocument();
			expect(sendMessage).not.toHaveBeenCalled();

			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			await user.click(screen.getByRole('menuitemradio', {name: /Ask/}));
			expect(screen.queryByRole('menu')).not.toBeInTheDocument();
			expect(sendMessage).not.toHaveBeenCalled();

			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			await user.click(screen.getByRole('menuitem', {name: 'Files'}));
			expect(fileClick).toHaveBeenCalledOnce();
			expect(screen.queryByRole('menu')).not.toBeInTheDocument();
		});

		it('closes the quick menu with Escape or an outside click', async () => {
			const user = userEvent.setup();
			render(
				<>
					<Composer />
					<button type="button">外部按钮</button>
				</>,
			);

			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			expect(screen.getByRole('menu')).toBeInTheDocument();
			await user.keyboard('{Escape}');
			expect(screen.queryByRole('menu')).not.toBeInTheDocument();

			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			await user.click(screen.getByRole('button', {name: '外部按钮'}));
			expect(screen.queryByRole('menu')).not.toBeInTheDocument();
		});
	});

	describe('Composer Multi-Agent toggle', () => {
		beforeEach(() => {
			vi.clearAllMocks();
			resetComposerDraftsForTests();
			chatState.activeId = 'sess_1';
			sendMessage.mockResolvedValue(true);
		});

		it('passes multiAgent=false by default', async () => {
			const user = userEvent.setup();
			render(<Composer />);
			const ta = screen.getByLabelText('消息输入');
			await user.type(ta, '普通消息');
			await user.keyboard('{Enter}');
			await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
			expect(sendMessage).toHaveBeenCalledWith(
'普通消息',
				[],
				[],
				'agent',
				expect.any(Function),
				false,
				// Composer 始终传会话级思考等级 opts（空 = 自动/模型默认）。
				{reasoningEffort: '', steerIfBusy: false, sessionId: 'sess_1', background: false},
			);
		});

		it('toggles from + menu, shows chip, and passes multiAgent=true', async () => {
			const user = userEvent.setup();
			render(<Composer />);

			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			const item = screen.getByRole('menuitemradio', {name: /Multi-Agent/});
			expect(item).toHaveAttribute('aria-checked', 'false');
			await user.click(item);
			expect(screen.queryByRole('menu')).not.toBeInTheDocument();

			// chip 出现且可退出
			const chipExit = screen.getByLabelText('退出 Multi-Agent');
			expect(chipExit).toBeInTheDocument();

			const ta = screen.getByLabelText('消息输入');
			await user.type(ta, '并行任务');
			await user.keyboard('{Enter}');
			await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
			expect(sendMessage).toHaveBeenCalledWith(
'并行任务',
				[],
				[],
				'agent',
				expect.any(Function),
				true,
				// Composer 始终传会话级思考等级 opts（空 = 自动/模型默认）。
				{reasoningEffort: '', steerIfBusy: false, sessionId: 'sess_1', background: false},
			);
		});

		it('chip exit resets the flag before sending', async () => {
			const user = userEvent.setup();
			render(<Composer />);
			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			await user.click(screen.getByRole('menuitemradio', {name: /Multi-Agent/}));
			await user.click(screen.getByLabelText('退出 Multi-Agent'));
			expect(screen.queryByLabelText('退出 Multi-Agent')).not.toBeInTheDocument();

			const ta = screen.getByLabelText('消息输入');
			await user.type(ta, '又变回单agent');
			await user.keyboard('{Enter}');
			await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
			expect(sendMessage).toHaveBeenCalledWith(
'又变回单agent',
				[],
				[],
				'agent',
				expect.any(Function),
				false,
				// Composer 始终传会话级思考等级 opts（空 = 自动/模型默认）。
				{reasoningEffort: '', steerIfBusy: false, sessionId: 'sess_1', background: false},
			);
		});
	});

	describe('Composer mounts SessionGoalDock when the session has an active goal', () => {
		beforeEach(() => {
			vi.clearAllMocks();
			resetComposerDraftsForTests();
			chatState.activeId = 'sess_1';
			chatState.sessionStreams = {};
			chatState.sessionGoalById = {
				sess_1: {
					goal: {
						goal_id: 'g1',
						title: '测试目标',
						text: '测试目标',
						status: 'active',
						max_rounds: 32,
						rounds: 1,
						revision: 1,
						blocked_reason: '',
						pending_complete: false,
					},
					driver: {
						activation: 'disarmed',
						pending: false,
						active_round: null,
					},
				},
			};
		});

		afterEach(() => {
			chatState.sessionGoalById = {};
			cleanup();
		});

		it('renders 进行中的目标 + DSH 动作集（暂停/编辑/清除），不再有自动续跑入口', () => {
			render(<Composer />);
			expect(screen.getByText('进行中的目标')).toBeInTheDocument();
			expect(screen.getByRole('button', {name: '暂停'})).toBeInTheDocument();
			expect(screen.getByRole('button', {name: '编辑目标'})).toBeInTheDocument();
			expect(screen.getByRole('button', {name: '清除目标'})).toBeInTheDocument();
			expect(
				screen.queryByRole('button', {name: /自动续跑/}),
			).not.toBeInTheDocument();
		});

		it('does not render the dock when the session has no goal', () => {
			chatState.sessionGoalById = {};
			render(<Composer />);
			expect(screen.queryByText('进行中的目标')).not.toBeInTheDocument();
		});
	});

describe('Composer 自绘光标渲染所有权（IME 时序）', () => {
	it('compositionend 后不立刻交还渲染权，直到提交文本落进 value', () => {
		const {container} = render(<Composer />);
		const ta = screen.getByLabelText('消息输入') as HTMLTextAreaElement;
		const overlay = () => container.querySelector('.xy-gcaret');

		/* 平时：textarea 文字隐藏，由镜像覆盖层渲染 */
		expect(ta.className).toContain('text-transparent');
		expect(overlay()).not.toBeNull();

		fireEvent.compositionStart(ta);
		expect(ta.className).not.toContain('text-transparent');
		expect(overlay()).toBeNull();

		/* 组词期候选更新也走 change：不触发交还 */
		fireEvent.change(ta, {target: {value: '你好'}});
		expect(ta.className).not.toContain('text-transparent');

		/* 旧实现在这一步就把 textarea 设成透明（镜像却还画着旧文本）——那一帧就是闪 */
		fireEvent.compositionEnd(ta);
		expect(ta.className).not.toContain('text-transparent');
		expect(overlay()).toBeNull();

		/* 新文本与渲染者切换落在同一帧 */
		fireEvent.change(ta, {target: {value: '你好世界'}});
		expect(ta.className).toContain('text-transparent');
		expect(overlay()).not.toBeNull();
	});

	it('失焦收口：取消组词（不发 change）后自绘光标回到覆盖层', () => {
		const {container} = render(<Composer />);
		const ta = screen.getByLabelText('消息输入') as HTMLTextAreaElement;
		fireEvent.compositionStart(ta);
		fireEvent.compositionEnd(ta);
		fireEvent.blur(ta);
		expect(ta.className).toContain('text-transparent');
		expect(container.querySelector('.xy-gcaret')).not.toBeNull();
	});
});
