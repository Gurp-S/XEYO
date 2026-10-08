import {patchGoalAction, type GoalAction, type GoalPatchOptions, type GoalMutationResult} from './api/goals';
import {goalBackendId, invalidateGoalReads} from './goalProjection';
import {writeGoalState} from './goalSync';
import {useChatStore} from '@/stores/chatStore';

/** Revision CAS is scoped to one goal identity and one backend branch. */
export async function runGoalAction(
	sessionId: string,
	action: Exclude<GoalAction, 'new'>,
	options: GoalPatchOptions = {},
): Promise<GoalMutationResult | null> {
	const initial = useChatStore.getState().sessionGoalById[sessionId];
	if (!initial) return null;
	if (options.goal_id && options.goal_id !== initial.goal.goal_id) {
		return {ok: false, conflict: null, message: 'goal_changed'};
	}
	const backendId = goalBackendId(sessionId);
	const goalId = initial.goal.goal_id;
	const stillCurrent = () => goalBackendId(sessionId) === backendId &&
		useChatStore.getState().sessionGoalById[sessionId]?.goal.goal_id === goalId;
	invalidateGoalReads(sessionId);
	const run = (revision: number) => patchGoalAction(backendId, action, {
		...options, goal_id: goalId, revision,
	});
	let result = await run(initial.goal.revision);
	if (!stillCurrent()) return {ok: false, conflict: null, message: 'goal_changed'};
	if (!result.ok && result.conflict) {
		writeGoalState(sessionId, {goal: result.conflict, driver: initial.driver});
		if (result.conflict.goal_id !== goalId) return result;
		result = await run(result.conflict.revision);
		if (!stillCurrent()) return {ok: false, conflict: null, message: 'goal_changed'};
	}
	if (result.ok && result.goal?.goal_id !== goalId) {
		return {ok: false, conflict: null, message: 'goal_changed'};
	}
	if (result.ok && result.goal) {
		writeGoalState(sessionId, {goal: result.goal, driver: result.driver ?? initial.driver});
	}
	return result;
}
