import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {streamTurnEvents} from '@/lib/api/chatStream';
import {useChatStore} from '@/stores/chatStore';
import {sessionProjectionHandlers} from './sessionProjectionHandlers';

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => useChatStore.setState({sessions: [{id: 'gui'}] as never,
	historyById: {gui: {activeBranch: {branchId: 'root', backendSessionId: 'backend'}}} as never,
	sessionGoalById: {gui: {goal: {goal_id: 'existing'} as never, driver: null}}, sessionJobsById: {}}));

describe('reattached session projections', () => {
	it('delivers goal and jobs through the real SSE parser onto the GUI branch', async () => {
		useChatStore.setState({sessions: [{id: 'gui'}] as never,
			historyById: {gui: {activeBranch: {branchId: 'root', backendSessionId: 'backend'}}} as never,
			sessionGoalById: {}, sessionJobsById: {gui: [{}] as never}});
		const goal = {goal_id: 'g1', title: 'T', text: 'T', status: 'paused', revision: 2,
			pending_complete: false, rounds: 0, max_rounds: 0, blocked_reason: ''};
		const body = [
			{xy: {type: 'goal', goal, session_id: 'backend'}},
			{xy: {type: 'jobs', jobs: [], session_id: 'backend'}},
		].map(frame => `data: ${JSON.stringify(frame)}\n\n`).join('') + 'data: [DONE]\n\n';
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)));
		const done = vi.fn(); const error = vi.fn();
		await streamTurnEvents('backend', 0, {
			...sessionProjectionHandlers(useChatStore.setState, useChatStore.getState, 'gui', 'backend'),
			onDelta: () => {}, onDone: done, onError: error,
		});
		expect(error).not.toHaveBeenCalled(); expect(done).toHaveBeenCalledOnce();
		expect(useChatStore.getState().sessionGoalById.gui?.goal).toEqual(goal);
		expect(useChatStore.getState().sessionJobsById.gui).toBeUndefined();
	});
	it('ignores malformed and previous-branch frames rather than clearing the current goal', () => {
		const current = useChatStore.getState().sessionGoalById.gui;
		const handlers = sessionProjectionHandlers(useChatStore.setState, useChatStore.getState, 'gui', 'backend');
		handlers.onGoal?.({goal: {bad: true}, driver: null});
		expect(useChatStore.getState().sessionGoalById.gui).toBe(current);
		useChatStore.setState({historyById: {gui: {activeBranch: {branchId: 'root', backendSessionId: 'next'}}} as never});
		handlers.onGoal?.({goal: null, driver: null, sessionId: 'backend'});
		expect(useChatStore.getState().sessionGoalById.gui).toBe(current);
	});
});
