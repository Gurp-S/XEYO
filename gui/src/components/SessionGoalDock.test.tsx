/**
 * SessionGoalDock.test.tsx — goal 条带契约（2026-10-03 深夜起按 DSH GoalBar 字面对齐）。
 *
 * 钉住"条带上有什么、没什么"：
 * - 相位 → 动作：active→暂停、paused→恢复、blocked→**只有**编辑/清除（DSH 不给 blocked 恢复）；
 * - 条带上不出现：自动续跑开关与状态圆点、待确认完成的标记完成/继续、轮次上限输入、
 *   停止本轮、受阻重开、清除的二次确认（业主裁定"样式、交互等所有对齐 DSH"）。
 * 自动续跑这组功能已废弃（业主 10-03 裁定）：动词只发 phase PATCH；夹具连
 * `roundDriverAction` 都不提供，产品代码若再调用它就直接抛 = 不是恒真断言。
 * 另外钉：CAS 409 刷新重试一次、失败内联在条带里、编辑没落地不关编辑器、
 * 目标换身份时丢弃本地草稿、归档只读、轮询"读不出≠没有"。
 */
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {useChatStore} from '@/stores/chatStore';
import {SessionGoalDock, goalDockLiveFor} from './SessionGoalDock';
import type {SessionGoalState} from '@/lib/api/goals';

const patchGoalAction = vi.fn();
const fetchGoalMock = vi.fn();

// 故意不提供 roundDriverAction：自动续跑这组功能已废弃（业主 10-03 裁定），
// 产品代码若再去 import 它，调用即抛——比"断言它没被调用"的恒真判据有牙。
vi.mock('@/lib/api/goals', async importOriginal => {
	const actual =
		await importOriginal<typeof import('@/lib/api/goals')>();
	return {
		...actual,
		roundDriverAction: undefined,
		fetchGoal: (...args: unknown[]) => fetchGoalMock(...args),
		patchGoalAction: (...args: unknown[]) => patchGoalAction(...args),
	};
});

vi.mock('@/lib/toast', () => ({
	toast: {
		error: vi.fn(),
		success: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		dismiss: vi.fn(),
	},
}));

/** 动词失败内联在条带里（role=alert）；这里是读它当前说了什么。 */
function goalAlert(): string {
	return screen.getAllByRole('alert').map(el => el.textContent ?? '').join('\n');
}

/** 条带上当前的动作（DSH：active/paused 三个，blocked 两个）。 */
function goalButtonLabels(): Array<string | null> {
	return screen.getAllByRole('button').map(b => b.getAttribute('aria-label'));
}

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
	patchGoalAction.mockReset();
	seed(null);
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe('渲染矩阵', () => {
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
});

describe('条带上有什么、没什么（DSH GoalBar 的字面动作集）', () => {
	it('active：进行中的目标 + 恰好 暂停/编辑目标/清除目标 三个动作', () => {
		seed(makeGoal());
		const {container} = render(<SessionGoalDock embedded />);
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
		expect(goalButtonLabels()).toEqual(['暂停', '编辑目标', '清除目标']);
		// 撤掉的能力不许留痕迹：待确认完成文案、armed 状态圆点。
		expect(screen.queryByText('待确认完成')).not.toBeInTheDocument();
		expect(container.querySelector('.animate-pulse')).toBeNull();
	});

	it('active + pending_complete：与 active 同形，没有「标记完成」入口', () => {
		seed(makeGoal({pending_complete: true}));
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
		expect(
			screen.queryByRole('button', {name: '标记完成'}),
		).not.toBeInTheDocument();
		expect(
			screen.queryByRole('button', {name: '继续此目标'}),
		).not.toBeInTheDocument();
	});

	it('paused：已暂停的目标 + 恢复/编辑/清除', () => {
		seed(makeGoal({status: 'paused'}));
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('已暂停的目标')).toBeInTheDocument();
		expect(goalButtonLabels()).toEqual(['恢复', '编辑目标', '清除目标']);
	});

	it('blocked：受阻的目标 + 只有编辑/清除', () => {
		seed(makeGoal({status: 'blocked', blocked_reason: 'provider_error'}));
		render(<SessionGoalDock embedded />);
		expect(screen.getByText('受阻的目标')).toBeInTheDocument();
		expect(goalButtonLabels()).toEqual(['编辑目标', '清除目标']);
		expect(screen.queryByRole('button', {name: '恢复'})).not.toBeInTheDocument();
	});

	it('编辑态只有一个输入框：轮次上限不再出现在条带上', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		expect(screen.getByPlaceholderText('目标内容')).toBeInTheDocument();
		expect(
			screen.queryByPlaceholderText('轮次上限(0=默认)'),
		).not.toBeInTheDocument();
	});
});

