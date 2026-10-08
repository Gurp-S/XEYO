import type {StoreApi} from 'zustand';
import type {ChatStreamHandlers} from '@/lib/api';
import {normalizeSessionGoalState} from '@/lib/api/goals';
import {normalizeJobSnapshots} from '@/lib/api/jobs';
import {writeGoalState} from '@/lib/goalSync';
import {activeBackendSessionId, type ChatState} from './preStoreHelpers';

/** Both new streams and reattached streams project onto the current branch. */
export function sessionProjectionHandlers(
	set: StoreApi<ChatState>['setState'],
	get: StoreApi<ChatState>['getState'],
	sessionId: string,
	backendId: string,
): Pick<ChatStreamHandlers, 'onGoal' | 'onJobs'> {
	const accepts = (eventSessionId?: string) =>
		activeBackendSessionId(get().historyById, sessionId) === backendId &&
		(!eventSessionId || eventSessionId === backendId) &&
		get().sessions.some(s => s.id === sessionId);
	return {
		onGoal(event) {
			if (!accepts(event.sessionId)) return;
			const next = normalizeSessionGoalState(event.goal, event.driver);
			if (next || event.goal === null || (event.goal && typeof event.goal === 'object' &&
				!Array.isArray(event.goal) && Object.keys(event.goal).length === 0)) {
				writeGoalState(sessionId, next, set);
			}
		},
		onJobs(event) {
			if (!accepts(event.sessionId)) return;
			const jobs = normalizeJobSnapshots(event.jobs);
			set(s => {
				const next = {...s.sessionJobsById};
				if (jobs.length) next[sessionId] = jobs;
				else delete next[sessionId];
				return {sessionJobsById: next};
			});
		},
	};
}
