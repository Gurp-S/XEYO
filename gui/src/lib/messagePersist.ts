import {samePersistedMessage} from "./messageEquality";
import type {ChatMessage} from '@/lib/types';
import {persistableMessage} from './messageDeliveryPersistence';

/** 保存快照不含运行期投递状态；复制媒体数组以免后续修改污染快照。 */
function snapshot(m: ChatMessage): ChatMessage {
	const saved = persistableMessage(m);
	return saved.mediaRefs ? {...saved, mediaRefs: [...saved.mediaRefs]} : saved;
}

export function collectMessagesToPersist(
	messages: ChatMessage[],
	saved: Map<string, ChatMessage>,
): {toWrite: ChatMessage[]; nextSaved: Map<string, ChatMessage>} {
	const toWrite: ChatMessage[] = [];
	const nextSaved = new Map<string, ChatMessage>();
	for (const m of messages) {
		const previous = saved.get(m.id);
		if (previous && samePersistedMessage(previous, m)) {
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
