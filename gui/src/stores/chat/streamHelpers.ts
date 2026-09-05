/**
 * streamHelpers.ts — stream / tool / thought / todo helper functions.
 * Extracted verbatim from preStoreHelpers.ts (auto-dismantle). Behavior unchanged.
 */
import {
	syncUiThoughtsToServer,
} from '@/lib/api';
import {
	collectSyncableThoughts,
} from '@/lib/mergeTranscript';
import type {
	SessionStreamState,
} from '@/lib/sessionStreams';
import {
	parseTodosFromInput,
	parseTodosFromResult,
	type TodoItemView,
	type TodoSnapshot,
} from '@/lib/toolActivity';
import type {
	ChatMessage,
} from '@/lib/types';
import {
	uid,
} from '@/lib/utils';

const INTERRUPTED_TOOL_MSG = 'interrupted (stream ended without tool result)';

/**
 * smoke-test #15：以服务端 transcript 对账工具卡。
 * 用户 stop/断流时 SSE 已 abort,引擎在 abort 收尾里把未决工具以真实结果
 * （或 "aborted" 标注）写入服务端 transcript,但客户端收不到事件——本地
 * waiting/running 卡只能猜 error。这里按 toolUseId 用服务端结果覆盖本地。
 */
export function settleToolsFromServer(
	local: ChatMessage[],
	server: ChatMessage[],
): {changed: boolean; messages: ChatMessage[]} {
	const needs = local.some(
		m =>
			m.role === 'tool' &&
			(m.toolStatus === 'running' || m.toolStatus === 'waiting') &&
			m.toolUseId,
	);
	if (!needs) {
		return {changed: false, messages: local};
	}
	const byId = new Map<string, ChatMessage>();
	for (const s of server) {
		if (s.role === 'tool' && s.toolUseId) {
			byId.set(s.toolUseId, s);
		}
	}
	let changed = false;
	const messages = local.map(m => {
		if (
			m.role !== 'tool' ||
			!(m.toolStatus === 'running' || m.toolStatus === 'waiting') ||
			!m.toolUseId
		) {
			return m;
		}
		const real = byId.get(m.toolUseId);
		if (
			!real ||
			real.toolStatus === 'running' ||
			real.toolStatus === 'waiting'
		) {
			return m;
		}
		changed = true;
		return {
			...m,
			text: real.text || m.text,
			toolStatus: real.toolStatus ?? 'done',
		};
	});
	return {changed, messages};
}

/**
 * smoke-test #1：回合结束不再无条件清空 todo 面板——仍有未完成项时保留快照
 * （面板在 Dock 上继续显示,后续 TodoWrite 继续追加/更新）。
 */
export function todosWithUnfinished(
	snap: TodoSnapshot | null | undefined,
): TodoSnapshot | null {
	if (snap && snap.todos.some(t => t.status !== 'completed')) {
		return snap;
	}
	return null;
}

function parseTodoRowsLoose(raw: unknown): TodoItemView[] {
	if (!Array.isArray(raw)) {
		return [];
	}
	const out: TodoItemView[] = [];
	for (const row of raw) {
		if (!row || typeof row !== 'object' || Array.isArray(row)) {
			continue;
		}
		const r = row as Record<string, unknown>;
		const content = typeof r.content === 'string' ? r.content.trim() : '';
		const status = r.status;
		const activeForm =
			(typeof r.activeForm === 'string' && r.activeForm.trim()) ||
			(typeof r.active_form === 'string' && r.active_form.trim()) ||
			content;
		if (
			!content ||
			(status !== 'pending' &&
				status !== 'in_progress' &&
				status !== 'completed')
		) {
			continue;
		}
		out.push({content, status, activeForm});
	}
	return out;
}

/**
 * 活跃 agent 轮次的 dock 快照。
 * 优先 SSE `todos`，其次 <todo_list> 标签，再 tool input。
 * 空 → null。全部完成仍显示直到流结束。
 */
function snapshotFromTodoTool(opts: {
	id: string;
	input: string;
	result?: string;
	todos?: unknown;
	running: boolean;
}): TodoSnapshot | null {
	let rows: TodoItemView[] = [];
	if (opts.todos !== undefined) {
		rows = parseTodoRowsLoose(opts.todos);
	} else if (opts.result?.trim() && !opts.running) {
		const fromResult = parseTodosFromResult(opts.result);
		rows =
			fromResult !== null ? fromResult : parseTodosFromInput(opts.input);
	} else {
		rows = parseTodosFromInput(opts.input);
	}
	if (rows.length === 0) {
		return null;
	}
	return {id: opts.id, todos: rows, running: opts.running};
}

