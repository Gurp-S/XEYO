/**
 * SessionGoalDock.test.tsx — 41 号 P0 GUI 单测（单行 GoalBar 外观）。
 *
 * 覆盖：
 * - 渲染矩阵：无 goal / completed / abandoned 不渲染；
 *   active / paused / blocked / 候选各自的标签与动词。
 * - 动词：自动续跑→arm；暂停→pause(+disarm)；恢复(paused)→resume(+arm)；
 *   停止(轮中)→interrupt+disarm；标记完成→confirm_complete；恢复(blocked)→reopen。
 * - 编辑（行内 input）→edit；清除（确认）→drop；取消不触发。
 * - CAS 纪律（409 → 刷新重试一次）；goalDockLiveFor 谓词。
 * - 动词失败：失败必须报出后端原话；暂停/恢复没落地就不动自动续跑；
 *   编辑没落地就不关编辑器；interrupt 的 not_running 不算失败。
 */
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {useChatStore} from '@/stores/chatStore';
import {SessionGoalDock, goalDockLiveFor} from './SessionGoalDock';
import type {SessionGoalState} from '@/lib/api/goals';

const roundDriverAction = vi.fn();
const patchGoalAction = vi.fn();
const fetchGoalMock = vi.fn();

vi.mock('@/lib/api/goals', async importOriginal => {
	const actual =
		await importOriginal<typeof import('@/lib/api/goals')>();
	return {
		...actual,
		fetchGoal: (...args: unknown[]) => fetchGoalMock(...args),
		patchGoalAction: (...args: unknown[]) => patchGoalAction(...args),
		roundDriverAction: (...args: unknown[]) => roundDriverAction(...args),
	};
});

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		interruptChat: vi.fn().mockResolvedValue({ok: true, message: ''}),
	};
});

const toastError = vi.fn();

vi.mock('@/lib/toast', () => ({
	toast: {
		error: (...args: unknown[]) => toastError(...args),
		success: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		dismiss: vi.fn(),
	},
}));

function makeGoal(
	over: Partial<SessionGoalState['goal']> = {},
): SessionGoalState {
	return {
		goal: {
			goal_id: 'g1',
			title: '重构登录模块',
			text: '重构登录模块',
			status: 'active',
			pending_complete: false,
			rounds: 1,
			max_rounds: 0,
			blocked_reason: '',
			revision: 3,
			...over,
		},
		driver: {activation: 'disarmed', pending: false, active_round: null},
	};
}

let fixture: SessionGoalState | null = null;

function seed(next: SessionGoalState | null) {
	fixture = next;
	useChatStore.setState(s => ({
		activeId: 's1',
		sessionGoalById: {...s.sessionGoalById, s1: next},
	}));
}

