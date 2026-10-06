/**
 * goalSync.test.ts — /goal 之后那次投影同步的读数。
 *
 * 斜杠命令的回执来自后端（"已创建"），而条带挂载全靠这里。投影读不到时原来
 * 只是 `continue` 后静默返回：用户看到"已创建"，界面上却没有目标——沉默等于
 * 一个没验证过的状态。
 *
 * 2026-10-03 业主裁定废弃"自动续跑"这组功能 ⇒ 本模块不再 arm。夹具**故意只
 * 导出 fetchGoal**：产品代码若再 import `roundDriverAction` 就会拿到 undefined，
 * 一调用即抛，这几条用例当场红——不是"断言它没被调用"那种恒真判据。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {GoalSnapshot} from '@/lib/api/goals';

const fetchGoalMock = vi.fn();
const writes: Array<Record<string, unknown>> = [];

vi.mock('@/lib/api/goals', () => ({
	fetchGoal: (...args: unknown[]) => fetchGoalMock(...args),
}));

vi.mock('@/stores/chatStore', () => ({
	useChatStore: {
		setState: (fn: (s: unknown) => Record<string, unknown>) => {
			writes.push(fn({sessionGoalById: {}}));
		},
	},
}));

/* eslint-disable import/first */
import {syncGoalAfterCommand, writeGoalState} from '@/lib/goalSync';

const goal: GoalSnapshot = {
	goal_id: 'g1',
	title: 'T',
	text: 'T',
	status: 'active',
	pending_complete: false,
	rounds: 0,
	max_rounds: 0,
	blocked_reason: '',
	revision: 1,
};
const READ_OK = {ok: true, goal, driver: null, message: ''};
const READ_EMPTY = {ok: true, goal: null, driver: null, message: ''};
const READ_FAIL = {ok: false, goal: null, driver: null, message: 'HTTP 503'};

beforeEach(() => {
	fetchGoalMock.mockReset();
	writes.length = 0;
});

describe('syncGoalAfterCommand', () => {
	it('投影读不到：不静默继续，note 带原因，也不写 store', async () => {
		fetchGoalMock.mockResolvedValue(READ_FAIL);

		const r = await syncGoalAfterCommand('gui-1');

		expect(r.ok).toBe(false);
		expect(r.note).toContain('HTTP 503');
		expect(writes).toHaveLength(0);
	});

	it('读到活跃目标：落一次 store 就完事（arm 已废弃，不再有第二次写）', async () => {
		fetchGoalMock.mockResolvedValue(READ_OK);

		const r = await syncGoalAfterCommand('gui-1');

		expect(r).toEqual({ok: true, note: ''});
		expect(writes).toHaveLength(1);
	});

	it('确认没有活跃目标与读不到是两种说法', async () => {
		fetchGoalMock.mockResolvedValue(READ_EMPTY);

		const r = await syncGoalAfterCommand('gui-1');

		expect(r.ok).toBe(false);
		expect(r.note).toContain('投影里没有活跃目标');
	});

	it('completed / abandoned 不是活跃目标：不落 store（条带不该挂出终态）', async () => {
		fetchGoalMock.mockResolvedValue({
			...READ_OK,
			goal: {...goal, status: 'abandoned'},
		});

		const r = await syncGoalAfterCommand('gui-1');

		expect(r.ok).toBe(false);
		expect(writes).toHaveLength(0);
	});

	it('goal 绑在后端会话 id 时：读用后端 id，store 写在 GUI id 上', async () => {
		fetchGoalMock.mockResolvedValue(READ_OK);

		await syncGoalAfterCommand('gui-1', 'backend-9');

		expect(fetchGoalMock).toHaveBeenNthCalledWith(1, 'backend-9');
		expect(
			(writes[0] as {sessionGoalById: Record<string, unknown>}).sessionGoalById['gui-1'],
		).toBeTruthy();
	});

	it('writeGoalState 仍按整值写入 store（SSE / GET / 命令三源同形）', () => {
		writeGoalState('s9', {goal, driver: null});

		expect(writes).toHaveLength(1);
		expect(
			(writes[0] as {sessionGoalById: Record<string, unknown>}).sessionGoalById.s9,
		).toBeTruthy();
	});
});
