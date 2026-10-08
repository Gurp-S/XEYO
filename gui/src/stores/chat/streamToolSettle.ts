/**
 * streamToolSettle.ts — 单次流式发送的工具结果落定辅助逻辑，自
 * streamSendSlice.createStreamSendSlice() 原样拆出
 * (scheduleWaitingToolSettle / applyLateToolResult)。行为不变；
 * 调用方委托给返回的 controller。
 */
import type {StoreApi} from 'zustand';
import {settleStoppedTools} from './stoppedTools';
import {dispatchXeyoUi} from '@/lib/dispatchXeyoUi';
import {
	replaceMessages,
} from '@/lib/db';
import {
	WAITING_TOOL_TIMEOUT_MS,
	clearWaitingToolTimer,
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
	isCurrent?: () => boolean;
}): ToolSettleController {
	const {get, set, sessionId, applyToolResult, persistNow} = deps;
	const isCurrent = deps.isCurrent ?? (() => true);

	const scheduleWaitingToolSettle = () => {
		if (!isCurrent()) return;
		clearWaitingToolTimer(sessionId);
		const stoppedIds = new Set((get().messagesById[sessionId] ?? [])
			.filter(message => message.role === 'tool' && message.toolStatus === 'waiting').map(message => message.id));
		const timer = window.setTimeout(() => {
			if (waitingToolTimers.get(sessionId) !== timer) return;
			waitingToolTimers.delete(sessionId);
			if (!isCurrent()) return;
			const cur = get();
			const settledMsgs = settleStoppedTools(cur.messagesById[sessionId] ?? [], stoppedIds);
			if (!settledMsgs.changed) return;
			void replaceMessages(sessionId, settledMsgs.messages, isCurrent);
			set(s => ({messagesById: {...s.messagesById, [sessionId]: settledMsgs.messages}}));
		}, WAITING_TOOL_TIMEOUT_MS);
		waitingToolTimers.set(sessionId, timer);
	};

	const applyLateToolResult = (ev: {
		name: string;
		output: string;
		is_error: boolean;
		todos?: unknown;
		ui?: unknown;
		toolUseId?: string;
	}) => {
		if (!isCurrent() || !get().sessions.some(s => s.id === sessionId)) {
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
