import type {ChatMessage} from '@/lib/types';

/** 保存快照不含运行期投递状态；复制媒体数组以免后续修改污染快照。 */
function snapshot(m: ChatMessage): ChatMessage {
	const {queueState: _queueState, ...saved} = m;
	return saved.mediaRefs ? {...saved, mediaRefs: [...saved.mediaRefs]} : saved;
}

function sameMessage(a: ChatMessage, b: ChatMessage): boolean {
	for (const key in a) {
		if (key === 'queueState') continue;
		const field = key as keyof ChatMessage;
		if (field === 'mediaRefs') {
			if (a.mediaRefs?.length !== b.mediaRefs?.length ||
				a.mediaRefs?.some((ref, i) => ref !== b.mediaRefs?.[i])) return false;
		} else if (a[field] !== b[field]) return false;
	}
	for (const key in b) {
		if (key !== 'queueState' && !(key in a) && b[key as keyof ChatMessage] !== undefined) return false;
	}
	return true;
}

export function collectMessagesToPersist(
	messages: ChatMessage[],
	saved: Map<string, ChatMessage>,
): {toWrite: ChatMessage[]; nextSaved: Map<string, ChatMessage>} {
	const toWrite: ChatMessage[] = [];
	const nextSaved = new Map<string, ChatMessage>();
	for (const m of messages) {
		const previous = saved.get(m.id);
		if (previous && sameMessage(previous, m)) {
			nextSaved.set(m.id, previous);
		} else {
			const copy = snapshot(m);
			toWrite.push(copy);
			nextSaved.set(m.id, copy);
		}
	}
	return {toWrite, nextSaved};
}

export function seedPersistedMessages(messages: ChatMessage[]): Map<string, ChatMessage> {
	return new Map(messages.map(m => [m.id, snapshot(m)]));
}
