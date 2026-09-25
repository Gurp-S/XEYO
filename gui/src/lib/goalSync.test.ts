/**
 * goalSync.test.ts — /goal 之后那次"投影 + arm"的读数。
 *
 * 斜杠命令的回执来自后端（"已创建"），而 dock 挂载与自动续跑全靠这里。
 * 投影读不到时原来只是 `continue` 后静默返回：用户看到"已创建"，
 * 界面上却没有目标、也不会自动续跑——沉默等于一个没验证过的状态。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {GoalSnapshot} from '@/lib/api/goals';

const fetchGoalMock = vi.fn();
const roundDriverMock = vi.fn();
const writes: Array<Record<string, unknown>> = [];

vi.mock('@/lib/api/goals', () => ({
	fetchGoal: (...args: unknown[]) => fetchGoalMock(...args),
	roundDriverAction: (...args: unknown[]) => roundDriverMock(...args),
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
	roundDriverMock.mockReset();
	writes.length = 0;
});

describe('syncGoalAfterCommand', () => {
	it('投影读不到：不静默继续，note 带原因，也不 arm', async () => {
		fetchGoalMock.mockResolvedValue(READ_FAIL);

		const r = await syncGoalAfterCommand('gui-1');

		expect(r.ok).toBe(false);
		expect(r.note).toContain('HTTP 503');
		expect(roundDriverMock).not.toHaveBeenCalled();
		expect(writes).toHaveLength(0);
	});

	it('读到活跃目标并 arm 成功：写两次 store（投影 + arm 回执）', async () => {
		fetchGoalMock.mockResolvedValue(READ_OK);
		roundDriverMock.mockResolvedValue({ok: true, goal: {...goal, revision: 2}, driver: null});

		const r = await syncGoalAfterCommand('gui-1');

		expect(r).toEqual({ok: true, note: ''});
		expect(roundDriverMock).toHaveBeenCalledWith('gui-1', 'arm');
		expect(writes).toHaveLength(2);
	});

	it('arm 失败：目标已投影，但 note 说清续跑没挂上', async () => {
		fetchGoalMock.mockResolvedValue(READ_OK);
		roundDriverMock.mockResolvedValue({ok: false, conflict: null, message: 'loopback only'});

		const r = await syncGoalAfterCommand('gui-1');

		expect(r.ok).toBe(false);
		expect(r.note).toContain('自动续跑没挂上');
		expect(r.note).toContain('loopback only');
	});

	it('确认没有活跃目标与读不到是两种说法', async () => {
		fetchGoalMock.mockResolvedValue(READ_EMPTY);

		const r = await syncGoalAfterCommand('gui-1');

		expect(r.ok).toBe(false);
		expect(r.note).toContain('投影里没有活跃目标');
	});

	it('goal 绑在后端会话 id 时：读与 arm 都对后端 id，store 写在 GUI id 上', async () => {
		fetchGoalMock.mockResolvedValue(READ_OK);
		roundDriverMock.mockResolvedValue({ok: true, goal, driver: null});

		await syncGoalAfterCommand('gui-1', 'backend-9');

		expect(fetchGoalMock).toHaveBeenNthCalledWith(1, 'backend-9');
		expect(roundDriverMock).toHaveBeenCalledWith('backend-9', 'arm');
		expect(Object.keys(writes[0] as {sessionGoalById: never})).toContain(
			'sessionGoalById',
		);
	});

	it('writeGoalState 仍按整值写入 store（SSE / GET / 命令三源同形）', () => {
		writeGoalState('s9', {goal, driver: null});

		expect(writes).toHaveLength(1);
		expect(
			(writes[0] as {sessionGoalById: Record<string, unknown>}).sessionGoalById.s9,
		).toBeTruthy();
	});
});