beforeEach(() => {
	fetchGoalMock.mockImplementation(async () =>
		fixture
			? {ok: true, goal: fixture.goal, driver: fixture.driver, message: ''}
			: {ok: true, goal: null, driver: null, message: ''},
	);
	roundDriverAction.mockReset();
	patchGoalAction.mockReset();
	seed(null);
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe('SessionGoalDock 渲染矩阵', () => {
	it('无 goal 不渲染', () => {
		const {container} = render(<SessionGoalDock embedded />);
		expect(container).toBeEmptyDOMElement();
	});

	it('completed / abandoned 不渲染', () => {
		seed(makeGoal({status: 'completed'}));
		const {container, unmount} = render(<SessionGoalDock embedded />);
		expect(container).toBeEmptyDOMElement();
		unmount();
		seed(makeGoal({status: 'abandoned'}));
		const res = render(<SessionGoalDock embedded />);
		expect(res.container).toBeEmptyDOMElement();
	});

	it('active+disarmed：进行中的目标 + 自动续跑 → arm', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
		const armed = makeGoal();
		armed.driver = {activation: 'armed', pending: false, active_round: null};
		roundDriverAction.mockResolvedValue({
			ok: true,
			goal: armed.goal,
			driver: armed.driver,
		});
		await user.click(screen.getByRole('button', {name: /自动续跑/}));
		expect(roundDriverAction).toHaveBeenCalledWith('s1', 'arm');
		await waitFor(() => {
			expect(
				useChatStore.getState().sessionGoalById?.s1?.driver?.activation,
			).toBe('armed');
		});
	});

	it('active+armed 空闲：进行中的目标 + 暂停 → PATCH pause', async () => {
		const user = userEvent.setup();
		seed({
			goal: makeGoal().goal,
			driver: {activation: 'armed', pending: false, active_round: null},
		});
		const pausedGoal = makeGoal({status: 'paused'});
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: pausedGoal.goal,
			driver: null,
		});
		roundDriverAction.mockResolvedValue({
			ok: true,
			goal: pausedGoal.goal,
			driver: {activation: 'disarmed', pending: false, active_round: null},
		});
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: /暂停/}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'pause', {
			revision: 3,
		});
	});

	it('active+armed+轮中：进行中的目标 + 停止 → interrupt + disarm', async () => {
		const user = userEvent.setup();
		seed({
			goal: makeGoal().goal,
			driver: {activation: 'armed', pending: false, active_round: ['g1', 2]},
		});
		const {interruptChat} = await import('@/lib/api');
		roundDriverAction.mockResolvedValue({
			ok: true,
			goal: makeGoal().goal,
			driver: {activation: 'disarmed', pending: false, active_round: null},
		});
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: /停止/}));
		await waitFor(() => {
			expect(interruptChat).toHaveBeenCalledWith('s1');
		});
		expect(roundDriverAction).toHaveBeenCalledWith('s1', 'disarm');
	});

	it('paused：已暂停的目标 + 恢复 → PATCH resume + arm', async () => {
		const user = userEvent.setup();
		seed(makeGoal({status: 'paused'}));
		const resumed = makeGoal();
		resumed.driver = {activation: 'armed', pending: false, active_round: null};
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: resumed.goal,
			driver: null,
		});
		roundDriverAction.mockResolvedValue({
			ok: true,
			goal: resumed.goal,
			driver: resumed.driver,
		});
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('已暂停的目标')).toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: /恢复/}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'resume', {
			revision: 3,
		});
		expect(roundDriverAction).toHaveBeenCalledWith('s1', 'arm');
	});

	it('候选：待确认完成 + 标记完成 → PATCH confirm_complete', async () => {
		const user = userEvent.setup();
		seed(makeGoal({pending_complete: true}));
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: makeGoal({status: 'completed'}).goal,
			driver: null,
		});
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('待确认完成')).toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: '标记完成'}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'confirm_complete', {
			revision: 3,
		});
	});

	it('blocked：受阻的目标 + 恢复 → PATCH reopen', async () => {
		const user = userEvent.setup();
		seed(makeGoal({status: 'blocked', blocked_reason: 'provider_error'}));
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: makeGoal().goal,
			driver: null,
		});
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('受阻的目标')).toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: '恢复'}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'reopen', {
			revision: 3,
		});
	});
});

describe('SessionGoalDock 编辑 / 清除', () => {
	it('编辑 → 行内 input → 保存 → PATCH edit（text + maxRounds）', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		const saved = makeGoal({text: '新目标', max_rounds: 8});
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: saved.goal,
			driver: null,
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		const textInput = await screen.findByPlaceholderText('目标内容');
		await user.clear(textInput);
		await user.type(textInput, '新目标');
		const cap = screen.getByPlaceholderText('轮次上限(0=默认)');
		await user.clear(cap);
		await user.type(cap, '8');
		await user.click(screen.getByRole('button', {name: '保存'}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'edit', {
			revision: 3,
			text: '新目标',
			maxRounds: 8,
		});
	});

	it('清除 → 确认 → PATCH drop，dock 随 abandoned 隐藏', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: makeGoal({status: 'abandoned'}).goal,
			driver: null,
		});
		const {container} = render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '清除目标'}));
		expect(
			await screen.findByRole('button', {name: '确认删除'}),
		).toBeInTheDocument();
		await user.click(screen.getByRole('button', {name: '确认删除'}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'drop', {revision: 3});
		await waitFor(() => {
			expect(container).toBeEmptyDOMElement();
		});
	});

	it('清除确认前点取消不触发 drop', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '清除目标'}));
		await user.click(screen.getByRole('button', {name: '取消'}));
		expect(
			screen.queryByRole('button', {name: '确认删除'}),
		).not.toBeInTheDocument();
		expect(patchGoalAction).not.toHaveBeenCalled();
	});
});

