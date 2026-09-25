/**
 * P1 mid-turn inbox UI slice：排队快照轮询 / 取消（Composer chip 的数据源）。
 */
import type {ChatState} from './preStoreHelpers';
import {
	acknowledgeInboxItems,
	cancelInboxItem,
	editInboxItem as editInboxItemApi,
	inboxSnapshot,
	loadServerSessionMessages,
	type InboxSnapshot,
} from '@/lib/api';
import {deleteMessageForSession, patchMessages, updateMessageText} from '@/lib/db';
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
				it.state === 'delivered'
					? 'syncing'
					: it.state === 'stuck'
					? 'stuck'
					: it.state === 'delivering'
						? 'delivering'
						: 'queued',
			position: i + 1,
			autorun: payload.autorun,
			delivery_id: it.delivery_id ?? it.message_id ?? null,
		}));
}

/** 把权威 inbox 快照投影到相应的用户气泡，不把本地状态写进后端消息。 */
function projectQueueStates(
	messages: ChatMessage[],
	items: InboxQueuedItem[],
): ChatMessage[] {
	const itemByMessageId = new Map<string, InboxQueuedItem>();
	for (const item of items) {
		if (item.message_id) {
			itemByMessageId.set(item.message_id, item);
		}
	}
	let changed = false;
	const next: ChatMessage[] = [];
	const releasedQueueMessages: ChatMessage[] = [];
	for (const message of messages) {
		if (message.role !== 'user') {
			next.push(message);
			continue;
		}
		const item = itemByMessageId.get(message.id);
		if (item) {
			const projectedText = item.state === 'syncing' ? message.text : item.text;
			if (message.queueState === item.state && message.text === projectedText) {
				next.push(message);
				continue;
			}
			changed = true;
			next.push({...message, text: projectedText, queueState: item.state});
			continue;
		}
		if (!message.queueState) {
			next.push(message);
			continue;
		}
		changed = true;
		const copy = {...message};
		delete copy.queueState;
		releasedQueueMessages.push(copy);
	}
	// after_turn 投递不会走当前浏览器的模型 SSE。把从权威 inbox 消失的气泡
	// 移到当时已有回复之后，避免它在 transcript 中把上一轮的工具/答复截断。
	let releasedAt = next.reduce(
		(max, message) => Math.max(max, message.createdAt + 1),
		Date.now(),
	);
	for (const message of releasedQueueMessages) {
		next.push({...message, createdAt: releasedAt++});
	}
	const knownIds = new Set(messages.map(message => message.id));
	for (const item of items) {
		const messageId = item.message_id?.trim();
		if (!messageId || knownIds.has(messageId)) continue;
		// A batch is one transcript user message. Its other local bubbles remain
		// visible while syncing, then are folded into the authoritative anchor row.
		if (item.state === 'syncing' && item.delivery_id && messageId !== item.delivery_id) {
			continue;
		}
		knownIds.add(messageId);
		changed = true;
		next.push({
			id: messageId,
			role: 'user',
			text: item.text,
			...(item.media_refs.length ? {mediaRefs: [...item.media_refs]} : {}),
			queueState: item.state,
			createdAt: item.queued_at > 0 ? item.queued_at : Date.now(),
		});
	}
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
			if (!get().sessions.some(session => session.id === sessionId)) {
				return false;
			}
			const snapshotItems = normalizeItems(payload);
			const snapshotIds = new Set(snapshotItems.map(item => item.queue_id));
			const previousItems = get().inboxBySession[sessionId] ?? [];
			// A completed receipt is acknowledged only after its server transcript is
			// present locally. Retain a delivering item as a syncing receipt if an
			// older backend version drops it directly at turn start.
			const syncItems = previousItems
				.filter(
					item =>
						(item.state === 'syncing' || item.state === 'delivering') &&
						!snapshotIds.has(item.queue_id),
				)
				.map(item => ({...item, state: 'syncing' as const}));
			const knownQueueIds = new Set(snapshotItems.map(item => item.queue_id));
			const items = [
				...snapshotItems,
				...syncItems.filter(item => {
					if (knownQueueIds.has(item.queue_id)) return false;
					knownQueueIds.add(item.queue_id);
					return true;
				}),
			];
			const currentMessages = get().messagesById[sessionId] ?? [];
			const projectedMessages = projectQueueStates(currentMessages, items);
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
			if (projectedMessages !== currentMessages) {
				const currentById = new Map(
					currentMessages.map(message => [message.id, message]),
				);
				const changedMessages = projectedMessages.filter(
					message => currentById.get(message.id) !== message,
				);
				await patchMessages(sessionId, changedMessages).catch(() => undefined);
			}

			const syncingGroups = new Map<string, InboxQueuedItem[]>();
			for (const item of items) {
				if (item.state !== 'syncing') continue;
				const deliveryId = item.delivery_id ?? item.message_id;
				if (!deliveryId) continue;
				const group = syncingGroups.get(deliveryId) ?? [];
				group.push(item);
				syncingGroups.set(deliveryId, group);
			}
			if (syncingGroups.size === 0) return true;

			const serverMessages = await loadServerSessionMessages(backendId(sessionId));
			if (
				!serverMessages.length ||
				revisions.get(sessionId) !== revision ||
				!get().sessions.some(session => session.id === sessionId)
			) {
				return true;
			}
			const serverUserIndex = new Map<string, number>();
			serverMessages.forEach((message, index) => {
				if (message.role === 'user') serverUserIndex.set(message.id, index);
			});
			const confirmed = [...syncingGroups.entries()].filter(([deliveryId]) =>
				serverUserIndex.has(deliveryId),
			);
			if (confirmed.length === 0) return true;

			const confirmedDeliveryIds = new Set(confirmed.map(([id]) => id));
			const confirmedQueueIds = new Set(
				confirmed.flatMap(([, group]) => group.map(item => item.queue_id)),
			);
			const aliasMessageIds = new Set(
				confirmed.flatMap(([deliveryId, group]) =>
					group
						.map(item => item.message_id)
						.filter((id): id is string => Boolean(id && id !== deliveryId)),
				),
			);
			const firstServerIndex = Math.min(
				...confirmed.map(([id]) => serverUserIndex.get(id)!),
			);
			const serverTail = serverMessages.slice(firstServerIndex);
			const acknowledged = await acknowledgeInboxItems(
				backendId(sessionId),
				[...confirmedQueueIds],
			);
			if (revisions.get(sessionId) !== revision) return false;

			let changedForDb: ChatMessage[] = [];
			set(s => {
				if (!s.sessions.some(session => session.id === sessionId)) return s;
				const messages = s.messagesById[sessionId] ?? [];
				const byId = new Map<string, ChatMessage>();
				for (const message of messages) {
					if (!aliasMessageIds.has(message.id)) byId.set(message.id, message);
				}
			for (const message of serverTail) {
				if (
					confirmedDeliveryIds.has(message.id) ||
					!byId.has(message.id)
				) {
					byId.set(message.id, message);
				}
			}
			const transcript = [...byId.values()].sort(
				(a, b) => a.createdAt - b.createdAt,
			);
			const remainingItems = acknowledged
				? items.filter(item => !confirmedQueueIds.has(item.queue_id))
				: items;
			const projected = projectQueueStates(transcript, remainingItems);
			const oldById = new Map(messages.map(message => [message.id, message]));
			changedForDb = projected.filter(
				message => oldById.get(message.id) !== message,
			);
			return {
				messagesById: {...s.messagesById, [sessionId]: projected},
				inboxBySession: {
					...s.inboxBySession,
					[sessionId]: remainingItems,
				},
			};
			});
			await Promise.all([
				patchMessages(sessionId, changedForDb).catch(() => undefined),
				...([...aliasMessageIds].map(id =>
					deleteMessageForSession(sessionId, id).catch(() => undefined),
				)),
			]);
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
			if (!get().sessions.some(session => session.id === sessionId)) {
				return true;
			}
			const initialInbox = get().inboxBySession[sessionId] ?? [];
			const item = initialInbox.find(it => it.queue_id === queue_id) ?? originalItem;
			const messageId = item?.message_id ?? null;
			set(s => {
				const prev = s.inboxBySession[sessionId] ?? [];
				const next = prev.filter(it => it.queue_id !== queue_id);
				const messages = s.messagesById[sessionId] ?? [];
				const nextMessages = messageId
					? messages.filter(message => message.id !== messageId)
					: messages;
				return {
					inboxBySession: {...s.inboxBySession, [sessionId]: next},
					...(nextMessages !== messages && nextMessages.length !== messages.length
						? {messagesById: {...s.messagesById, [sessionId]: nextMessages}}
						: {}),
				};
			});
			if (messageId) {
				void deleteMessageForSession(sessionId, messageId).catch(() => undefined);
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
			if (!get().sessions.some(session => session.id === sessionId)) {
				return true;
			}
			const initialInbox = get().inboxBySession[sessionId] ?? [];
			const item = initialInbox.find(it => it.queue_id === queue_id) ?? originalItem;
			const messageId = item?.message_id ?? null;
			set(s => {
				const prev = s.inboxBySession[sessionId] ?? [];
				const next = prev.map(it =>
					it.queue_id === queue_id ? {...it, text} : it,
				);
				const messages = s.messagesById[sessionId] ?? [];
				const nextMessages = messageId
					? messages.map(message =>
							message.id === messageId ? {...message, text} : message,
						)
					: messages;
				return {
					inboxBySession: {...s.inboxBySession, [sessionId]: next},
					...(nextMessages !== messages && nextMessages.some((m, i) => m !== messages[i])
						? {messagesById: {...s.messagesById, [sessionId]: nextMessages}}
						: {}),
				};
			});
			if (messageId) {
				void updateMessageText(sessionId, messageId, text).catch(() => undefined);
			}
			return true;
		},
	};
}

// 便于类型检查的再导出
export type {InboxQueuedItem};
