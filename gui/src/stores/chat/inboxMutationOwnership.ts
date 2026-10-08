import {activeBackendSessionId, type ChatState} from './preStoreHelpers';

/** A queue mutation owns the backend branch it addressed, including DB waits. */
export function captureInboxMutation(get: () => ChatState, sessionId: string) {
	const backendId = activeBackendSessionId(get().historyById, sessionId);
	const branchId = get().historyById[sessionId]?.activeBranch.branchId;
	const isCurrent = (state = get()) => state.sessions.some(session => session.id === sessionId && !session.archived) &&
		activeBackendSessionId(state.historyById, sessionId) === backendId &&
		state.historyById[sessionId]?.activeBranch.branchId === branchId;
	return {backendId, isCurrent};
}
