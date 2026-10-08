import type {StoreApi} from 'zustand';
import {activeBackendSessionId, type ChatState} from './preStoreHelpers';

export function captureRecoveryAction(set: StoreApi<ChatState>['setState'], get: StoreApi<ChatState>['getState'], sessionId: string) {
	const recovery = get().recoveryBySession[sessionId];
	if (!recovery?.turnId) return null;
	const backendId = activeBackendSessionId(get().historyById, sessionId);
	const isCurrent = (state = get()) => state.sessions.some(session => session.id === sessionId) &&
		activeBackendSessionId(state.historyById, sessionId) === backendId && state.recoveryBySession[sessionId] === recovery;
	return {
		backendId, turnId: recovery.turnId, key: JSON.stringify([sessionId, backendId, recovery.turnId]), isCurrent,
		clear: () => set(state => {
			if (!isCurrent(state)) return state;
			const next = {...state.recoveryBySession}; delete next[sessionId];
			return {recoveryBySession: next};
		}),
	};
}
