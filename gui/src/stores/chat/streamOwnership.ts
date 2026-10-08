import type {StoreApi} from 'zustand';
import {getSessionStream} from '@/lib/sessionStreams';
import {activeBackendSessionId, type ChatState} from './preStoreHelpers';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

/** A recovery operation may update only the branch and connection it observed. */
export function createStreamOwnership(
	set: SetState, get: GetState, sessionId: string, backendId: string,
) {
	let stream = getSessionStream(get(), sessionId);
	let controller = stream.abortRef;
	let turnId = stream.turnId;
	let aborted = controller?.signal.aborted;
	const matchesBranch = (state = get()) =>
		state.sessions.some(session => session.id === sessionId) &&
		activeBackendSessionId(state.historyById, sessionId) === backendId;
	const isCurrent = (state = get()) => {
		const current = getSessionStream(state, sessionId);
		return matchesBranch(state) && current.abortRef === controller &&
			current.turnId === turnId && controller?.signal.aborted === aborted;
	};
	const ownedSet: SetState = update => {
		set(state => {
			if (!isCurrent(state)) return state;
			const patch = typeof update === 'function' ? update(state) : update;
			stream = getSessionStream({...state, ...patch}, sessionId);
			// Advance before subscribers run. A subscriber can start a newer turn.
			controller = stream.abortRef; turnId = stream.turnId;
			aborted = controller?.signal.aborted;
			return patch;
		});
	};
	return {isCurrent, matchesBranch, set: ownedSet};
}
