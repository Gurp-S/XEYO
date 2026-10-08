import type {ChatMessage} from './types';

export function stampTranscriptOrder(messages: ChatMessage[]): ChatMessage[] {
	return messages.map((message, transcriptOrder) => ({...message, transcriptOrder}));
}

export function compareTranscriptOrder(a: ChatMessage, b: ChatMessage): number {
	if (a.transcriptOrder != null || b.transcriptOrder != null) {
		return (a.transcriptOrder ?? Infinity) - (b.transcriptOrder ?? Infinity) || a.createdAt - b.createdAt;
	}
	return a.createdAt - b.createdAt;
}

/** Server rows define their order; local-only rows retain their nearby anchor. */
export function mergeTranscript(
	local: ChatMessage[], server: ChatMessage[], removedIds: Set<string> = new Set(),
): ChatMessage[] {
	const serverIds = new Set(server.map(m => m.id));
	const extras = new Map<string | null, ChatMessage[]>();
	let anchor: string | null = null;
	for (let i = local.length - 1; i >= 0; i--) {
		const message = local[i]!;
		if (serverIds.has(message.id)) { anchor = message.id; continue; }
		if (removedIds.has(message.id)) continue;
		const key = message.queueState ? null : anchor;
		const group = extras.get(key) ?? []; group.unshift(message); extras.set(key, group);
	}
	const byId = new Map(local.map(m => [m.id, m]));
	const out: ChatMessage[] = [];
	for (const row of server) {
		out.push(...extras.get(row.id) ?? []);
		const old = byId.get(row.id);
		const combined = {...old, ...row};
		// A backfilled list can also contain retained local input. Only an
		// actual delivered row acknowledges those local delivery markers.
		if (!row.queueState && !row.localUndelivered && !row.uiOnly) {
			delete combined.queueState;
			delete combined.localUndelivered;
		}
		out.push(combined);
	}
	out.push(...extras.get(null) ?? []);
	return stampTranscriptOrder(out);
}
