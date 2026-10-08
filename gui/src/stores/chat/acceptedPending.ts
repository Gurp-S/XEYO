import type {StoreApi} from 'zustand';
import {pendingMatchesActiveSession} from '@/lib/pendingForSession';
import type {ChatState} from './preStoreHelpers';

/** A failed send or a queue receipt cannot resolve an existing interaction. */
export function acceptedPendingClear(
	set: StoreApi<ChatState>['setState'],
	get: StoreApi<ChatState>['getState'],
	sessionId: string,
) {
	const {pendingAsk, pendingPlan} = get();
	return () => set(s => ({
		pendingAsk: pendingAsk && s.pendingAsk === pendingAsk &&
			pendingMatchesActiveSession(pendingAsk.sessionId, sessionId) ? null : s.pendingAsk,
		pendingPlan: pendingPlan && s.pendingPlan === pendingPlan &&
			pendingMatchesActiveSession(pendingPlan.sessionId, sessionId) ? null : s.pendingPlan,
	}));
}