/**
 * 崩溃 / HMR / 等待超时：把仍 running/waiting 且无结果的 tool 行标为 interrupted。
 * 这会导致 Activity "xy-thinking" shimmer 在重启后永远闪烁。
 */
function settleOrphanRunningTools(messages: ChatMessage[]): {
	messages: ChatMessage[];
	changed: boolean;
} {
	let changed = false;
	const next = messages.map(m => {
		if (m.role !== 'tool') {
			return m;
		}
		const legacyCall =
			!m.toolStatus && m.text.startsWith('call ') && !m.toolInput;
		const unsettled =
			m.toolStatus === 'running' || m.toolStatus === 'waiting';
		if (!unsettled && !legacyCall) {
			return m;
		}
		changed = true;
		const body = m.text.startsWith('call ') ? '' : m.text.trim();
		if (body) {
			return {
				...m,
				toolStatus: (body.startsWith('[error]')
					? 'error'
					: 'done') as ChatMessage['toolStatus'],
			};
		}
		return {
			...m,
			toolStatus: 'error' as const,
			text: `[error]\n${INTERRUPTED_TOOL_MSG}`,
		};
	});
	return {messages: next, changed};
}

/** 流正常结束但仍有 running 工具：标 waiting，等晚到 result 或超时再定胜负。 */
function markRunningToolsWaiting(messages: ChatMessage[]): {
	messages: ChatMessage[];
	changed: boolean;
} {
	let changed = false;
	const next = messages.map(m => {
		if (m.role !== 'tool' || m.toolStatus !== 'running') {
			return m;
		}
		const body = m.text.startsWith('call ') ? '' : m.text.trim();
		if (body) {
			changed = true;
			return {
				...m,
				toolStatus: (body.startsWith('[error]')
					? 'error'
					: 'done') as ChatMessage['toolStatus'],
			};
		}
		changed = true;
		return {...m, toolStatus: 'waiting' as const};
	});
	return {messages: next, changed};
}

/** clearStream 的 patch 可能早于最后一次 flush；用 store 里已落定的 tool 行覆盖。 */
function overlaySettledTools(
	patchMsgs: ChatMessage[],
	storeMsgs: ChatMessage[],
): ChatMessage[] {
	const storeById = new Map(storeMsgs.map(m => [m.id, m]));
	return patchMsgs.map(m => {
		if (m.role !== 'tool') {
			return m;
		}
		const s = storeById.get(m.id);
		if (!s || s.role !== 'tool') {
			return m;
		}
		const patchBody = m.text.startsWith('call ') ? '' : m.text.trim();
		const storeBody = s.text.startsWith('call ') ? '' : s.text.trim();
		if (
			!patchBody &&
			storeBody &&
			(s.toolStatus === 'done' || s.toolStatus === 'error')
		) {
			return s;
		}
		return m;
	});
}

/** 丢弃曾使 transcript 看起来损坏的一次性 FE 崩溃横幅。 */
function scrubStaleUiCrashBanners(messages: ChatMessage[]): {
	messages: ChatMessage[];
	changed: boolean;
} {
	const next = messages.filter(
		m =>
			!(
				m.role === 'system' &&
				/liveTodosOrNull is not defined/i.test(m.text)
			),
	);
	return {messages: next, changed: next.length !== messages.length};
}

function recoverSessionMessages(messages: ChatMessage[]): {
	messages: ChatMessage[];
	changed: boolean;
} {
	const settled = settleOrphanRunningTools(messages);
	const scrubbed = scrubStaleUiCrashBanners(settled.messages);
	return {
		messages: scrubbed.messages,
		changed: settled.changed || scrubbed.changed,
	};
}

function countToolMessages(messages: ChatMessage[]): number {
	return messages.filter(m => m.role === 'tool').length;
}

const thoughtSyncTimers = new Map<string, number>();
const THOUGHT_SYNC_DEBOUNCE_MS = 800;
/** 流结束后仍 waiting 的工具：等晚到 result；超时后标 interrupted。略长于默认工具超时。 */
const waitingToolTimers = new Map<string, number>();
const WAITING_TOOL_TIMEOUT_MS = 320_000;

