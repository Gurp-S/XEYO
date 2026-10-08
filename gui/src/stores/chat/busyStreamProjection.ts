import {createAssistantOutput} from './assistantOutput';
/**
 * Project an unexpectedly started stream from the busy-submit race into the
 * normal transcript and stream state. A 202 queue response never activates it.
 */
import type {StoreApi} from 'zustand';
import type {
	ToolCallStreamEvent,
	ToolProgressStreamEvent,
	ToolResultStreamEvent,
} from '@/lib/api';
import {dispatchXeyoUi} from '@/lib/dispatchXeyoUi';
import {patchMessages} from '@/lib/db';
import {formatToolInputForUi} from '@/lib/sanitizeToolInput';
import {parentDir} from '@/lib/paths';
import {setStreamingTextSignal, streamSignalsEnabled} from '@/lib/streamSignal';
import {patchSessionStream, type SessionStreamState} from '@/lib/sessionStreams';
import {filePathFromTool} from '@/lib/toolFilePath';
import {clearTodoDismissal} from '@/lib/todoDismissals';
import type {ChatMessage} from '@/lib/types';
import {uid} from '@/lib/utils';
import {
	appendAssistantProse,
	isTodoWriteName,
	markRunningToolsWaiting,
	settleOrphanRunningTools,
	snapshotFromTodoTool,
} from './streamHelpers';
import {sessionErrorBannerPatch} from '@/lib/pendingForSession';
import type {ChatState} from './preStoreHelpers';
import {activeBackendSessionId} from './preStoreHelpers';
import {createStreamOwnership} from './streamOwnership';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

function persist(
	set: SetState,
	sessionId: string,
	messages: ChatMessage[],
	isCurrent: () => boolean,
): void {
	if (messages.length === 0) return;
	void patchMessages(sessionId, messages, isCurrent).catch(err => {
		const detail = err instanceof Error ? err.message : String(err);
		set(sessionErrorBannerPatch(sessionId, `本地保存失败：${detail}`));
	});
}

