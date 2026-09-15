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
import type {InboxQueuedItem} from './preStoreHelpers';

type SetState = (partial: Partial<ChatState> | ((s: ChatState) => Partial<ChatState>)) => void;
type GetState = () => ChatState;

function normalizeItems(payload: InboxSnapshot | null): InboxQueuedItem[] {
	if (!payload || !Array.isArray(payload.items)) {
		return [];
	}
	return payload.items.map((it, i) => ({
		queue_id: String(it.queue_id ?? ''),
		text: String(it.text ?? ''),
		media_refs: Array.isArray(it.media_refs) ? it.media_refs.map(String) : [],
		message_id: it.message_id ?? null,
		queued_at: Number(it.queued_at ?? 0),
		attempts: Number(it.attempts ?? 0),
		state: (it.state === 'stuck' ? 'stuck' : it.state === 'delivering' ? 'delivering' : 'queued'),
		position: i + 1,
	}));
}

export function createInboxSlice(
	set: SetState,
	_get: GetState,
): Pick<ChatState, 'refreshInbox' | 'cancelInboxItem' | 'editInboxItem'> {
	return {
		async refreshInbox(sessionId: string) {
			const payload = await inboxSnapshot(sessionId);
			const items = normalizeItems(payload);
			set(s => ({
				inboxBySession: {...s.inboxBySession, [sessionId]: items},
			}));
		},
		async cancelInboxItem(sessionId: string, queue_id: string) {
			const ok = await cancelInboxItem(sessionId, queue_id);
			// 失败（delivering 409 / 网络）不本地移除，调用方据返回值提示。
			if (!ok) {
				return false;
			}
			set(s => {
				const prev = s.inboxBySession[sessionId] ?? [];
				const next = prev.filter(it => it.queue_id !== queue_id);
				return {
					inboxBySession: {...s.inboxBySession, [sessionId]: next},
				};
			});
			return true;
		},
		async editInboxItem(sessionId: string, queue_id: string, text: string) {
			const ok = await editInboxItemApi(sessionId, queue_id, text);
			// 失败不改本地文本，调用方据返回值提示（避免「以为保存了」）。
			if (!ok) {
				return false;
			}
			set(s => {
				const prev = s.inboxBySession[sessionId] ?? [];
				const next = prev.map(it =>
					it.queue_id === queue_id ? {...it, text} : it,
				);
				return {inboxBySession: {...s.inboxBySession, [sessionId]: next}};
			});
			return true;
		},
	};
}

// 便于类型检查的再导出
export type {InboxQueuedItem};
