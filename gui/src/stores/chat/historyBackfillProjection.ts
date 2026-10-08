import type {ChatMessage} from '@/lib/types';
import {mergeTranscript} from '@/lib/transcriptOrder';

/** Preserve rows added during the read, while applying its proven removals. */
export function projectHistoryBackfill(
	snapshot: ChatMessage[], current: ChatMessage[], loaded: ChatMessage[],
): ChatMessage[] {
	if (current === snapshot) return loaded;
	const loadedIds = new Set(loaded.map(row => row.id));
	const removed = new Set(snapshot.filter(row => !loadedIds.has(row.id)).map(row => row.id));
	return mergeTranscript(current, loaded, removed);
}
