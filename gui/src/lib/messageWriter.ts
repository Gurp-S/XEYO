import type {ChatMessage} from '@/lib/types';
import {collectMessagesToPersist, seedPersistedMessages} from './messagePersist';

/** 单次发送：串行写入，等待期间仅保留最新快照；失败不提交已保存状态。 */
export function createMessageWriter(seed: ChatMessage[], storage: {
	patch: (messages: ChatMessage[]) => Promise<void>;
	replace: (messages: ChatMessage[]) => Promise<void>;
	/** Read the authoritative store after awaiting any previous database write. */
	current?: () => ChatMessage[] | null;
}) {
	let saved = seedPersistedMessages(seed);
	let pending: ChatMessage[] | null = null;
	let running = false;

	async function drain() {
		try {
			while (pending) {
				const messages = storage.current ? storage.current() : pending;
				pending = null;
				if (!messages) continue;
				const {toWrite, nextSaved} = collectMessagesToPersist(messages, saved);
				try {
					if ([...saved.keys()].some(id => !nextSaved.has(id))) {
						await storage.replace([...nextSaved.values()]);
					} else if (toWrite.length) {
						await storage.patch(toWrite);
					}
					saved = nextSaved;
				} catch {
					// 已有较新的快照时继续；否则留待下一次 write/exit 重试，不自旋。
					if (!pending) {pending = messages; break;}
				}
			}
		} finally {running = false;}
	}

	return (messages: ChatMessage[]) => {
		pending = messages;
		if (!running) {running = true; void drain();}
	};
}
