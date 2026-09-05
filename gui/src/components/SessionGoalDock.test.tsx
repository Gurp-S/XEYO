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
		interruptChat: vi.fn().mockResolvedValue(undefined),
	};
});

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
			? {goal: fixture.goal, driver: fixture.driver}
			: {goal: null, driver: null},
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
