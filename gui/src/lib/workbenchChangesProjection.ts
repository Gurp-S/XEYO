import {consumeTools, latestUserTurnBoundary} from './groupTranscript';
import {collectChangedFilesFromItems, type ChangedFile} from './toolActivity';
import type {ChatMessage} from './types';

type Contribution = {next: ChatMessage | undefined; consumed: number; files: ChangedFile[]};

/** Per-view weak cache: immutable tool rows own parsing results. Prose updates do
 * not reparse tool JSON/diffs; legacy call/result pairs invalidate together.
 * A scan of message references remains, without retaining abandoned sessions.
 */
export function createWorkbenchChangesProjection() {
	const cache = new WeakMap<ChatMessage, Contribution>();
	let previous: Contribution[] = [];
	let result: ChangedFile[] = [];
	return (messages: ChatMessage[], messageId?: string): ChangedFile[] => {
		const chosen = messageId ? messages.findIndex(m => m.id === messageId && m.role === 'user') : -1;
		const start = chosen >= 0 ? chosen : latestUserTurnBoundary(messages)?.index ?? 0;
		let end = start + 1;
		while (end < messages.length) {
			const m = messages[end];
			if (m.role === 'user' && !m.queueState && !m.localUndelivered && !m.uiOnly) break;
			end++;
		}
		// Same queued-user filtering as groupTranscript, including legacy pairing.
		const round = messages.slice(start, end).filter(m => !(m.role === 'user' && m.queueState));
		const contributions: Contribution[] = [];
		for (let i = 0; i < round.length;) {
			const message = round[i];
			if (message.role !== 'tool') { i++; continue; }
			const next = message.toolInput === undefined && message.toolStatus === undefined ? round[i + 1] : undefined;
			let contribution = cache.get(message);
			if (!contribution || contribution.next !== next) {
				const consumed = consumeTools(round, i)!;
				contribution = {next, consumed: consumed.next - i, files: collectChangedFilesFromItems([consumed.item])};
				cache.set(message, contribution);
			}
			contributions.push(contribution);
			i += contribution.consumed;
		}
		if (contributions.length === previous.length && contributions.every((value, i) => value === previous[i])) return result;
		previous = contributions;
		const files = new Map<string, ChangedFile>();
		for (const contribution of contributions) for (const file of contribution.files) {
			const key = file.path.replace(/\\/g, '/').toLowerCase();
			const existing = files.get(key);
			if (!existing) files.set(key, {...file});
			else {
				existing.add += file.add; existing.del += file.del;
				if (file.created) existing.created = true;
				if (file.diff) existing.diff = file.diff;
			}
		}
		result = [...files.values()];
		return result;
	};
}