describe('动词只发 phase PATCH（round-driver 已废弃）', () => {
	it('暂停 → 只发 PATCH pause', async () => {
		const user = userEvent.setup();
		seed({
			goal: makeGoal().goal,
			driver: {activation: 'armed', pending: false, active_round: null},
		});
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: makeGoal({status: 'paused'}).goal,
			driver: null,
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '暂停'}));
		await waitFor(() => {
			expect(patchGoalAction).toHaveBeenCalledWith('s1', 'pause', {revision: 3});
		});
	});

	it('恢复 → 只发 PATCH resume', async () => {
		const user = userEvent.setup();
		seed(makeGoal({status: 'paused'}));
		patchGoalAction.mockResolvedValue({ok: true, goal: makeGoal().goal, driver: null});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '恢复'}));
		await waitFor(() => {
			expect(patchGoalAction).toHaveBeenCalledWith('s1', 'resume', {revision: 3});
		});
	});

	it('动词回执按 whole-value 覆写：条带当场换成新相位，不靠本地猜', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: makeGoal({status: 'paused', revision: 4}).goal,
			driver: null,
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '暂停'}));
		await waitFor(() => expect(screen.getByText('已暂停的目标')).toBeInTheDocument());
		expect(screen.getByRole('button', {name: '恢复'})).toBeInTheDocument();
	});

	it('暂停失败 → 条带内报出后端原话，相位原地不动', async () => {
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
		await user.click(screen.getByRole('button', {name: '暂停'}));
		await waitFor(() => expect(goalAlert()).toContain('目标操作未生效'));
		expect(goalAlert()).toContain('goal_action_not_allowed');
		expect(useChatStore.getState().sessionGoalById?.s1?.goal.status).toBe('active');
		expect(screen.getByText('进行中的目标')).toBeInTheDocument();
	});

	it('恢复失败 → 条带内报出原话，目标仍是已暂停', async () => {
		const user = userEvent.setup();
		seed(makeGoal({status: 'paused'}));
		patchGoalAction.mockResolvedValue({
			ok: false,
			conflict: null,
			message: 'session_not_found',
		});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '恢复'}));
		await waitFor(() => expect(goalAlert()).toContain('session_not_found'));
		expect(useChatStore.getState().sessionGoalById?.s1?.goal.status).toBe('paused');
	});
});