export function createBusyStreamProjection(
	get: GetState,
	rawSet: SetState,
	sessionId: string,
	priorStream: SessionStreamState,
	anchorMessageId: string,
): {
	isCurrent: () => boolean;
	start: (abortRef: AbortController) => void;
	onDelta: (text: string, messageId?: string) => void;
	onReasoningDelta: (text: string) => void;
	onToolCall: (event: Omit<ToolCallStreamEvent, 'kind'>) => void;
	onToolResult: (event: Omit<ToolResultStreamEvent, 'kind'>) => void;
	onToolProgress: (event: Omit<ToolProgressStreamEvent, 'kind'>) => void;
	onDone: () => void;
	onError: () => void;
	onAbort: () => void;
	onConnectionLost: () => void;
} {
	let set = rawSet;
	let ownership: ReturnType<typeof createStreamOwnership> | undefined;
	const backendId = activeBackendSessionId(get().historyById, sessionId);
	const isCurrent = () => ownership?.isCurrent() ?? false;
	const assistantOutput = createAssistantOutput();
	let started = false;
	let prose = '';
	let reasoning = '';
	let thoughtStartedAt: number | null = null;
	let liveFrame = 0;

	const cancelLiveFrame = () => {
		if (liveFrame) {
			window.cancelAnimationFrame(liveFrame);
			liveFrame = 0;
		}
	};

	const flushLive = () => {
		cancelLiveFrame();
		if (!started || !isCurrent()) return;
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				streamingText: prose,
				streamingShown: prose,
				reasoningText: reasoning,
				thoughtStartedAt,
				...(prose || reasoning ? {statusText: ''} : {}),
			}),
		}));
		if (streamSignalsEnabled && get().activeId === sessionId) {
			setStreamingTextSignal(prose);
		}
	};

	const scheduleLive = () => {
		if (liveFrame) return;
		liveFrame = window.requestAnimationFrame(() => {
			liveFrame = 0;
			flushLive();
		});
	};

	const settleUnfinishedTools = (error = false) => {
		let written: ChatMessage[] = [];
		set(s => {
			const previous = s.messagesById[sessionId] ?? [];
			const settled = error
				? settleOrphanRunningTools(previous)
				: markRunningToolsWaiting(previous);
			if (!settled.changed) return {};
			written = settled.messages.filter((message, index) => message !== previous[index]);
			return {
				messagesById: {
					...s.messagesById,
					[sessionId]: settled.messages,
				},
			};
		});
		persist(set, sessionId, written, isCurrent);
	};

	const start = (abortRef: AbortController) => {
		ownership = createStreamOwnership(rawSet, get, sessionId, backendId);
		if (!ownership.isCurrent()) return;
		set = ownership.set;
		started = true;
		prose = '';
		reasoning = '';
		thoughtStartedAt = null;
		settleUnfinishedTools();
		// The stale local stream may still contain the previous turn's tail. The
		// server's 200 proves that turn is no longer busy, so settle that tail
		// immediately before the newly accepted user message.
		let priorTail: ChatMessage[] = [];
		set(s => {
			const current = s.messagesById[sessionId] ?? [];
			const anchor = current.findIndex(message => message.id === anchorMessageId);
			if (anchor < 0) return {};
			let before = current.slice(0, anchor);
			const appended: ChatMessage[] = [];
			const thought = priorStream.reasoningText.trim();
			if (thought) {
				const previousThought = before[before.length - 1];
				const thoughtMessage: ChatMessage =
					previousThought?.role === 'assistant' && previousThought.isThought
						? {
								...previousThought,
								text: thought,
								thoughtMs:
									priorStream.thoughtStartedAt != null
										? Date.now() - priorStream.thoughtStartedAt
										: previousThought.thoughtMs,
							}
						: {
								id: uid('thought'),
								role: 'assistant',
								text: thought,
								isThought: true,
								thoughtMs:
									priorStream.thoughtStartedAt != null
										? Date.now() - priorStream.thoughtStartedAt
										: undefined,
								createdAt: priorStream.thoughtStartedAt ?? Date.now(),
							};
				if (previousThought?.role === 'assistant' && previousThought.isThought) {
					before = [...before.slice(0, -1), thoughtMessage];
				} else {
					before = [...before, thoughtMessage];
				}
				appended.push(thoughtMessage);
			}
			if (priorStream.streamingText.trim()) {
				const withProse = appendAssistantProse(before, priorStream.streamingText);
				appended.push(...withProse.slice(before.length));
				before = withProse;
			}
			const next = [...before, ...current.slice(anchor)];
			priorTail = appended;
			return {messagesById: {...s.messagesById, [sessionId]: next}};
		});
		persist(set, sessionId, priorTail, isCurrent);
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				isLoading: true,
				streamingText: '',
				streamingShown: '',
				statusText: 'thinking…',
				reasoningText: '',
				thoughtStartedAt: null,
				abortRef,
				remoteStreaming: false,
				turnDetached: false,
				draining: false,
			}),
		}));
		if (streamSignalsEnabled && get().activeId === sessionId) {
			setStreamingTextSignal('');
		}
	};

	const appendMessage = (message: ChatMessage) => {
		set(s => ({
			messagesById: {
				...s.messagesById,
				[sessionId]: [...(s.messagesById[sessionId] ?? []), message],
			},
		}));
		persist(set, sessionId, [message], isCurrent);
	};

	const commitReasoning = () => {
		cancelLiveFrame();
		const text = reasoning.trim();
		const createdAt = thoughtStartedAt ?? Date.now();
		reasoning = '';
		thoughtStartedAt = null;
		if (text) {
			appendMessage({
				id: uid('thought'),
				role: 'assistant',
				text,
				isThought: true,
				createdAt,
			});
		}
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				reasoningText: '',
				thoughtStartedAt: null,
			}),
		}));
	};

	const commitProse = () => {
		cancelLiveFrame();
		const text = prose;
		prose = '';
		if (text.trim()) {
			let written: ChatMessage[] = [];
			set(s => {
				const previous = s.messagesById[sessionId] ?? [];
				const next = assistantOutput.append(previous, text);
				if (next === previous) return {};
				written = next.filter((message, index) => message !== previous[index]);
				return {
					messagesById: {
						...s.messagesById,
						[sessionId]: next,
					},
				};
			});
			persist(set, sessionId, written, isCurrent);
		}
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				streamingText: '',
				streamingShown: '',
			}),
		}));
		if (streamSignalsEnabled && get().activeId === sessionId) {
			setStreamingTextSignal('');
		}
	};

	const onDelta = (text: string, messageId?: string) => {
		assistantOutput.begin(messageId);
		if (!started || !isCurrent() || !text) return;
		prose += text;
		scheduleLive();
	};

	const onReasoningDelta = (text: string) => {
		if (!started || !isCurrent() || !text) return;
		thoughtStartedAt ??= Date.now();
		reasoning += text;
		scheduleLive();
	};

	const onToolCall = (event: Omit<ToolCallStreamEvent, 'kind'>) => {
		if (!started || !isCurrent()) return;
		commitReasoning();
		const segment = prose;
		commitProse();
		assistantOutput.finishSegment(segment);
		const toolInput = formatToolInputForUi(event.input);
		const toolMessage: ChatMessage = {
			id: uid('tool'),
			role: 'tool',
			toolName: event.name,
			toolUseId: event.toolUseId,
			toolInput,
			toolStatus: 'running',
			text: '',
			createdAt: Date.now(),
		};
		appendMessage(toolMessage);
		if (isTodoWriteName(event.name)) {
			try {
				clearTodoDismissal(sessionId);
				const snapshot = snapshotFromTodoTool({
					id: toolMessage.id,
					input: toolInput,
					running: true,
				});
				if (snapshot) {
					set(s => ({
						sessionTodosById: {
							...s.sessionTodosById,
							[sessionId]: snapshot,
						},
					}));
				}
			} catch (err) {
				console.warn('TodoWrite tool_call UI update failed:', err);
			}
		}
	};

	const onToolResult = (event: Omit<ToolResultStreamEvent, 'kind'>) => {
		if (!started || !isCurrent()) return;
		commitReasoning();
		commitProse();
		let written: ChatMessage | null = null;
		let toolId = uid('tool');
		let toolInput = '';
		set(s => {
			const previous = s.messagesById[sessionId] ?? [];
			let index = -1;
			if (event.toolUseId) {
				for (let i = previous.length - 1; i >= 0; i -= 1) {
					const message = previous[i]!;
					if (
						message.role === 'tool' &&
						message.toolUseId === event.toolUseId &&
						(message.toolStatus === 'running' || message.toolStatus === 'waiting')
					) {
						index = i;
						break;
					}
				}
			}
			if (index < 0) {
				for (let i = previous.length - 1; i >= 0; i -= 1) {
					const message = previous[i]!;
					if (
						message.role === 'tool' &&
						message.toolName === event.name &&
						(message.toolStatus === 'running' || message.toolStatus === 'waiting')
					) {
						index = i;
						break;
					}
				}
			}
			const isError = Boolean(event.is_error);
			const text = isError ? `[error]\n${event.output}` : event.output;
			const next = [...previous];
			if (index >= 0) {
				const old = next[index]!;
				toolId = old.id;
				toolInput = old.toolInput ?? '';
				written = {
					...old,
					text,
					toolStatus: isError ? 'error' : 'done',
					...(event.toolUseId && !old.toolUseId
						? {toolUseId: event.toolUseId}
						: {}),
				};
				next[index] = written;
			} else {
				written = {
					id: uid('tool'),
					role: 'tool',
					toolName: event.name,
					toolUseId: event.toolUseId,
					toolInput: '',
					toolStatus: isError ? 'error' : 'done',
					text,
					createdAt: Date.now(),
				};
				toolId = written.id;
				next.push(written);
			}
			return {
				messagesById: {...s.messagesById, [sessionId]: next},
			};
		});
		if (written) persist(set, sessionId, [written], isCurrent);
		dispatchXeyoUi(event.ui, {
			toolUseId: event.toolUseId,
			isError: Boolean(event.is_error),
		});
		if (!event.is_error) {
			const path = filePathFromTool(event.name, toolInput);
			if (path) {
				void import('@/stores/explorerStore')
					.then(({useExplorerStore}) => {
						void useExplorerStore.getState().reloadIfOpen(path);
						void useExplorerStore.getState().invalidateDir(parentDir(path));
					})
					.catch(() => undefined);
			}
		}
		if (isTodoWriteName(event.name) && !event.is_error) {
			try {
				clearTodoDismissal(sessionId);
				const snapshot = snapshotFromTodoTool({
					id: toolId,
					input: toolInput,
					result: event.output,
					todos: event.todos,
					running: false,
				});
				set(s => ({
					sessionTodosById: {
						...s.sessionTodosById,
						[sessionId]: snapshot && snapshot.todos.length > 0 ? snapshot : null,
					},
				}));
			} catch (err) {
				console.warn('TodoWrite tool_result UI update failed:', err);
			}
		}
	};

	const finish = (statusText: string, error = false) => {
		if (!started || !isCurrent()) return;
		commitReasoning();
		commitProse();
		settleUnfinishedTools(error);
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				isLoading: false,
				streamingText: '',
				streamingShown: '',
				statusText,
				reasoningText: '',
				thoughtStartedAt: null,
				abortRef: null,
				remoteStreaming: false,
				turnDetached: false,
				draining: false,
			}),
		}));
		if (streamSignalsEnabled && get().activeId === sessionId) {
			setStreamingTextSignal('');
		}
		started = false;
	};

	const onToolProgress = (event: Omit<ToolProgressStreamEvent, 'kind'>) => {
		if (!started || !isCurrent()) return;
		const detail = (event.message || '').trim();
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				statusText: detail ? `${event.name} · ${detail}` : event.name,
			}),
		}));
	};

	const onConnectionLost = () => {
		if (!started || !isCurrent()) return;
		commitReasoning();
		commitProse();
		settleUnfinishedTools();
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				isLoading: true,
				statusText: '连接中断，正在恢复…',
				abortRef: null,
				turnDetached: true,
			}),
		}));
	};

	const onAbort = () => {
		cancelLiveFrame();
		started = false;
	};

	return {
		isCurrent,
		start,
		onDelta,
		onReasoningDelta,
		onToolCall,
		onToolResult,
		onToolProgress,
		onDone: () => finish(''),
		onError: () => finish('', true),
		onAbort,
		onConnectionLost,
	};
}