function clearWaitingToolTimer(sessionId: string): void {
	const t = waitingToolTimers.get(sessionId);
	if (t) {
		window.clearTimeout(t);
		waitingToolTimers.delete(sessionId);
	}
}

function scheduleThoughtSync(backendSessionId: string, msgs: ChatMessage[]): void {
	const thoughts = collectSyncableThoughts(msgs);
	if (thoughts.length === 0) {
		return;
	}
	const existing = thoughtSyncTimers.get(backendSessionId);
	if (existing) {
		window.clearTimeout(existing);
	}
	const timer = window.setTimeout(() => {
		thoughtSyncTimers.delete(backendSessionId);
		void syncUiThoughtsToServer(backendSessionId, thoughts).catch(() => {});
	}, THOUGHT_SYNC_DEBOUNCE_MS);
	thoughtSyncTimers.set(backendSessionId, timer);
}

function flushThoughtSync(backendSessionId: string, msgs: ChatMessage[]): void {
	const existing = thoughtSyncTimers.get(backendSessionId);
	if (existing) {
		window.clearTimeout(existing);
		thoughtSyncTimers.delete(backendSessionId);
	}
	const thoughts = collectSyncableThoughts(msgs);
	if (thoughts.length === 0) {
		return;
	}
	void syncUiThoughtsToServer(backendSessionId, thoughts).catch(() => {});
}

function shouldPreferServerMessages(
	local: ChatMessage[],
	server: ChatMessage[],
): boolean {
	if (local.length === 0 && server.length > 0) {
		return true;
	}
	const localTools = countToolMessages(local);
	const serverTools = countToolMessages(server);
	if (serverTools > localTools) {
		return true;
	}
	return server.length > local.length && serverTools >= localTools;
}

/** 流已失活但 streamingText 仍在时，把尾巴落进 messages（防 recover/clear 静默丢摘要）。 */
function flushOrphanStreamingTail(
	messagesById: Record<string, ChatMessage[]>,
	sessionId: string,
	stream: SessionStreamState,
): {messagesById: Record<string, ChatMessage[]>; changed: boolean} {
	const tail = stream.streamingText.trim();
	if (!tail) {
		return {messagesById, changed: false};
	}
	const prev = messagesById[sessionId] ?? [];
	const next = appendAssistantProse(prev, tail);
	if (next === prev) {
		return {messagesById, changed: false};
	}
	return {
		messagesById: {...messagesById, [sessionId]: next},
		changed: true,
	};
}

function appendAssistantProse(
	msgs: ChatMessage[],
	text: string,
): ChatMessage[] {
	const trimmed = text.trim();
	if (!trimmed) {
		return msgs;
	}
	const last = msgs[msgs.length - 1];
	if (
		last?.role === 'assistant' &&
		!last.isThought &&
		last.text.trim() === trimmed
	) {
		return msgs;
	}
	return [
		...msgs,
		{
			id: uid('msg'),
			role: 'assistant',
			text: trimmed,
			createdAt: Date.now(),
		},
	];
}

function titleFromText(text: string): string {
	const t = text.trim().replace(/\s+/g, ' ');
	return t.length > 24 ? `${t.slice(0, 24)}…` : t || '新对话';
}

function isTodoWriteName(name: string): boolean {
	return name.toLowerCase().includes('todo');
}

const DRAIN_MIN_BACKLOG = 64;

export {
	DRAIN_MIN_BACKLOG,
	INTERRUPTED_TOOL_MSG,
	THOUGHT_SYNC_DEBOUNCE_MS,
	WAITING_TOOL_TIMEOUT_MS,
	appendAssistantProse,
	clearWaitingToolTimer,
	countToolMessages,
	flushOrphanStreamingTail,
	flushThoughtSync,
	isTodoWriteName,
	markRunningToolsWaiting,
	overlaySettledTools,
	parseTodoRowsLoose,
	recoverSessionMessages,
	scheduleThoughtSync,
	scrubStaleUiCrashBanners,
	settleOrphanRunningTools,
	shouldPreferServerMessages,
	snapshotFromTodoTool,
	thoughtSyncTimers,
	titleFromText,
	waitingToolTimers,
};
