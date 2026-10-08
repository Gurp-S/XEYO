import type {ChatMessage} from '@/lib/types';
import {uid} from '@/lib/utils';

/** One output keeps one identity through tool flush, drain, server merge and commit. */
export function createAssistantOutput() {
	let messageId = '';
	let authoritative = false;
	let prefix = '';
	return {
		getId: () => messageId,
		begin(id?: string) {
			if (id && id !== messageId) { messageId = id; prefix = ''; authoritative = true; }
			if (!messageId) messageId = uid('msg');
		},
		append(messages: ChatMessage[], text: string): ChatMessage[] {
			if (!text.trim()) return messages;
			if (!messageId) messageId = uid('msg');
			const full = (prefix + text).trim();
			const index = messages.findIndex(m => m.id === messageId && m.role === 'assistant' && !m.isThought);
			if (index >= 0) {
				const current = messages[index]!;
				// A complete transcript can arrive before the client has drained its prefix.
				if (current.text === full || current.text.startsWith(full)) return messages;
				const next = [...messages]; next[index] = {...current, text: full}; return next;
			}
			const next = [...messages];
			const pendingIndex = next.findIndex(m => m.queueState === 'queued' || m.queueState === 'stuck');
			next.splice(pendingIndex < 0 ? next.length : pendingIndex, 0,
				{id: messageId, role: 'assistant', text: full, createdAt: Date.now()});
			return next;
		},
		finishSegment(text: string) {
			if (authoritative) prefix += text;
			else { messageId = ''; prefix = ''; }
		},
	};
}