describe('SessionGoalDock CAS 纪律', () => {
	it('409 conflict：刷新 store 后带新 revision 重试一次', async () => {
		const user = userEvent.setup();
		seed(makeGoal({pending_complete: true}));
		const conflicted = makeGoal({pending_complete: true, revision: 9});
		const settled = makeGoal({status: 'completed', revision: 10});
		patchGoalAction
			.mockResolvedValueOnce({
				ok: false,
				conflict: conflicted.goal,
				message: 'goal_revision_conflict',
			})
			.mockResolvedValueOnce({ok: true, goal: settled.goal, driver: null});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '标记完成'}));
		await waitFor(() => {
			expect(patchGoalAction).toHaveBeenCalledTimes(2);
		});
		expect(patchGoalAction).toHaveBeenNthCalledWith(
			1,
			's1',
			'confirm_complete',
			{revision: 3},
		);
		expect(patchGoalAction).toHaveBeenNthCalledWith(
			2,
			's1',
			'confirm_complete',
			{revision: 9},
		);
	});
});

describe('动词失败的三种说法（写请求发了不等于改成了）', () => {
	it('暂停失败 → 报出后端原话，目标仍是进行中，且不停自动续跑', async () => {
		const user = userEvent.setup();
		seed({
			goal: makeGoal().goal,
			driver: {activation: 'armed', pending: false, active_round: null},
		});
		patchGoalAction.mockResolvedValue({
			ok: false,
			conflict: null,
			message: 'goal_action_not_allowed',
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: /暂停/}));
		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(toastError.mock.calls[0][0]).toContain('目标操作未生效');
		expect(toastError.mock.calls[0][0]).toContain('goal_action_not_allowed');
		expect(roundDriverAction).not.toHaveBeenCalled();
		expect(useChatStore.getState().sessionGoalById?.s1?.goal.status).toBe(
			'active',
		);
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
	});

	it('恢复失败 → 不 arm（不能让自动续跑接着暂停的目标跑轮）', async () => {
		const user = userEvent.setup();
		seed(makeGoal({status: 'paused'}));
		patchGoalAction.mockResolvedValue({
			ok: false,
			conflict: null,
			message: 'session_not_found',
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: /恢复/}));
		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(toastError.mock.calls[0][0]).toContain('session_not_found');
		expect(roundDriverAction).not.toHaveBeenCalled();
		expect(useChatStore.getState().sessionGoalById?.s1?.goal.status).toBe(
			'paused',
		);
	});

	it('编辑失败 → 编辑器不关，刚输入的标题不跟着消失', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		patchGoalAction.mockResolvedValue({
			ok: false,
			conflict: null,
			message: 'goal_text_too_long',
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		const textInput = await screen.findByPlaceholderText('目标内容');
		await user.clear(textInput);
		await user.type(textInput, '改成这个标题');
		await user.click(screen.getByRole('button', {name: '保存'}));
		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(toastError.mock.calls[0][0]).toContain('goal_text_too_long');
		expect(screen.getByRole('button', {name: '保存'})).toBeInTheDocument();
		expect(screen.getByPlaceholderText('目标内容')).toHaveValue(
			'改成这个标题',
		);
	});

	it('停止：interrupt 与 disarm 各自失败就各说一句', async () => {
		const user = userEvent.setup();
		const {interruptChat} = await import('@/lib/api');
		vi.mocked(interruptChat).mockResolvedValueOnce({
			ok: false,
			message: 'HTTP 500',
		});
		seed({
			goal: makeGoal().goal,
			driver: {activation: 'armed', pending: false, active_round: ['g1', 2]},
		});
		roundDriverAction.mockResolvedValue({
			ok: false,
			conflict: null,
			message: 'driver_unavailable',
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: /停止/}));
		await waitFor(() => expect(toastError).toHaveBeenCalledTimes(2));
		const said = toastError.mock.calls.map(c => String(c[0])).join('\n');
		expect(said).toContain('停止本轮未生效：HTTP 500');
		expect(said).toContain('停止自动续跑未生效：driver_unavailable');
	});

	it('interrupt 回 not_running 不算失败（这一轮本来就没在跑）', async () => {
		const user = userEvent.setup();
		const {interruptChat} = await import('@/lib/api');
		vi.mocked(interruptChat).mockResolvedValueOnce({
			ok: false,
			message: 'not_running',
		});
		seed({
			goal: makeGoal().goal,
			driver: {activation: 'armed', pending: false, active_round: ['g1', 2]},
		});
		roundDriverAction.mockResolvedValue({
			ok: true,
			goal: makeGoal().goal,
			driver: {activation: 'disarmed', pending: false, active_round: null},
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: /停止/}));
		await waitFor(() => expect(interruptChat).toHaveBeenCalledWith('s1'));
		expect(toastError).not.toHaveBeenCalled();
	});
});

