import type {ChatMessage} from '@/lib/types';

/** 用于检测 IDB 增量写：消息是否在 persist 后发生变化。 */
export function messagePersistFingerprint(m: ChatMessage): string {
	const tail = m.text.length > 48 ? m.text.slice(-48) : m.text;
	return [
		m.role,
		m.text.length,
		tail,
		m.toolName ?? '',
		m.toolStatus ?? '',
		m.isThought ? '1' : '0',
		m.thoughtMs ?? '',
		(m.toolInput ?? '').length,
	].join('|');
}

export function collectMessagesToPersist(
	messages: ChatMessage[],
	fingerprints: Map<string, string>,
): {toWrite: ChatMessage[]; nextFingerprints: Map<string, string>} {
	const toWrite: ChatMessage[] = [];
	const next = new Map(fingerprints);
	for (const m of messages) {
		const fp = messagePersistFingerprint(m);
		if (next.get(m.id) !== fp) {
			toWrite.push(m);
			next.set(m.id, fp);
		}
	}
	return {toWrite, nextFingerprints: next};
}

export function seedPersistFingerprints(
	messages: ChatMessage[],
): Map<string, string> {
	const out = new Map<string, string>();
	for (const m of messages) {
		out.set(m.id, messagePersistFingerprint(m));
	}
	return out;
}
