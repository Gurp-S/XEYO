import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';

// Any mutation or newer projection invalidates reads already in flight.
const generations = new Map<string, number>();

export function invalidateGoalReads(sessionId: string): void {
	generations.set(sessionId, (generations.get(sessionId) ?? 0) + 1);
}

export function goalBackendId(sessionId: string): string {
	return activeBackendSessionId(useChatStore.getState().historyById ?? {}, sessionId);
}

export function goalReadToken(sessionId: string) {
	const generation = generations.get(sessionId) ?? 0;
	const backendId = goalBackendId(sessionId);
	return {
		backendId,
		isCurrent: () => generation === (generations.get(sessionId) ?? 0) &&
			backendId === goalBackendId(sessionId),
	};
}
