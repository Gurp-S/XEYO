/**
 * P1 mid-turn inbox UI slice：排队快照轮询 / 取消（Composer chip 的数据源）。
 */
import type {ChatState} from './preStoreHelpers';
import {
	cancelInboxItem,
	editInboxItem as editInboxItemApi,
	inboxSnapshot,
	type InboxSnapshot,
} from '@/lib/api';
import {replaceMessages} from '@/lib/db';
import type {ChatMessage} from '@/lib/types';
import {
	activeBackendSessionId,
	type InboxQueuedItem,
} from './preStoreHelpers';

type SetState = (partial: Partial<ChatState> | ((s: ChatState) => Partial<ChatState>)) => void;
type GetState = () => ChatState;

function normalizeItems(payload: InboxSnapshot | null): InboxQueuedItem[] {
	if (!payload || !Array.isArray(payload.items)) {
		return [];
	}
	return payload.items
		.filter(it => Boolean(String(it.queue_id ?? '').trim()))
		.map((it, i) => ({
			queue_id: String(it.queue_id).trim(),
			text: String(it.text ?? ''),
			media_refs: Array.isArray(it.media_refs) ? it.media_refs.map(String) : [],
			message_id: it.message_id ?? null,
			queued_at: Number(it.queued_at ?? 0),
			attempts: Number(it.attempts ?? 0),
			state:
				it.state === 'stuck'
					? 'stuck'
					: it.state === 'delivering'
						? 'delivering'
						: 'queued',
			position: i + 1,
		}));
}

/** 把权威 inbox 快照投影到相应的用户气泡，不把本地状态写进后端消息。 */
function projectQueueStates(
	messages: ChatMessage[],
	items: InboxQueuedItem[],
): ChatMessage[] {
	const stateByMessageId = new Map<string, ChatMessage['queueState']>();
	for (const item of items) {
		if (item.message_id) {
			stateByMessageId.set(item.message_id, item.state);
		}
	}
	let changed = false;
	const next = messages.map(message => {
		if (message.role !== 'user') return message;
		const queueState = stateByMessageId.get(message.id);
		if (queueState) {
			if (message.queueState === queueState) return message;
			changed = true;
			return {...message, queueState};
		}
		if (!message.queueState) return message;
		changed = true;
		const copy = {...message};
		delete copy.queueState;
		return copy;
	});
	return changed ? next : messages;
}

export function createInboxSlice(
	set: SetState,
	get: GetState,
): Pick<ChatState, 'refreshInbox' | 'cancelInboxItem' | 'editInboxItem'> {
	// Poll replies and mutations share a revision per UI session. A response that
	// started before a newer poll or an edit/cancel cannot overwrite newer state.
	const revisions = new Map<string, number>();
	const revise = (sessionId: string) => {
		const revision = (revisions.get(sessionId) ?? 0) + 1;
		revisions.set(sessionId, revision);
		return revision;
	};
	const backendId = (sessionId: string) =>
		activeBackendSessionId(get().historyById, sessionId);

	return {
		async refreshInbox(sessionId: string) {
			const revision = revise(sessionId);
			let payload: InboxSnapshot | null = null;
			try {
				payload = await inboxSnapshot(backendId(sessionId));
			} catch {
				return false;
			}
			// null means the snapshot failed; only an authoritative empty items[]
			// may clear queue cards.
			if (!payload || revisions.get(sessionId) !== revision) {
				return false;
			}
			const items = normalizeItems(payload);
			set(s => {
				const messages = s.messagesById[sessionId] ?? [];
				const projected = projectQueueStates(messages, items);
				return {
					inboxBySession: {...s.inboxBySession, [sessionId]: items},
					...(projected !== messages
						? {messagesById: {...s.messagesById, [sessionId]: projected}}
						: {}),
				};
			});
			return true;
		},
		async cancelInboxItem(sessionId: string, queue_id: string) {
			const originalItem = (get().inboxBySession[sessionId] ?? []).find(
				it => it.queue_id === queue_id,
			);
			revise(sessionId);
			let ok = false;
			try {
				ok = await cancelInboxItem(backendId(sessionId), queue_id);
			} catch {
				ok = false;
			} finally {
				revise(sessionId);
			}
			// 失败（delivering 409 / 网络）不本地移除，调用方据返回值提示。
			if (!ok) {
				return false;
			}
			let persistedMessages: ChatMessage[] | null = null;
			set(s => {
				const prev = s.inboxBySession[sessionId] ?? [];
				const next = prev.filter(it => it.queue_id !== queue_id);
				const item = prev.find(it => it.queue_id === queue_id) ?? originalItem;
				const messageId = item?.message_id;
				const messages = s.messagesById[sessionId] ?? [];
				const nextMessages = messageId
					? messages.filter(message => message.id !== messageId)
					: messages;
				if (nextMessages !== messages && nextMessages.length !== messages.length) {
					persistedMessages = nextMessages;
				}
				return {
				inboxBySession: {...s.inboxBySession, [sessionId]: next},
					...(persistedMessages
						? {messagesById: {...s.messagesById, [sessionId]: persistedMessages}}
						: {}),
				};
			});
			if (persistedMessages) {
				void replaceMessages(sessionId, persistedMessages).catch(() => undefined);
			}
			return true;
		},
		async editInboxItem(sessionId: string, queue_id: string, text: string) {
			const originalItem = (get().inboxBySession[sessionId] ?? []).find(
				it => it.queue_id === queue_id,
			);
			revise(sessionId);
			let ok = false;
			try {
				ok = await editInboxItemApi(backendId(sessionId), queue_id, text);
			} catch {
				ok = false;
			} finally {
				revise(sessionId);
			}
			// 失败不改本地文本，调用方据返回值提示（避免「以为保存了」）。
			if (!ok) {
				return false;
			}
			let persistedMessages: ChatMessage[] | null = null;
			set(s => {
				const prev = s.inboxBySession[sessionId] ?? [];
				const item = prev.find(it => it.queue_id === queue_id) ?? originalItem;
				const next = prev.map(it =>
					it.queue_id === queue_id ? {...it, text} : it,
				);
				const messages = s.messagesById[sessionId] ?? [];
				const nextMessages = item?.message_id
					? messages.map(message =>
							message.id === item.message_id ? {...message, text} : message,
						)
					: messages;
				if (nextMessages !== messages && nextMessages.some((m, i) => m !== messages[i])) {
					persistedMessages = nextMessages;
				}
				return {
					inboxBySession: {...s.inboxBySession, [sessionId]: next},
					...(persistedMessages
						? {messagesById: {...s.messagesById, [sessionId]: persistedMessages}}
						: {}),
				};
			});
			if (persistedMessages) {
				void replaceMessages(sessionId, persistedMessages).catch(() => undefined);
			}
			return true;
		},
	};
}

// 便于类型检查的再导出
export type {InboxQueuedItem};
