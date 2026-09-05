/**
 * streamToolSettle.ts — tool-result settling helpers for a single streaming send,
 * extracted verbatim from streamSendSlice.createStreamSendSlice()
 * (scheduleWaitingToolSettle / applyLateToolResult). Behavior unchanged;
 * callers delegate to the returned controller.
 */
import type {StoreApi} from 'zustand';
import {dispatchXeyoUi} from '@/lib/dispatchXeyoUi';
import {
	replaceMessages,
} from '@/lib/db';
import {
	WAITING_TOOL_TIMEOUT_MS,
	clearWaitingToolTimer,
	settleOrphanRunningTools,
	waitingToolTimers,
} from './streamHelpers';
import {
	type ChatState,
} from './preStoreHelpers';
import type {
	TodoSnapshot,
} from '@/lib/toolActivity';
import type {
	ChatMessage,
} from '@/lib/types';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

export type ToolSettleController = {
	scheduleWaitingToolSettle: () => void;
	applyLateToolResult: (ev: {
		name: string;
		output: string;
		is_error: boolean;
		todos?: unknown;
		ui?: unknown;
		toolUseId?: string;
	}) => void;
};

export function createToolSettleController(deps: {
	get: GetState;
	set: SetState;
	sessionId: string;
	applyToolResult: (
		msgs: ChatMessage[],
		name: string,
		output: string,
		is_error: boolean,
		todos: unknown,
		sessionTodos: Record<string, TodoSnapshot | null>,
		written: string[],
		toolUseId?: string,
	) => {msgs: ChatMessage[]; sessionTodos: Record<string, TodoSnapshot | null>};
	persistNow: (msgs: ChatMessage[]) => void;
}): ToolSettleController {
	const {get, set, sessionId, applyToolResult, persistNow} = deps;

	const scheduleWaitingToolSettle = () => {
		clearWaitingToolTimer(sessionId);
		waitingToolTimers.set(
			sessionId,
			window.setTimeout(() => {
				waitingToolTimers.delete(sessionId);
				const cur = get();
				const raw = cur.messagesById[sessionId] ?? [];
				const hasWaiting = raw.some(
					m => m.role === 'tool' && m.toolStatus === 'waiting',
				);
				if (!hasWaiting) {
					return;
				}
				const settledMsgs = settleOrphanRunningTools(raw);
				if (!settledMsgs.changed) {
					return;
				}
				void replaceMessages(sessionId, settledMsgs.messages);
				set(s => ({
					messagesById: {
						...s.messagesById,
						[sessionId]: settledMsgs.messages,
					},
				}));
			}, WAITING_TOOL_TIMEOUT_MS),
		);
	};

	const applyLateToolResult = (ev: {
		name: string;
		output: string;
		is_error: boolean;
		todos?: unknown;
		ui?: unknown;
		toolUseId?: string;
	}) => {
		if (!get().sessions.some(s => s.id === sessionId)) {
			return;
		}
		clearWaitingToolTimer(sessionId);
		const written: string[] = [];
		const cur = get();
		const msgs = cur.messagesById[sessionId] ?? [];
		const next = applyToolResult(
			msgs,
			ev.name,
			ev.output,
			Boolean(ev.is_error),
			ev.todos,
			cur.sessionTodosById,
			written,
			ev.toolUseId,
		);
		dispatchXeyoUi(ev.ui, {
			toolUseId: ev.toolUseId,
			isError: Boolean(ev.is_error),
		});
		const stillWaiting = next.msgs.some(
			m => m.role === 'tool' && m.toolStatus === 'waiting',
		);
		if (stillWaiting) {
			scheduleWaitingToolSettle();
		}
		persistNow(next.msgs);
		set({
			messagesById: {...cur.messagesById, [sessionId]: next.msgs},
			sessionTodosById: next.sessionTodos,
		});
	};

	return {scheduleWaitingToolSettle, applyLateToolResult};
}