describe('goalDockLiveFor', () => {
	it('active / paused / blocked → live；completed / abandoned / 无 goal → 不 live', () => {
		expect(goalDockLiveFor(null)).toBe(false);
		expect(goalDockLiveFor(makeGoal())).toBe(true);
		expect(goalDockLiveFor(makeGoal({status: 'paused'}))).toBe(true);
		expect(goalDockLiveFor(makeGoal({status: 'blocked'}))).toBe(true);
		expect(goalDockLiveFor(makeGoal({status: 'completed'}))).toBe(false);
		expect(goalDockLiveFor(makeGoal({status: 'abandoned'}))).toBe(false);
	});
});

/**
 * 挂载即拉一次投影（useSessionGoalLive）。要害是"读不出"与"确实没有"必须分家：
 * 轮询撞上后端抖动时把 store 写成 null，dock 就按"没有目标"自己消失了。
 */
describe('投影轮询的三种读数', () => {
	it('读到目标 → 落进 store 并渲染出来', async () => {
		const seeded = makeGoal();
		fetchGoalMock.mockResolvedValue({
			ok: true,
			goal: seeded.goal,
			driver: seeded.driver,
			message: '',
		});
		seed(null);

		render(<SessionGoalDock embedded />);

		await waitFor(() =>
			expect(useChatStore.getState().sessionGoalById.s1).not.toBeNull(),
		);
		expect(screen.getByText(/重构登录模块/)).toBeTruthy();
	});

	it('读不出（403/5xx/离线）→ 保留已有目标，不清空、不消失', async () => {
		fetchGoalMock.mockResolvedValue({
			ok: false,
			goal: null,
			driver: null,
			message: 'HTTP 503',
		});
		seed(makeGoal());

		const {container} = render(<SessionGoalDock embedded />);
		await new Promise(r => setTimeout(r, 0));

		expect(useChatStore.getState().sessionGoalById.s1).not.toBeNull();
		expect(container).not.toBeEmptyDOMElement();
	});

	it('确认没有目标（ok 且 goal 为空）→ 才允许清空', async () => {
		fetchGoalMock.mockResolvedValue({
			ok: true,
			goal: null,
			driver: null,
			message: '',
		});
		seed(makeGoal());

		render(<SessionGoalDock embedded />);

		await waitFor(() =>
			expect(useChatStore.getState().sessionGoalById.s1).toBeNull(),
		);
	});
});
