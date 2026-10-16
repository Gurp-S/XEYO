import type {StoreApi} from 'zustand';
import {loadServerSessionMessages} from '@/lib/api';
import {patchSessionStream} from '@/lib/sessionStreams';
import {sessionErrorBannerPatch} from '@/lib/pendingForSession';
import type {ChatMessage} from '@/lib/types';
import type {ChatState} from './preStoreHelpers';
import {replaceMessages} from '@/lib/db';

type SetState = StoreApi<ChatState>['setState'];

function incomplete(set: SetState, sessionId: string, message: string) {
	set(state => ({
		sessionStreams: patchSessionStream(state.sessionStreams, sessionId, {
			isLoading: false, draining: false, remoteStreaming: false,
			abortRef: null, turnDetached: true, statusText: '完整回复尚未恢复',
		}),
		...sessionErrorBannerPatch(sessionId, message),
	}));
}

export async function finalizeFinishedTurn(
	set: SetState, sessionId: string, messages: ChatMessage[],
	note = '回合已结束（连接曾中断，已恢复最终内容）',
	isCurrent: () => boolean = () => true,
): Promise<boolean> {
	if (!isCurrent()) return false;
	try {
		await replaceMessages(sessionId, messages, isCurrent);
	} catch {
		if (isCurrent()) incomplete(set, sessionId, '完整回复尚未保存，本地历史已保留，可重新连接。');
		return false;
	}
	if (!isCurrent()) return false;
	set(state => ({
		messagesById: {...state.messagesById, [sessionId]: messages},
		sessionStreams: patchSessionStream(state.sessionStreams, sessionId, {
			isLoading: false, streamingText: '', streamingShown: '', statusText: note,
			abortRef: null, turnDetached: false, draining: false, remoteStreaming: false,
		}),
	}));
	return true;
}

/** A known gap must remain recoverable until the authoritative history arrives. */
export async function reconcileStreamGap(
	set: StoreApi<ChatState>['setState'], sessionId: string, backendId: string,
	isCurrent: () => boolean, finish: (messages: ChatMessage[]) => unknown,
): Promise<void> {
	try {
		const messages = await loadServerSessionMessages(backendId);
		if (!isCurrent()) return;
		if (messages.length) {
			await finish(messages);
			return;
		}
	} catch {
		// Transport adapters can throw; this has the same meaning as no receipt.
	}
	if (!isCurrent()) return;
	incomplete(set, sessionId, '回复存在缺段，完整记录暂未取回，可重新连接。');
}
