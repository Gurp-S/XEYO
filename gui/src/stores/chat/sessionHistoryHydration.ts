import {loadChatHistoryState} from '@/lib/db';
import {activeBackendSessionId, normalizeChatHistoryState, type ChatState} from './preStoreHelpers';
import {createStreamOwnership} from './streamOwnership';
import type {StoreApi} from 'zustand';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];
const loads = new Map<string, {work: Promise<boolean>; isCurrent: () => boolean}>();

/** Restore the backend identity before recovering messages or submitting input. */
export function ensureSessionHistory(set: SetState, get: GetState, sessionId: string): Promise<boolean> {
	if (get().historyById[sessionId]) return Promise.resolve(true);
	const existing = loads.get(sessionId);
	if (existing?.isCurrent()) return existing.work;
	const ownership = createStreamOwnership(set, get, sessionId, activeBackendSessionId(get().historyById, sessionId));
	const entry = {isCurrent: ownership.isCurrent, work: Promise.resolve(false)};
	entry.work = (async () => {
		const history = normalizeChatHistoryState(await loadChatHistoryState(sessionId), sessionId);
		if (!ownership.isCurrent()) return false;
		set(state => ({historyById: {...state.historyById, [sessionId]: history}}));
		return true;
	})().finally(() => {if (loads.get(sessionId) === entry) loads.delete(sessionId);});
	loads.set(sessionId, entry);
	return entry.work;
}
