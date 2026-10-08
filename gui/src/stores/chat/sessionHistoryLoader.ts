import {loadServerSessionMessages} from '@/lib/api';
import {loadMessages, replaceMessages, replaceMessagesWithHistoryBackup} from '@/lib/db';
import {mergeTranscriptWithLocalThoughts} from '@/lib/mergeTranscript';
import {mergeTranscript} from '@/lib/transcriptOrder';
import {mergeIncompleteTranscript, transcriptSnapshotInfo} from '@/lib/transcriptSnapshot';
import type {ChatMessage} from '@/lib/types';
import {recoverSessionMessages, scheduleThoughtSync, shouldPreferServerMessages} from './streamHelpers';
import {canonicalSessionHistory, hasLocalOnlyOutput} from './canonicalSessionHistory';
import {toast} from '@/lib/toast';

export type HistoryLoadOptions = {
	preferServer?: boolean;
	localSnapshot?: {messages: ChatMessage[]; changed: boolean};
	isCurrent?: () => boolean;
};

// Share transport only. Branch identity and local snapshots belong to each caller.
const serverLoads = new Map<string, Promise<ChatMessage[]>>();
const latestLoads = new Map<string, symbol>();
function serverMessages(backendId: string) {
	const existing = serverLoads.get(backendId);
	if (existing) return existing;
	const work = loadServerSessionMessages(backendId).finally(() => {
		if (serverLoads.get(backendId) === work) serverLoads.delete(backendId);
	});
	serverLoads.set(backendId, work);
	return work;
}

function sameTranscriptRows(local: ChatMessage[], server: ChatMessage[]) {
	const canonical = (rows: ChatMessage[]) => rows.filter(row => !row.isThought && !row.uiOnly && !row.queueState && !row.localUndelivered);
	const left = canonical(local); const right = canonical(server);
	const ids = new Set(right.map(row => row.id));
	return right.length > 0 && left.length === right.length && left.every(row => ids.has(row.id));
}

export async function loadSessionHistory(
	sessionId: string, backendId: string, options?: HistoryLoadOptions,
): Promise<ChatMessage[]> {
	const token = Symbol(sessionId); latestLoads.set(sessionId, token);
	const isCurrent = () => latestLoads.get(sessionId) === token && (options?.isCurrent?.() ?? true);
	try {
		const local = options?.localSnapshot ?? recoverSessionMessages(await loadMessages(sessionId));
		if (!isCurrent()) return local.messages;
		let chosen = local.messages;
		try {
			const rawServer = await serverMessages(backendId);
			const snapshot = transcriptSnapshotInfo(rawServer);
			const server = recoverSessionMessages(rawServer);
			if (!isCurrent()) return chosen;
			if (snapshot && !snapshot.complete && server.messages.length > 0) {
				chosen = mergeIncompleteTranscript(local.messages, server.messages);
				await replaceMessages(sessionId, chosen, isCurrent);
			} else if (snapshot?.complete && !options?.preferServer && hasLocalOnlyOutput(local.messages, server.messages)) {
				const canonical = await canonicalSessionHistory(backendId, local.messages, isCurrent);
				if (!isCurrent()) return chosen;
				if (canonical) {
					try {
						if (await replaceMessagesWithHistoryBackup(sessionId, backendId, local.messages, canonical, isCurrent)) chosen = canonical;
					} catch {
						if (isCurrent()) toast.warn('历史备份未完成，已保留原本地历史');
					}
				} else {
					chosen = mergeIncompleteTranscript(local.messages, server.messages);
					await replaceMessages(sessionId, chosen, isCurrent);
				}
			} else if ((options?.preferServer && server.messages.length > 0) ||
				shouldPreferServerMessages(local.messages, server.messages) ||
				sameTranscriptRows(local.messages, server.messages)) {
				chosen = mergeTranscriptWithLocalThoughts(server.messages, local.messages);
				if (!options?.preferServer) {
					// Pending input and local UI rows are not delivered transcript rows.
					const ids = new Set(chosen.map(row => row.id));
					const removed = new Set(local.messages.filter(row => !ids.has(row.id) && !row.queueState && !row.localUndelivered && !row.uiOnly).map(row => row.id));
					chosen = mergeTranscript(local.messages, chosen, removed);
				}
				await replaceMessages(sessionId, chosen, isCurrent);
				if (isCurrent()) scheduleThoughtSync(backendId, chosen);
			} else if (local.changed) {
				await replaceMessages(sessionId, chosen, isCurrent);
			}
		} catch {
			if (local.changed && isCurrent()) await replaceMessages(sessionId, chosen, isCurrent);
		}
		return chosen;
	} finally {
		// The guarded write finishes before the request is released. No per-session
		// generation entries remain after loading or accumulate for deleted sessions.
		if (latestLoads.get(sessionId) === token) latestLoads.delete(sessionId);
	}
}
