import type {ChatMessage} from './types';

const undelivered = (m: ChatMessage) => m.role === 'user' && m.queueState ? true : m.localUndelivered;

/** Compare before copying; still detect in-place edits against the saved snapshot. */
export function samePersistedMessage(a: ChatMessage, b: ChatMessage): boolean {
	if (a.localUndelivered !== undelivered(b)) return false;
	for (const key in a) {
		if (key === 'queueState' || key === 'localUndelivered') continue;
		const field = key as keyof ChatMessage;
		if (field === 'mediaRefs') {
			if (a.mediaRefs?.length !== b.mediaRefs?.length ||
				a.mediaRefs?.some((ref, i) => ref !== b.mediaRefs?.[i])) return false;
		} else if (a[field] !== b[field]) return false;
	}
	for (const key in b) {
		if (key !== 'queueState' && key !== 'localUndelivered' && !(key in a) && b[key as keyof ChatMessage] !== undefined) return false;
	}
	return true;
}
