import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {resetComposerDraftsForTests} from '@/lib/composerDrafts';
import {patchSessionStream} from '@/lib/sessionStreams';

const {chatState, sendMessage, stopGeneration} = vi.hoisted(() => {
	const sendMessage = vi.fn();
	const stopGeneration = vi.fn();
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
		// 工作区已加的 P1 mid-turn inbox：测试环境需提供这些字段（否则 inbvoxBySession undefined）。
		inboxBySession: {} as Record<
			string,
			{
				queueId: string;
				position: number;
				text: string;
			}[]
		>,
		hasInboxChip: false,
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
	return {chatState, sendMessage, stopGeneration};
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
	resumeInbox: vi.fn(async () => true),
	fetchSkills: vi.fn(async () => ({ok: true, skills: []})),
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

vi.mock('@/lib/slashCommands', () => ({
	handleComposerSlash,
	lastUserText: vi.fn(() => ''),
}));

import {Composer} from './Composer';

describe('Composer send UX', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		resetComposerDraftsForTests();
		chatState.activeId = 'sess_1';
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
		const ta = screen.getByPlaceholderText(/描述任务/);
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
			{reasoningEffort: ''},
		);
	});

	it('keeps draft when sendMessage returns false', async () => {
		const user = userEvent.setup();
		sendMessage.mockResolvedValue(false);
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, 'keep');
		await user.keyboard('{Enter}');
		await waitFor(() => expect(sendMessage).toHaveBeenCalled());
		expect(ta).toHaveValue('keep');
	});

	it('does not send empty / whitespace-only', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, '   ');
		await user.keyboard('{Enter}');
		expect(sendMessage).not.toHaveBeenCalled();
	});

	it('routes slash commands to handleComposerSlash, not sendMessage', async () => {
		handleComposerSlash.mockResolvedValue(true);
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, '/export a.md');
		await user.keyboard('{Enter}');
		await waitFor(() =>
			expect(handleComposerSlash).toHaveBeenCalledWith('/export a.md', expect.any(Object)),
		);
		expect(sendMessage).not.toHaveBeenCalled();
	});

	it('slash menu: ArrowDown + Enter picks the highlighted suggestion instead of sending', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, '/exp');
		// ↑ 高亮第一项 → Enter 选中该行（回填 usage），绝不透传成发送。
		fireEvent.keyDown(ta, {key: 'ArrowDown'});
		fireEvent.keyDown(ta, {key: 'Enter'});
		await waitFor(() => expect((ta as HTMLTextAreaElement).value.startsWith('/export ')).toBe(true));
		expect(sendMessage).not.toHaveBeenCalled();
		expect(handleComposerSlash).not.toHaveBeenCalled();
	});

	it('Enter without highlight in slash menu still sends (combobox pass-through)', async () => {
		handleComposerSlash.mockResolvedValue(true);
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, '/exp');
		// 无高亮直接 Enter → 仲裁 pass → 落到原发送链路。
		fireEvent.keyDown(ta, {key: 'Enter'});
		await waitFor(() =>
			expect(handleComposerSlash).toHaveBeenCalledWith('/exp', expect.any(Object)),
		);
	});

	it('IME composing Enter does not send', async () => {
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, '你好');
		fireEvent.keyDown(ta, {key: 'Enter', isComposing: true});
		expect(sendMessage).not.toHaveBeenCalled();
		expect(handleComposerSlash).not.toHaveBeenCalled();
	});

	it('keeps input available while streaming and shows stop control', async () => {
		chatState.sessionStreams = patchSessionStream({}, 'sess_1', {
			isLoading: true,
			statusText: 'thinking…',
		});
		const user = userEvent.setup();
		render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		expect(screen.getByLabelText('停止生成')).toBeInTheDocument();
		expect(screen.getByTitle('停止生成')).toBeInTheDocument();
		expect(ta).not.toBeDisabled();
		await user.type(ta, '继续输入');
		expect(ta).toHaveValue('继续输入');
		expect(sendMessage).not.toHaveBeenCalled();
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
		const ta = screen.getByPlaceholderText(/描述任务/);

		await user.type(ta, '你好');
		expect(ta).toHaveValue('你好');

		chatState.activeId = 'sess_2';
		rerender(<Composer />);
		await waitFor(() =>
			expect(screen.getByPlaceholderText(/描述任务/)).toHaveValue(''),
		);

		await user.type(screen.getByPlaceholderText(/描述任务/), '你是谁');
		expect(screen.getByPlaceholderText(/描述任务/)).toHaveValue('你是谁');

		chatState.activeId = 'sess_1';
		rerender(<Composer />);
		await waitFor(() =>
			expect(screen.getByPlaceholderText(/描述任务/)).toHaveValue('你好'),
		);

		chatState.activeId = 'sess_2';
		rerender(<Composer />);
		await waitFor(() =>
			expect(screen.getByPlaceholderText(/描述任务/)).toHaveValue('你是谁'),
		);
	});

	it('clears draft for session after successful send', async () => {
		const user = userEvent.setup();
		const {rerender} = render(<Composer />);
		const ta = screen.getByPlaceholderText(/描述任务/);
		await user.type(ta, '发送后清空');
		await user.keyboard('{Enter}');
		await waitFor(() => expect(ta).toHaveValue(''));

		chatState.activeId = 'sess_2';
		rerender(<Composer />);
		chatState.activeId = 'sess_1';
		rerender(<Composer />);
			await waitFor(() =>
				expect(screen.getByPlaceholderText(/描述任务/)).toHaveValue(''),
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
			const ta = screen.getByPlaceholderText(/描述任务/);
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
				{reasoningEffort: ''},
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

			const ta = screen.getByPlaceholderText(/描述任务/);
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
				{reasoningEffort: ''},
			);
		});

		it('chip exit resets the flag before sending', async () => {
			const user = userEvent.setup();
			render(<Composer />);
			await user.click(screen.getByRole('button', {name: '打开操作菜单'}));
			await user.click(screen.getByRole('menuitemradio', {name: /Multi-Agent/}));
			await user.click(screen.getByLabelText('退出 Multi-Agent'));
			expect(screen.queryByLabelText('退出 Multi-Agent')).not.toBeInTheDocument();

			const ta = screen.getByPlaceholderText(/描述任务/);
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
				{reasoningEffort: ''},
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

		it('renders 进行中的目标 + 自动续跑 for an active disarmed goal', () => {
			render(<Composer />);
			expect(screen.getByText('进行中的目标')).toBeInTheDocument();
			expect(
				screen.getByRole('button', {name: /自动续跑/}),
			).toBeInTheDocument();
		});

		it('does not render the dock when the session has no goal', () => {
			chatState.sessionGoalById = {};
			render(<Composer />);
			expect(screen.queryByText('进行中的目标')).not.toBeInTheDocument();
		});
	});
