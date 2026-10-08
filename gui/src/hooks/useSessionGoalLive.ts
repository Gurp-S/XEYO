import {useEffect, useRef} from 'react';
import {fetchGoal} from '@/lib/api/goals';
import {goalReadToken, invalidateGoalReads} from '@/lib/goalProjection';
import {writeGoalState} from '@/lib/goalSync';
import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';

/** Read independently of whether a goal is already visible. */
export function useSessionGoalLive(sessionId: string | null) {
	const previous = useRef<{sessionId: string; backendId: string} | null>(null);
	const backendId = useChatStore(s => sessionId
		? activeBackendSessionId(s.historyById, sessionId) : null);
	useEffect(() => {
		if (!sessionId || !backendId) return;
		if (previous.current?.sessionId === sessionId && previous.current.backendId !== backendId) {
			writeGoalState(sessionId, null);
		}
		previous.current = {sessionId, backendId};
		let stopped = false;
		let inflight = false;
		invalidateGoalReads(sessionId);
		const refresh = async () => {
			if (stopped || inflight || document.visibilityState !== 'visible') return;
			inflight = true;
			const token = goalReadToken(sessionId);
			try {
				const result = await fetchGoal(backendId);
				if (!stopped && token.isCurrent() && result.ok) {
					writeGoalState(sessionId, result.goal ? {goal: result.goal, driver: result.driver} : null);
				}
			} catch {
				// A failed read leaves the last valid projection intact.
			} finally {
				inflight = false;
			}
		};
		void refresh();
		const timer = window.setInterval(() => void refresh(), 3000);
		document.addEventListener('visibilitychange', refresh);
		return () => {
			stopped = true;
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', refresh);
		};
	}, [sessionId, backendId]);
}
