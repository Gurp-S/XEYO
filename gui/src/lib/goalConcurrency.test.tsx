import {act, cleanup, render, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {useChatStore} from '@/stores/chatStore';
import {useSessionGoalLive} from '@/hooks/useSessionGoalLive';
import {runGoalAction} from './goalMutations';
import {writeGoalState} from './goalSync';
import type {GoalReadResult, SessionGoalState} from './api/goals';

const fetchGoal = vi.hoisted(() => vi.fn());
const patchGoalAction = vi.hoisted(() => vi.fn());
vi.mock('./api/goals', async original => ({
	...await original<typeof import('./api/goals')>(), fetchGoal, patchGoalAction,
}));

const goal = (revision = 1, id = 'g1'): SessionGoalState => ({
	goal: {goal_id: id, title: 'T', text: 'T', status: 'active', revision,
		pending_complete: false, rounds: 0, max_rounds: 0, blocked_reason: ''}, driver: null,
});
function Reader() { useSessionGoalLive('gui'); return null; }
function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>(r => { resolve = r; });
	return {resolve, promise};
}
const state = () => useChatStore.getState().sessionGoalById.gui;
const branch = (backendId: string) => ({
	activeBranch: {branchId: backendId, backendSessionId: backendId},
});

beforeEach(() => {
	fetchGoal.mockReset(); patchGoalAction.mockReset();
	fetchGoal.mockResolvedValue({ok: false, goal: null, driver: null, message: 'offline'});
	useChatStore.setState({activeId: 'gui', sessions: [{id: 'gui'}] as never,
		historyById: {gui: branch('backend')} as never, sessionGoalById: {gui: null}});
});
afterEach(cleanup);

describe('goal projection concurrency', () => {
	it('reads on mount even with no goal and reads the backend branch', async () => {
		fetchGoal.mockResolvedValue({ok: true, ...goal(), message: ''});
		render(<Reader />);
		await waitFor(() => expect(state()?.goal.goal_id).toBe('g1'));
		expect(fetchGoal).toHaveBeenCalledWith('backend');
	});
	it.each([true, false])('a delayed GET cannot overwrite a pause (%s: old goal/empty)', async oldGoal => {
		const read = deferred<GoalReadResult>(); fetchGoal.mockReturnValue(read.promise);
		writeGoalState('gui', goal());
		render(<Reader />);
		patchGoalAction.mockResolvedValue({ok: true, goal: {...goal(2).goal, status: 'paused'}, driver: null});
		await runGoalAction('gui', 'pause');
		await act(async () => read.resolve({ok: true, goal: oldGoal ? goal().goal : null, driver: null, message: ''}));
		expect(state()?.goal).toMatchObject({revision: 2, status: 'paused'});
	});
	it('a lower revision from another projection cannot roll back state', () => {
		writeGoalState('gui', goal(4)); writeGoalState('gui', goal(1));
		expect(state()?.goal.revision).toBe(4);
	});
	it('replacement identity conflict refreshes but never retries an old edit onto it', async () => {
		writeGoalState('gui', goal());
		patchGoalAction.mockResolvedValue({ok: false, conflict: goal(1, 'g2').goal, message: 'goal_revision_conflict'});
		const result = await runGoalAction('gui', 'edit', {text: 'old edit'});
		expect(result?.ok).toBe(false); expect(patchGoalAction).toHaveBeenCalledTimes(1);
		expect(patchGoalAction).toHaveBeenCalledWith('backend', 'edit', {text: 'old edit', goal_id: 'g1', revision: 1});
		expect(state()?.goal.goal_id).toBe('g2');
	});
	it('an old rendered editor cannot submit after the goal was replaced', async () => {
		writeGoalState('gui', goal(1, 'g2'));
		expect(await runGoalAction('gui', 'edit', {goal_id: 'g1', text: 'old edit'})).toMatchObject({ok: false});
		expect(patchGoalAction).not.toHaveBeenCalled();
	});
	it('branch switching discards late reads and clears the previous branch projection', async () => {
		const read = deferred<GoalReadResult>(); fetchGoal.mockReturnValueOnce(read.promise);
		writeGoalState('gui', goal()); render(<Reader />);
		act(() => useChatStore.setState({historyById: {gui: branch('next')} as never}));
		await waitFor(() => expect(fetchGoal).toHaveBeenCalledWith('next'));
		await act(async () => read.resolve({ok: true, ...goal(), message: ''}));
		expect(state()).toBeNull();
	});
});
