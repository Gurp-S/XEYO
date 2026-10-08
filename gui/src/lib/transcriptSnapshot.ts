import type {ChatMessage} from './types';
import {mergeTranscriptWithLocalThoughts} from './mergeTranscript';
import {mergeTranscript} from './transcriptOrder';

export type TranscriptSnapshotInfo = {complete: boolean};
// Preserve transport facts without changing the established message-array API.
// Entries live only as long as the returned arrays.
const snapshots = new WeakMap<ChatMessage[], TranscriptSnapshotInfo>();

export function rememberTranscriptSnapshot(messages: ChatMessage[], payload: unknown, sessionId: string) {
	const receipt = payload as Record<string, unknown> | null;
	const complete = Boolean(receipt && receipt.session_id === sessionId &&
		receipt.transcript_found === true && receipt.degraded === false &&
		receipt.skipped_lines === 0 && Array.isArray(receipt.read_errors) && receipt.read_errors.length === 0);
	snapshots.set(messages, {complete});
	return messages;
}

export function transcriptSnapshotInfo(messages: ChatMessage[]) {
	return snapshots.get(messages);
}

/** Incomplete server history may contribute rows, but cannot remove local rows. */
export function mergeIncompleteTranscript(local: ChatMessage[], server: ChatMessage[]) {
	const canonical = mergeTranscriptWithLocalThoughts(server, local);
	const ids = new Set(canonical.map(row => row.id));
	return mergeTranscript(local.filter(row => !row.isThought || ids.has(row.id)), canonical);
}
