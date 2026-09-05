import type {ChatMessage} from '@/lib/types';

/** 正在流式写入、尚未 finalize 的 Thought id（禁止落盘/同步半成品）。 */
const streamingThoughtIds = new Set<string>();

export function markThoughtStreaming(id: string): void {
	streamingThoughtIds.add(id);
}

export function markThoughtFinalized(id: string): void {
	streamingThoughtIds.delete(id);
}

export function clearStreamingThoughtMarks(): void {
	streamingThoughtIds.clear();
}

export function isThoughtStreaming(id: string): boolean {
	return streamingThoughtIds.has(id);
}

export function isSyncableThought(m: ChatMessage): boolean {
	return (
		m.isThought === true &&
		Boolean(m.text.trim()) &&
		!streamingThoughtIds.has(m.id) &&
		!m.id.startsWith('thought-stream-')
	);
}

export function collectSyncableThoughts(
	msgs: ChatMessage[],
): Array<{id: string; text: string; thoughtMs?: number; createdAt: number}> {
	return msgs.filter(isSyncableThought).map(m => ({
		id: m.id,
		text: m.text,
		thoughtMs: m.thoughtMs,
		createdAt: m.createdAt,
	}));
}

/** 服务端 transcript 恢复后，把本地 IDB 里尚未落盘的 Thought 按时间插回。 */
export function mergeTranscriptWithLocalThoughts(
	server: ChatMessage[],
	local: ChatMessage[],
): ChatMessage[] {
	const serverIds = new Set(server.map(m => m.id));
	const localThoughts = collectSyncableThoughts(local);
	const missing = localThoughts.filter(t => !serverIds.has(t.id));
	if (missing.length === 0) {
		return server;
	}

	const merged = [...server];
	for (const thought of missing) {
		let insertAt = merged.length;
		for (let i = 0; i < merged.length; i++) {
			if (merged[i]!.createdAt > thought.createdAt) {
				insertAt = i;
				break;
			}
		}
		merged.splice(insertAt, 0, {
			id: thought.id,
			role: 'assistant',
			text: thought.text,
			isThought: true,
			thoughtMs: thought.thoughtMs,
			createdAt: thought.createdAt,
		});
	}
	return merged;
}