describe('编辑 / 清除', () => {
	it('编辑 → 行内 input → 保存 → PATCH edit 只带 text', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		const saved = makeGoal({text: '新目标'});
		patchGoalAction.mockResolvedValue({ok: true, goal: saved.goal, driver: null});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		const textInput = await screen.findByPlaceholderText('目标内容');
		await user.clear(textInput);
		await user.type(textInput, '新目标');
		await user.click(screen.getByRole('button', {name: '保存目标'}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'edit', {
			revision: 3,
			text: '新目标',
		});
	});

	it('草稿为空时保存键禁用（空目标不许提交）', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		await user.clear(screen.getByPlaceholderText('目标内容'));
		expect(screen.getByRole('button', {name: '保存目标'})).toBeDisabled();
		expect(patchGoalAction).not.toHaveBeenCalled();
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
		await user.click(screen.getByRole('button', {name: '保存目标'}));
		await waitFor(() => expect(goalAlert()).toContain('goal_text_too_long'));
		expect(screen.getByRole('button', {name: '保存目标'})).toBeInTheDocument();
		expect(screen.getByPlaceholderText('目标内容')).toHaveValue('改成这个标题');
	});

	it('清除 → 一次点击即 drop（DSH 无二次确认），条带随即收起', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		patchGoalAction.mockResolvedValue({
			ok: true,
			goal: makeGoal({status: 'abandoned'}).goal,
			driver: null,
		});
		const {container} = render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '清除目标'}));
		expect(patchGoalAction).toHaveBeenCalledWith('s1', 'drop', {revision: 3});
		expect(
			screen.queryByRole('button', {name: '确认删除'}),
		).not.toBeInTheDocument();
		await waitFor(() => {
			expect(container).toBeEmptyDOMElement();
		});
	});

	it('清除失败 → 条带留在原地说清楚为什么没删掉', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		const {container} = render(<SessionGoalDock embedded />);
		patchGoalAction.mockResolvedValue({
			ok: false,
			conflict: null,
			message: 'goal_action_not_allowed',
		});
		await user.click(screen.getByRole('button', {name: '清除目标'}));
		await waitFor(() => expect(goalAlert()).toContain('goal_action_not_allowed'));
		expect(container).not.toBeEmptyDOMElement();
	});
});

describe('CAS 与投影滞后', () => {
	it('409 conflict：刷新 store 后带新 revision 重试一次', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		const conflicted = makeGoal({revision: 9});
		const settled = makeGoal({text: '新目标', revision: 10});
		patchGoalAction
			.mockResolvedValueOnce({
				ok: false,
				conflict: conflicted.goal,
				message: 'goal_revision_conflict',
			})
			.mockResolvedValueOnce({ok: true, goal: settled.goal, driver: null});
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		const textInput = await screen.findByPlaceholderText('目标内容');
		await user.clear(textInput);
		await user.type(textInput, '新目标');
		await user.click(screen.getByRole('button', {name: '保存目标'}));
		await waitFor(() => {
			expect(patchGoalAction).toHaveBeenCalledTimes(2);
		});
		expect(patchGoalAction).toHaveBeenNthCalledWith(1, 's1', 'edit', {
			revision: 3,
			text: '新目标',
		});
		expect(patchGoalAction).toHaveBeenNthCalledWith(2, 's1', 'edit', {
			revision: 9,
			text: '新目标',
		});
	});

	it('目标换了身份（外部替换/清除）→ 未提交的草稿被丢弃，不许写到新目标上', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		render(<SessionGoalDock embedded />);
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		const textInput = await screen.findByPlaceholderText('目标内容');
		await user.type(textInput, '还没保存的字');
		seed(makeGoal({goal_id: 'g2', text: '别的目标', revision: 7}));
		await waitFor(() => {
			expect(screen.queryByPlaceholderText('目标内容')).not.toBeInTheDocument();
		});
		expect(screen.getByText('别的目标')).toBeInTheDocument();
	});

	it('归档会话：动作全部禁用，写请求一个都不发', async () => {
		const user = userEvent.setup();
		seed(makeGoal());
		useChatStore.setState(s => ({
			sessions: [...s.sessions, {id: 's1', archived: true} as never],
		}));
		render(<SessionGoalDock embedded />);
		const btns = screen.getAllByRole('button');
		expect(btns.length).toBeGreaterThan(0);
		for (const b of btns) {
			expect(b).toBeDisabled();
		}
		await user.click(screen.getByRole('button', {name: '编辑目标'}));
		expect(patchGoalAction).not.toHaveBeenCalled();
		expect(screen.queryByPlaceholderText('目标内容')).not.toBeInTheDocument();
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
