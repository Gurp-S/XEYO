import {fetchSessionTask, loadServerSessionMessages, type SessionTaskInfo} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import {mergeTranscriptWithLocalThoughts} from '@/lib/mergeTranscript';
import {mergeTranscript} from '@/lib/transcriptOrder';
import {transcriptSnapshotInfo} from '@/lib/transcriptSnapshot';

export function hasLocalOnlyOutput(local: ChatMessage[], server: ChatMessage[]) {
	const ids = new Set(server.map(row => row.id));
	return local.some(row => row.role !== 'user' && !row.uiOnly && !row.isThought && !ids.has(row.id));
}

const settled = (task: SessionTaskInfo | null, backendId: string): task is SessionTaskInfo => Boolean(task &&
	task.ok && task.session_id === backendId && !task.busy && !task.waiting_permission &&
	['idle', 'succeeded', 'stopped', 'failed'].includes(task.status));

/** A destructive recovery needs a complete read bracketed by the same settled turn. */
export async function canonicalSessionHistory(backendId: string, local: ChatMessage[], isCurrent: () => boolean) {
	const before = await fetchSessionTask(backendId);
	if (!isCurrent() || !settled(before, backendId)) return null;
	const server = await loadServerSessionMessages(backendId);
	if (!isCurrent() || !transcriptSnapshotInfo(server)?.complete) return null;
	const after = await fetchSessionTask(backendId);
	if (!isCurrent() || !settled(after, backendId) || before.turn_id !== after.turn_id ||
		before.revision !== after.revision || before.last_event_id !== after.last_event_id || before.status !== after.status) return null;
	const canonical = mergeTranscriptWithLocalThoughts(server, local);
	const ids = new Set(canonical.map(row => row.id));
	const removed = new Set(local.filter(row => !ids.has(row.id) && row.role !== 'user' && !row.uiOnly && !row.isThought).map(row => row.id));
	const preserved = local.map(row => row.role === 'user' && !ids.has(row.id) && !row.queueState && !row.uiOnly
		? {...row, localUndelivered: true} : row);
	return mergeTranscript(preserved, canonical, removed);
}
