/**
 * streamSendSlice.ts — 流式发送 slice。
 * sendMessage / stopGeneration / sendToSession 在此实现。恢复与重新挂载
 * 方法已拆分到 streamRecoverySlice.ts（在下方展开），单次发送的外围逻辑
 * （持久化 / 用量 / 收尾排水 / 多 agent 分发 / 待处理分发）分别移入
 * streamPersistence.ts、usageAccumulator.ts、streamDrain.ts、
 * multiAgentSlice.ts 与 uiChromeSlice.ts。行为不变。
 */
import type {StoreApi} from 'zustand';
import {
	interruptChat,
	streamChat,
} from '@/lib/api';
import {normalizeSessionGoalState} from '@/lib/api/goals';
import {normalizeJobSnapshots} from '@/lib/api/jobs';
import {dispatchXeyoUi} from '@/lib/dispatchXeyoUi';
import {allowsEmptyApiKey} from '@/lib/localTestGate';
import {toast} from '@/lib/toast';
import {
	replaceMessages,
	saveSession,
} from '@/lib/db';
import {
	type AgentMode,
} from '@/lib/agentMode';
import {
	sessionErrorBannerPatch,
} from '@/lib/pendingForSession';
import {
	clearTodoDismissal,
} from '@/lib/todoDismissals';
import {
	formatToolInputForUi,
} from '@/lib/sanitizeToolInput';
import {
	type TodoSnapshot,
} from '@/lib/toolActivity';
import {
	type ChatMessage,
} from '@/lib/types';
import {
	uid,
} from '@/lib/utils';
import {parentDir} from '@/lib/paths';
import {
	toApiMessages,
} from '@/lib/toApiMessages';
import {
	markThoughtFinalized,
	markThoughtStreaming,
} from '@/lib/mergeTranscript';
import {
	filePathFromTool,
} from '@/lib/toolFilePath';
import {
	advanceTypewriterShown,
	isOnlyHoldBackLag,
	streamTypewriterStepFor,
	type TypewriterAdvanceCache,
} from '@/hooks/useStreamTypewriter';
import {
	streamNeedsFastTypewriter,
} from '@/lib/streamMarkdown';
import {
	isSmoothnessOn,
	useSettingsStore,
} from '@/stores/settingsStore';
import {
	setStreamingTextSignal,
	streamSignalsEnabled,
} from '@/lib/streamSignal';
import {
	getSessionStream,
	patchSessionStream,
	sessionStreamActive,
	sessionStreamBusy,
	isSessionStreamLive,
} from '@/lib/sessionStreams';
import {
	activeBackendSessionId,
	clearSessionStreamState,
	commitDrainForSession,
	syncWorkspaceRoot,
	type ChatState,
} from './preStoreHelpers';
import {
	DRAIN_MIN_BACKLOG,
	appendAssistantProse,
	clearWaitingToolTimer,
	flushThoughtSync,
	isTodoWriteName,
	markRunningToolsWaiting,
	overlaySettledTools,
	settleOrphanRunningTools,
	snapshotFromTodoTool,
	titleFromText,
	todosWithUnfinished,
} from './streamHelpers';
import {createStreamRecoverySlice, recoverAfterDisconnect} from './streamRecoverySlice';
import {createStreamPersistence} from './streamPersistence';
import {createUsageAccumulator} from './usageAccumulator';
import {createStreamDrain} from './streamDrain';
import {createToolSettleController} from './streamToolSettle';
import {createMultiAgentStreamHandlers} from './multiAgentSlice';
import {createPendingStreamHandlers} from './uiChromeSlice';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

const SLICE_KEYS = [
	'sendMessage',
	'sendToSession',
	'stopGeneration',
	'recoverStuckStream',
	'reattachActiveStreams',
	'reattachStream',
	'continueRecovery',
	'abandonRecovery',
] as const;

export function createStreamSendSlice(
	set: SetState,
	get: GetState,
): Pick<ChatState, (typeof SLICE_KEYS)[number]> {
	return {
	...createStreamRecoverySlice(set, get),

		async sendMessage(
			text,
			mediaRefs,
			_mediaPreviewUrls = [],
			requestedAgentMode: AgentMode = 'agent',
			onAccepted?: () => void,
			requestedMultiAgent: boolean = false,
			opts?: {
				sessionId?: string;
				background?: boolean;
				/** 会话输入框手动选的思考等级；优先级最高。 */
				reasoningEffort?: string;
			},
		) {
		const background = Boolean(opts?.background && opts.sessionId);
		const trimmed =
			text.trim() || (mediaRefs?.length ? '请分析这些图片。' : '');
		if (!trimmed) {
			return false;
		}
		// 新发送覆盖旧 Ask 面板（例如用户打「继续」续跑时不应再挂着确认框）。
		// 后台跨会话发送不碰当前会话的 pendingAsk。
		if (!background) {
			get().setPendingAsk?.(null);
		}
		set(sessionErrorBannerPatch(null, null));

		const settings = useSettingsStore.getState();
		// 空 Key 仅允许本地测试 provider（localTestGate，T25c）。
		if (!settings.apiKey.trim() && !allowsEmptyApiKey(settings.provider)) {
			settings.openSettings();
			set(
				sessionErrorBannerPatch(
					null,
					'请先在设置中填写 API Key，然后再发送消息。',
				),
			);
			return false;
		}

		let sessionId = opts?.sessionId?.trim() || get().activeId;
		if (
			!sessionId ||
			!get().sessions.some(s => s.id === sessionId)
		) {
			if (background) {
				toast.error('目标对话不存在');
				return false;
			}
			sessionId = await get().createSession();
		}

		commitDrainForSession(sessionId);

		const preSend = get();
		const preStream = getSessionStream(preSend, sessionId);
		// P1：忙碌判定要覆盖远程/分离回合（remoteStreaming / turnDetached / draining）——
		// sessionStreamActive 只含 isLoading||draining，漏了远程流会误判「空闲」而直发。
		const active =
			sessionStreamActive(preSend, sessionId) ||
			preStream.remoteStreaming ||
			preStream.turnDetached;
		if (active) {
			const live = isSessionStreamLive(preStream);
			if (live) {
				// P1：回合真正在跑——走**排队**路径，绝不进入下方 line 776 的
				// sessionStreams 重置（否则会清掉运行中流的 streamingText/abortRef）。
				// 乐观气泡照常落地；POST 返回 202 → onQueued 记入 inboxBySession（chip）。
				console.info('[inbox] busy 检测到，尝试排队…', {sessionId});
				const qUserMsg: ChatMessage = {
					id: uid('msg'),
					role: 'user',
					text: trimmed,
					...(mediaRefs?.length ? {mediaRefs: [...mediaRefs]} : {}),
					createdAt: Date.now(),
				};
				const qNext = [...(get().messagesById[sessionId] ?? []), qUserMsg];
				set(s => ({
					messagesById: {...s.messagesById, [sessionId]: qNext},
					...sessionErrorBannerPatch(null, null),
				}));
				const qApi = toApiMessages(qNext);
				const qBackend = activeBackendSessionId(get().historyById, sessionId);
				let queuedProse = '';
				const queueHandlers = {
					// 竞态防御：live 判定为 true 但后端实际未排队、直接开跑时（SSE 200 而非
					// 202），onDelta/onDone 不能空置（否则回复被吞、用户看到「无 chip 无回复」）。
					// 用闭包累积文本，onDone 时用 appendAssistantProse 把 assistant 回复落地。
					onDelta(text: string) {
						queuedProse += text;
					},
					onDone() {
						if (queuedProse.trim()) {
							const prevMsgs = get().messagesById[sessionId] ?? [];
							set(s => ({
								messagesById: {
									...s.messagesById,
									[sessionId]: appendAssistantProse(prevMsgs, queuedProse),
								},
							}));
						}
					},
					onError(message: string) {
						// 排队失败（后端不支持 / 其它拒绝）：撤回乐观气泡 + 提示。
						const kept = (get().messagesById[sessionId] ?? []).filter(
							m => m.id !== qUserMsg.id,
						);
						set(s => ({
							messagesById: {...s.messagesById, [sessionId]: kept},
							...sessionErrorBannerPatch(sessionId, message),
						}));
					},
					onQueued({queueId, position}: {queueId: string; position: number}) {
						console.info('[inbox] 已排队', {sessionId, queueId, position});
						toast.info(`已排队（第 ${position} 条），当前回合结束后自动投递`);
						set(s => {
							const prev = s.inboxBySession[sessionId] ?? [];
							return {
								inboxBySession: {
									...s.inboxBySession,
									[sessionId]: [
										...prev,
										{
											queue_id: queueId,
											text: qUserMsg.text,
											media_refs: qUserMsg.mediaRefs ?? [],
											message_id: qUserMsg.id ?? null,
											queued_at: Date.now(),
											attempts: 0,
											state: 'queued' as const,
											position,
										},
									],
								},
								hasInboxChip: true,
							};
						});
					},
				};
				await streamChat(qBackend, qApi, queueHandlers);
				// 返回 true：Composer 据以清空输入框（消息已入队）。
				return true;
			}
			// 残留的僵尸流：清状态，不再拦截。
			set(s => ({
				sessionStreams: clearSessionStreamState(s.sessionStreams, sessionId),
			}));
		}
		const backendSessionId = activeBackendSessionId(
			get().historyById,
			sessionId,
		);

		const now = Date.now();
		const userMsg: ChatMessage = {
			id: uid('msg'),
			role: 'user',
			text: trimmed,
			...(mediaRefs?.length ? {mediaRefs: [...mediaRefs]} : {}),
			createdAt: now,
		};

		const prev = get().messagesById[sessionId] ?? [];
		const nextMessages = [...prev, userMsg];
		const sessions = get().sessions.map(s =>
			s.id === sessionId
				? {
						...s,
						title:
							s.title === '新会话' || s.title === '新对话'
								? titleFromText(trimmed)
								: s.title,
						updatedAt: now,
					}
				: s,
		);
		const session = sessions.find(s => s.id === sessionId);
		if (!session) {
			return false;
		}

		// 侧聊（side-）不绑定工作区：读工具用服务端启动目录，跳过工作区守卫。
		const sideSession = sessionId.startsWith('side-');
		const sendSpace = get().spaces.find(s => s.id === session.spaceId);
		const workspaceRoot = sideSession
			? ''
			: (sendSpace?.rootPath?.trim() ?? '');
		if (!sideSession && !workspaceRoot) {
			set(
				sessionErrorBannerPatch(
					sessionId,
					'请先打开一个项目文件夹，再发送消息。',
				),
			);
			return false;
		}
		if (!sideSession) {
			const workspaceBound = await syncWorkspaceRoot(workspaceRoot);
			if (!workspaceBound) {
				set(
					sessionErrorBannerPatch(
						sessionId,
						'无法绑定工作区。请重新打开文件夹后再试。',
					),
				);
				return false;
			}
		}

		const abort = new AbortController();
		let settled = false;
		const smoothStream = () =>
			isSmoothnessOn(useSettingsStore.getState().smoothness);
		/** token + tool 共用一条 rAF 队列；每帧最多一次 Zustand set。 */
		let pendingDelta = '';
		let pendingReasoning = '';
		type PendingTool =
			| {kind: 'call'; name: string; input: unknown; toolUseId?: string}
			| {
					kind: 'result';
					name: string;
					output: string;
					is_error: boolean;
					todos?: unknown;
					ui?: unknown;
					toolUseId?: string;
			  };
		let pendingTools: PendingTool[] = [];
		let frameRaf = 0;
		const typewriterCache: TypewriterAdvanceCache = {
			full: '',
			points: [],
			shown: '',
			index: 0,
		};

		// 每次发送的外围控制器（从本 slice 拆出）。
		const persistence = createStreamPersistence({
			get,
			sessionId,
			backendSessionId,
			smoothStream,
			seedMessages: nextMessages,
		});
		const usage = createUsageAccumulator(get, set, sessionId);
		const multi = createMultiAgentStreamHandlers({get, set, sessionId});
		const pending = createPendingStreamHandlers({get, sessionId});

		const formatToolInput = (input: unknown): string =>
			formatToolInputForUi(input);

		const applyToolCall = (
			msgs: ChatMessage[],
			streamingText: string,
			name: string,
			input: unknown,
			sessionTodos: Record<string, TodoSnapshot | null>,
			meta?: {
				reasoningBefore?: string;
				thoughtMs?: number;
				toolUseId?: string;
			},
		): {
			msgs: ChatMessage[];
			streamingText: string;
			sessionTodos: Record<string, TodoSnapshot | null>;
		} => {
			let nextMsgs = msgs;
			let nextText = streamingText;
			if (nextText) {
				nextMsgs = [
					...nextMsgs,
					{
						id: uid('msg'),
						role: 'assistant',
						text: nextText,
						createdAt: Date.now(),
					},
				];
				nextText = '';
			} else {
				nextMsgs = [...nextMsgs];
			}
			const toolId = uid('tool');
			const toolInput = formatToolInput(input);
			nextMsgs.push({
				id: toolId,
				role: 'tool',
				toolName: name,
				toolInput,
				toolStatus: 'running',
				...(meta?.toolUseId ? {toolUseId: meta.toolUseId} : {}),
				text: '',
				reasoningBefore: meta?.reasoningBefore,
				thoughtMs: meta?.thoughtMs,
				createdAt: Date.now(),
			});
			let nextTodos = sessionTodos;
			if (isTodoWriteName(name)) {
				try {
					clearTodoDismissal(sessionId);
					const snap = snapshotFromTodoTool({
						id: toolId,
						input: toolInput,
						running: true,
					});
					if (snap) {
						nextTodos = {...sessionTodos, [sessionId]: snap};
					}
				} catch (err) {
					console.warn('TodoWrite tool_call UI update failed:', err);
				}
			}
			return {msgs: nextMsgs, streamingText: nextText, sessionTodos: nextTodos};
		};

		const findToolResultIndex = (
			msgs: ChatMessage[],
			name: string,
			toolUseId?: string,
		): number => {
			if (toolUseId) {
				for (let i = msgs.length - 1; i >= 0; i -= 1) {
					const m = msgs[i]!;
					if (
						m.role === 'tool' &&
						m.toolUseId === toolUseId &&
						(m.toolStatus === 'running' || m.toolStatus === 'waiting')
					) {
						return i;
					}
				}
				// 已有同 id 行但已 settle：仍更新该行（晚到覆盖），不开新行。
				for (let i = msgs.length - 1; i >= 0; i -= 1) {
					const m = msgs[i]!;
					if (m.role === 'tool' && m.toolUseId === toolUseId) {
						return i;
					}
				}
			}
			for (let i = msgs.length - 1; i >= 0; i -= 1) {
				const m = msgs[i]!;
				if (
					m.role === 'tool' &&
					m.toolName === name &&
					(m.toolStatus === 'running' || m.toolStatus === 'waiting')
				) {
					return i;
				}
			}
			return -1;
		};

		const applyToolResult = (
			msgs: ChatMessage[],
			name: string,
			output: string,
			is_error: boolean,
			todos: unknown,
			sessionTodos: Record<string, TodoSnapshot | null>,
			written: string[],
			toolUseId?: string,
		): {
			msgs: ChatMessage[];
			sessionTodos: Record<string, TodoSnapshot | null>;
		} => {
			const nextMsgs = [...msgs];
			const idx = findToolResultIndex(nextMsgs, name, toolUseId);
			const body = is_error ? `[error]\n${output}` : output;
			let toolId = uid('tool');
			let toolInput = '';
			if (idx >= 0) {
				const prev = nextMsgs[idx]!;
				toolId = prev.id;
				toolInput = prev.toolInput ?? '';
				nextMsgs[idx] = {
					...prev,
					text: body,
					toolStatus: is_error ? 'error' : 'done',
					...(toolUseId && !prev.toolUseId ? {toolUseId} : {}),
				};
			} else {
				nextMsgs.push({
					id: toolId,
					role: 'tool',
					toolName: name,
					toolInput: '',
					toolStatus: is_error ? 'error' : 'done',
					...(toolUseId ? {toolUseId} : {}),
					text: body,
					createdAt: Date.now(),
				});
			}
			let nextTodos = sessionTodos;
			if (isTodoWriteName(name) && !is_error) {
				try {
					clearTodoDismissal(sessionId);
					const snap = snapshotFromTodoTool({
						id: toolId,
						input: toolInput,
						result: output,
						todos,
						running: false,
					});
					nextTodos = {
						...sessionTodos,
						[sessionId]: snap && snap.todos.length > 0 ? snap : null,
					};
				} catch (err) {
					console.warn('TodoWrite tool_result UI update failed:', err);
				}
			}
			if (!is_error) {
				const path = filePathFromTool(name, toolInput);
				if (path) {
					written.push(path);
				}
			}
			return {msgs: nextMsgs, sessionTodos: nextTodos};
		};

		// settled 后晚到的 tool_result：只更新对应 tool 行，不开新流。
		const toolSettle = createToolSettleController({
			get,
			set,
			sessionId,
			applyToolResult,
			persistNow: persistence.now,
		});

		const streamingThoughtId = (sid: string, seg: number) =>
			`thought-${sid}-${seg}`;

		/** 当前流式 Thought 段；finalize 后置空，下一段重新分配，id 在段内保持稳定。 */
		let activeThoughtSeg = 0;
		let activeThoughtId: string | null = null;

		const ensureActiveThoughtId = (sid: string): string => {
			if (!activeThoughtId) {
				activeThoughtSeg += 1;
				activeThoughtId = streamingThoughtId(sid, activeThoughtSeg);
				markThoughtStreaming(activeThoughtId);
			}
			return activeThoughtId;
		};

		const dropActiveThoughtMark = () => {
			if (activeThoughtId) {
				markThoughtFinalized(activeThoughtId);
				activeThoughtId = null;
			}
		};

		const removeActiveStreamingThought = (msgs: ChatMessage[]): ChatMessage[] => {
			if (!activeThoughtId) {
				return msgs;
			}
			const id = activeThoughtId;
			dropActiveThoughtMark();
			return msgs.filter(m => m.id !== id);
		};

		const upsertStreamingThought = (
			msgs: ChatMessage[],
			sid: string,
			text: string,
			thoughtStartedAt: number | null,
		): ChatMessage[] => {
			const content = text.trim();
			if (!content) {
				return msgs;
			}
			const id = ensureActiveThoughtId(sid);
			const idx = msgs.findIndex(m => m.id === id);
			const row: ChatMessage = {
				id,
				role: 'assistant',
				text: content,
				isThought: true,
				thoughtMs:
					thoughtStartedAt != null
						? Date.now() - thoughtStartedAt
						: undefined,
				createdAt: thoughtStartedAt ?? Date.now(),
			};
			if (idx >= 0) {
				const next = [...msgs];
				next[idx] = row;
				return next;
			}
			return [...msgs, row];
		};

		const finalizeStreamingThought = (
			msgs: ChatMessage[],
			sid: string,
			text: string,
			thoughtMs?: number,
		): ChatMessage[] => {
			const content = text.trim();
			const id = activeThoughtId ?? ensureActiveThoughtId(sid);
			dropActiveThoughtMark();
			if (!content) {
				return msgs.filter(m => m.id !== id);
			}
			const idx = msgs.findIndex(m => m.id === id);
			const row: ChatMessage = {
				id,
				role: 'assistant',
				text: content,
				isThought: true,
				thoughtMs,
				createdAt:
					idx >= 0 ? (msgs[idx]!.createdAt ?? Date.now()) : Date.now(),
			};
			if (idx >= 0) {
				const next = [...msgs];
				next[idx] = row;
				return next;
			}
			return [...msgs, row];
		};

		const flushFrame = (opts?: {settle?: boolean}) => {
			if (frameRaf) {
				cancelAnimationFrame(frameRaf);
				frameRaf = 0;
			}
			if (settled && !opts?.settle) {
				pendingDelta = '';
				pendingReasoning = '';
				return;
			}
			const tools = pendingTools;
			pendingTools = [];
			/* 同帧 call+result 时先落 Reading，下一帧再 settle → 才能播 A8 翻面。
			 * settle 路径不 defer，避免 clearStream 前丢已入队的 result。 */
			const toolCalls = tools.filter(
				(ev): ev is Extract<PendingTool, {kind: 'call'}> =>
					ev.kind === 'call',
			);
			const toolResults = tools.filter(
				(ev): ev is Extract<PendingTool, {kind: 'result'}> =>
					ev.kind === 'result',
			);
			const deferToolResults =
				!opts?.settle && toolCalls.length > 0 && toolResults.length > 0;
			const toolsNow = deferToolResults ? toolCalls : tools;
			if (deferToolResults) {
				pendingTools = toolResults;
			}
			const chunk = pendingDelta;
			pendingDelta = '';
			const reasoningChunk = pendingReasoning;
			pendingReasoning = '';
			const written: string[] = [];
			set(cur => {
				if (!sessionStreamActive(cur, sessionId) && !opts?.settle) {
					return cur;
				}
				const stream = getSessionStream(cur, sessionId);
				let streamingText = stream.streamingText + chunk;
				let reasoningText = stream.reasoningText + reasoningChunk;
				let thoughtStartedAt = stream.thoughtStartedAt;
				let statusText = stream.statusText;
				if (reasoningChunk) {
					statusText = '';
					// 真正有 reasoning 时才开 Thought 计时；勿在工具边界抢先打开
					if (thoughtStartedAt == null) {
						thoughtStartedAt = Date.now();
					}
				}
				let msgs = cur.messagesById[sessionId] ?? [];
				let sessionTodos = cur.sessionTodosById;
				let messagesChanged = false;
				if (reasoningChunk && reasoningText.trim()) {
					const withThought = upsertStreamingThought(
						msgs,
						sessionId,
						reasoningText,
						thoughtStartedAt,
					);
					if (withThought !== msgs) {
						msgs = withThought;
						messagesChanged = true;
					}
				}
				for (const ev of toolsNow) {
					if (ev.kind === 'call') {
						const thoughtSnapshot = reasoningText.trim();
						const thoughtDuration =
							thoughtStartedAt != null
								? Date.now() - thoughtStartedAt
								: undefined;
						reasoningText = '';
						// 工具到达后清空计时；等下一段 reasoning 再开始，避免空 Thinking 挂在工具下方
						thoughtStartedAt = null;
						msgs = thoughtSnapshot
							? finalizeStreamingThought(
									msgs,
									sessionId,
									thoughtSnapshot,
									thoughtDuration,
								)
							: removeActiveStreamingThought(msgs);
						const next = applyToolCall(
							msgs,
							streamingText,
							ev.name,
							ev.input,
							sessionTodos,
							{toolUseId: ev.toolUseId},
						);
						msgs = next.msgs;
						streamingText = next.streamingText;
						sessionTodos = next.sessionTodos;
						messagesChanged = true;
					} else {
						if (!messagesChanged) {
							msgs = [...msgs];
						}
						const next = applyToolResult(
							msgs,
							ev.name,
							ev.output,
							ev.is_error,
							ev.todos,
							sessionTodos,
							written,
							ev.toolUseId,
						);
						msgs = next.msgs;
						sessionTodos = next.sessionTodos;
						messagesChanged = true;
						dispatchXeyoUi(ev.ui, {
							toolUseId: ev.toolUseId,
							isError: ev.is_error,
						});
					}
				}
				let streamingShown = stream.streamingShown;
				if (streamingText) {
					streamingShown = advanceTypewriterShown(
						streamingText,
						streamingShown,
						typewriterCache,
						streamTypewriterStepFor(
							streamingText,
							streamNeedsFastTypewriter,
						),
					);
				} else {
					streamingShown = '';
				}
				if (
					streamingText === stream.streamingText &&
					streamingShown === stream.streamingShown &&
					reasoningText === stream.reasoningText &&
					thoughtStartedAt === stream.thoughtStartedAt &&
					statusText === stream.statusText &&
					!messagesChanged
				) {
					return cur;
				}
				return {
					sessionStreams: patchSessionStream(cur.sessionStreams, sessionId, {
						streamingText,
						streamingShown,
						reasoningText,
						thoughtStartedAt,
						statusText,
					}),
					messagesById: messagesChanged
						? {...cur.messagesById, [sessionId]: msgs}
						: cur.messagesById,
					sessionTodosById: sessionTodos,
				};
			});
			{
				const msgs = get().messagesById[sessionId] ?? [];
				persistence.hot(msgs);
			}
			if (written.length > 0) {
				void import('@/stores/explorerStore').then(({useExplorerStore}) => {
					for (const path of written) {
						void useExplorerStore.getState().reloadIfOpen(path);
						// P1-⑦：失效重列文件的父目录，避免删除/新增后文件树残留。
						// invalidateDir 对无缓存的 key 是 no-op，安全。
						void useExplorerStore.getState().invalidateDir(parentDir(path));
					}
				});
			}
			const after = get();
			const afterStream = getSessionStream(after, sessionId);
			if (streamSignalsEnabled && after.activeId === sessionId) {
				setStreamingTextSignal(afterStream.streamingShown);
			}
			if (deferToolResults) {
				scheduleFrame();
			}
			if (
				!settled &&
				sessionStreamActive(after, sessionId) &&
				afterStream.streamingShown !== afterStream.streamingText &&
				// 仅剩被扣住的列表标号尾巴时不再空转续帧；新 delta 会重新调度
				!isOnlyHoldBackLag(
					afterStream.streamingText,
					afterStream.streamingShown,
				)
			) {
				scheduleFrame();
			}
		};

		const scheduleFrame = () => {
			if (!frameRaf) {
				frameRaf = requestAnimationFrame(() => flushFrame());
			}
		};

		const enqueueTool = (ev: PendingTool) => {
			pendingTools.push(ev);
			/* tool_result 必须立刻 settle 动词；勿排在打字机 rAF 队列后。 */
			if (ev.kind === 'result' || !smoothStream()) {
				flushFrame();
				return;
			}
			scheduleFrame();
		};

		// 乐观 UI 优先 — 在此落地前永不清空输入框。
		set(s => ({
			sessions: sessions.sort((a, b) => b.updatedAt - a.updatedAt),
			messagesById: {...get().messagesById, [sessionId]: nextMessages},
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				isLoading: true,
				streamingText: '',
				streamingShown: '',
				statusText: 'thinking…',
				reasoningText: '',
				// 等首段 reasoning 到达再计时，避免空 Thinking 抢先入轨
				thoughtStartedAt: null,
				abortRef: abort,
				remoteStreaming: false,
				draining: false,
			}),
			...(background
				? {}
				: {activeId: sessionId, activeSpaceId: session.spaceId}),
			...sessionErrorBannerPatch(null, null),
		}));
		if (streamSignalsEnabled && get().activeId === sessionId) {
			setStreamingTextSignal('');
		}
		onAccepted?.();

		void saveSession(session).catch(() => {
			/* 尽力而为；消息已在 UI 中可见 */
		});
		void replaceMessages(sessionId, nextMessages).catch(err => {
			const message = err instanceof Error ? err.message : String(err);
			set(cur => ({
				messagesById: {
					...cur.messagesById,
					[sessionId]: [
						...(cur.messagesById[sessionId] ?? nextMessages),
						{
							id: uid('err'),
							role: 'system',
							text: `本地保存失败：${message}`,
							createdAt: Date.now(),
						},
					],
				},
			}));
		});

		const sessionStillAlive = () =>
			get().sessions.some(s => s.id === sessionId);

		const clearStream = (
			patch: Partial<ChatState> = {},
			opts?: {orphanMode?: 'waiting' | 'error'},
		) => {
			/* 先把已入队的 tool result settle 完，再清队列。 */
			flushFrame({settle: true});
			while (pendingTools.length > 0) {
				flushFrame({settle: true});
			}
			persistence.cancelTimer();
			pendingDelta = '';
			pendingReasoning = '';
			pendingTools = [];
			const cur = get();
			const storeMsgs = cur.messagesById[sessionId!] ?? [];
			const patchMsgs = patch.messagesById?.[sessionId!];
			const raw = patchMsgs
				? overlaySettledTools(patchMsgs, storeMsgs)
				: storeMsgs;
			const orphanMode = opts?.orphanMode ?? 'error';
			const settledMsgs =
				orphanMode === 'waiting'
					? markRunningToolsWaiting(raw)
					: settleOrphanRunningTools(raw);
			const baseMessages = patch.messagesById ?? cur.messagesById;
			const messagesById = settledMsgs.changed || patchMsgs
				? {...baseMessages, [sessionId!]: settledMsgs.messages}
				: baseMessages;
			if (settledMsgs.changed || patchMsgs) {
				persistence.now(settledMsgs.messages);
			} else {
				persistence.flushQueued();
			}
			if (
				orphanMode === 'waiting' &&
				settledMsgs.messages.some(
					m => m.role === 'tool' && m.toolStatus === 'waiting',
				)
			) {
				toolSettle.scheduleWaitingToolSettle();
			} else {
				clearWaitingToolTimer(sessionId);
			}
			set(s => ({
				sessionStreams: clearSessionStreamState(s.sessionStreams, sessionId!),
				pendingPlan:
					s.pendingPlan?.sessionId === sessionId ? null : s.pendingPlan,
				// smoke-test #1：仍有未完成 todo 时保留快照（面板继续显示）。
				sessionTodosById: {
					...cur.sessionTodosById,
					[sessionId!]: todosWithUnfinished(
						cur.sessionTodosById?.[sessionId!],
					),
				},
				...patch,
				messagesById,
			}));
			if (streamSignalsEnabled && get().activeId === sessionId) {
				setStreamingTextSignal('');
			}
		};

		// 空回复守卫标志：本回合出流但 0 输出 → 结束时给出可见反馈而非静默。
		let emptyReplyNoticed = false;
		const commitAssistant = () => {
			if (settled) {
				return;
			}
			flushFrame({settle: true});
			while (pendingTools.length > 0) {
				flushFrame({settle: true});
			}
			settled = true;
			if (!sessionStillAlive()) {
				clearStream({}, {orphanMode: 'error'});
				return;
			}
			const cur = get();
			const stream = getSessionStream(cur, sessionId!);
			const msgs = [...(cur.messagesById[sessionId!] ?? [])];
			const drained = drain.isDraining() && drain.getTextSnap() ? drain.getTextSnap() : '';
			const out = drained || stream.streamingText;
			const reasoningSnapshot = stream.reasoningText.trim();
			const thoughtMs =
				reasoningSnapshot && stream.thoughtStartedAt != null
					? Date.now() - stream.thoughtStartedAt
					: undefined;
			let withoutStream = [...msgs];
			if (reasoningSnapshot) {
				withoutStream = finalizeStreamingThought(
					withoutStream,
					sessionId!,
					reasoningSnapshot,
					thoughtMs,
				);
			} else {
				withoutStream = removeActiveStreamingThought(withoutStream);
			}
			if (out) {
				withoutStream = appendAssistantProse(withoutStream, out);
			} else {
				// 空回复守卫：模型回合完成但 0 输出时，检查本回合是否真的没产出
				// （无 assistant 正文 / 无 tool 正文），是则给用户可见的反馈，
				// 而非只留下一个用户气泡然后“毫无反应”。
				const afterIdx =
					(cur.messagesById[sessionId!] ?? []).findIndex(
						m => m.id === userMsg.id,
					) + 1;
				const hasTurnOutput =
					afterIdx > 0 &&
					(cur.messagesById[sessionId!] ?? [])
						.slice(afterIdx)
						.some(m =>
							m.role === 'assistant'
								? Boolean(m.text && !m.isThought)
								: m.role === 'tool'
									? Boolean(m.text)
									: false,
						);
				if (!hasTurnOutput) {
					emptyReplyNoticed = true;
					withoutStream = [
						...withoutStream,
						{
							id: uid('msg'),
							role: 'system' as const,
							text: '模型未返回任何内容（空回复）。请重试，或检查设置中的模型 / API Key。',
							// 裁决 7：UI 横幅必须标 uiOnly，否则 toApiMessages 会把它
							// 当 system 消息漏进模型上下文（对模型是指令）。
							uiOnly: true,
							createdAt: Date.now(),
						},
					];
				}
			}
			clearStream(
				{
					messagesById: {...cur.messagesById, [sessionId!]: withoutStream},
					...(emptyReplyNoticed
						? sessionErrorBannerPatch(
								sessionId!,
								'模型未返回内容（空回复），请重试。',
							)
						: {}),
				},
				{orphanMode: 'waiting'},
			);
			persistence.now(get().messagesById[sessionId!] ?? withoutStream);
			flushThoughtSync(activeBackendSessionId(get().historyById, sessionId!), get().messagesById[sessionId!] ?? withoutStream);
		};

		const drain = createStreamDrain({
			get,
			set,
			sessionId,
			typewriterCache,
			persistNow: persistence.now,
			sessionStillAlive,
			cancelFrameRaf: () => {
				if (frameRaf) {
					cancelAnimationFrame(frameRaf);
					frameRaf = 0;
				}
			},
			onFinish: commitAssistant,
		});

		const flushPersistOnExit = () => {
			if (!get().sessions.some(s => s.id === sessionId)) {
				return;
			}
			const cur = get();
			let msgs = [...(cur.messagesById[sessionId] ?? [])];
			const stream = getSessionStream(cur, sessionId);
			const reasoningSnap = stream.reasoningText.trim();
			if (reasoningSnap) {
				const thoughtMs =
					stream.thoughtStartedAt != null
						? Date.now() - stream.thoughtStartedAt
						: undefined;
				msgs = finalizeStreamingThought(
					msgs,
					sessionId,
					reasoningSnap,
					thoughtMs,
				);
			} else {
				msgs = removeActiveStreamingThought(msgs);
			}
			if (stream.streamingText.trim()) {
				msgs = appendAssistantProse(msgs, stream.streamingText);
			}
			persistence.onExit(msgs);
		};

		try {
			window.addEventListener('pagehide', flushPersistOnExit);
			const apiMessages = toApiMessages(nextMessages);
			await streamChat(backendSessionId, apiMessages, {
				signal: abort.signal,
				onDelta(chunk) {
					pendingDelta += chunk;
					scheduleFrame();
				},
				onReasoningDelta(chunk) {
					if (settled || !sessionStreamActive(get(), sessionId)) {
						return;
					}
					pendingReasoning += chunk;
					scheduleFrame();
				},
				onToolCall({name, input, toolUseId}) {
					if (settled || !sessionStreamActive(get(), sessionId)) {
						return;
					}
					enqueueTool({kind: 'call', name, input, toolUseId});
					multi.handleAgentCard(name, input);
				},
				onToolResult({name, output, is_error, todos, ui, toolUseId}) {
					if (!sessionStillAlive()) {
						return;
					}
					if (settled || !sessionStreamActive(get(), sessionId)) {
						toolSettle.applyLateToolResult({
							name,
							output,
							is_error: Boolean(is_error),
							todos,
							ui,
							toolUseId,
						});
						return;
					}
					enqueueTool({
						kind: 'result',
						name,
						output,
						is_error: Boolean(is_error),
						todos,
						ui,
						toolUseId,
					});
				},
				onUsage(ev) {
					usage.onUsage(ev);
				},
				onCompression(ev) {
					usage.onCompression(ev);
				},
				onTitle(ev) {
					// T5：标题帧（投影-only）。本地会话标题随后端 sidecar 更新；
					// pinned（用户显式改名）为真时不覆盖，与后端 write_title 同语义。
					if (ev.pinned) {
						return;
					}
					const title = ev.title.trim();
					if (!title) {
						return;
					}
					const cur = get().sessions.find(x => x.id === sessionId);
					if (!cur || cur.title === title) {
						return;
					}
					const nextSession = {...cur, title};
					set(s => ({
						sessions: s.sessions.map(x => (x.id === sessionId ? nextSession : x)),
					}));
					void saveSession(nextSession).catch(() => {
						/* 尽力而为；后端 sidecar 已持有权威标题 */
					});
				},
				onPermissionPending(ev) {
					pending.onPermissionPending(ev);
				},
				onPermissionResolved(ev) {
					pending.onPermissionResolved(ev);
				},
				onAskUserPending(ev) {
					pending.onAskUserPending(ev);
				},
				onAskUserResolved(ev) {
					pending.onAskUserResolved(ev);
				},
				onPlanPending(ev) {
					pending.onPlanPending(ev);
				},
				onPlanResolved(ev) {
					pending.onPlanResolved(ev);
				},
				onGoal(ev) {
					// 41 号：goal 投影帧（whole-value）→ per-session 快照。
					// 与 todos 不同：turn 之间不清空（goal 状态跨轮存续）。
					if (!sessionStillAlive()) {
						return;
					}
					const next = normalizeSessionGoalState(ev.goal, ev.driver);
					set(s => ({
						sessionGoalById: {
							...s.sessionGoalById,
							[sessionId]: next,
						},
					}));
				},
				onJobs(ev) {
					// 42 号：jobs whole-value 快照。last-wins；空集 = 删除键
					// （缺失与 [] 同一表示，消费方永不测哨兵）。
					if (!sessionStillAlive()) {
						return;
					}
					const jobs = normalizeJobSnapshots(ev.jobs);
					set(s => {
						const next = {...s.sessionJobsById};
						if (jobs.length === 0) {
							delete next[sessionId];
						} else {
							next[sessionId] = jobs;
						}
						return {sessionJobsById: next};
					});
				},
				onMultiAgentTask(ev) {
					if (!sessionStreamActive(get(), sessionId)) {
						return;
					}
					multi.onMultiAgentTask(ev);
				},
				onMultiAgentResult(ev) {
					if (!sessionStreamActive(get(), sessionId)) {
						return;
					}
					multi.onMultiAgentResult(ev);
				},
				onMultiAgentProgress(ev) {
					if (!sessionStreamActive(get(), sessionId)) {
						return;
					}
					multi.onMultiAgentProgress(ev);
				},
				onMultiAgentDelta(ev) {
					if (!sessionStreamActive(get(), sessionId)) {
						return;
					}
					multi.onMultiAgentDelta(ev);
				},
				onMultiAgentStatus(ev) {
					if (!sessionStreamActive(get(), sessionId)) {
						return;
					}
					multi.onMultiAgentStatus(ev);
				},
				onQueued({queueId, position}) {
					// P1：后端已把消息排进 FIFO（settle 后自动投递）。保留乐观气泡
					// （不撤回），记入 inboxBySession 供 Composer chip 渲染。
					if (!sessionStillAlive()) {
						return;
					}
					toast.info(`已排队（第 ${position} 条），当前回合结束后自动投递`);
					set(s => {
						const prev = s.inboxBySession[sessionId] ?? [];
						return {
							inboxBySession: {
								...s.inboxBySession,
								[sessionId]: [
									...prev,
									{
										queue_id: queueId,
										text: userMsg.text,
										media_refs: userMsg.mediaRefs ?? [],
										message_id: userMsg.id ?? null,
										queued_at: Date.now(),
										attempts: 0,
										state: 'queued' as const,
										position,
									},
								],
							},
							hasInboxChip: true,
						};
					});
				},
				onDone() {
					usage.flush();
					flushFrame({settle: true});
					while (pendingTools.length > 0) {
						flushFrame({settle: true});
					}
					const cur = get();
					const stream = getSessionStream(cur, sessionId);
					if (!sessionStreamActive(cur, sessionId)) {
						// recoverStuckStream / clear 可能已摘掉 isLoading，但 tail 仍在。
						if (stream.streamingText.trim() && sessionStillAlive()) {
							commitAssistant();
						}
						return;
					}
					if (
						stream.streamingText.length - stream.streamingShown.length >
							DRAIN_MIN_BACKLOG &&
						sessionStillAlive()
					) {
						drain.start();
						return;
					}
					commitAssistant();
				},
				async onError(message, opts) {
					if (settled) {
						return;
					}
					usage.flush();
					flushFrame();
					settled = true;
					if (!sessionStillAlive()) {
						clearStream();
						return;
					}
					// 回合未启动型错误（session_busy / 其他 HTTP 状态拒绝）：
					// 后端从未写入用户消息，撤回乐观追加的那条；也不要 interrupt——
					// 没有可中断的回合（持有租约的可能是在跑的旧回合）。
					if (
						opts?.kind === 'session_busy' ||
						opts?.kind === 'turn_not_started'
					) {
						const looksAuth =
							/api key|401|authentication|未授权|鉴权/i.test(message);
						if (looksAuth) {
							useSettingsStore.getState().openSettings();
						}
						const cur = get();
						const kept = (cur.messagesById[sessionId] ?? []).filter(
							m => m.id !== userMsg.id,
						);
						clearStream({
							messagesById: {...cur.messagesById, [sessionId]: kept},
							...sessionErrorBannerPatch(sessionId, message),
						});
						return;
					}
					const cur = get();
					const stream = getSessionStream(cur, sessionId);
					const msgs = [...(cur.messagesById[sessionId!] ?? [])];
					if (stream.streamingText) {
						msgs.push({
							id: uid('msg'),
							role: 'assistant',
							text: stream.streamingText,
							createdAt: Date.now(),
						});
					}
					const looksAuth =
						/api key|401|authentication|未授权|鉴权/i.test(message);
					if (looksAuth) {
						useSettingsStore.getState().openSettings();
					}
					if (opts?.kind === 'connection_lost') {
						// T29：断流不杀回合、绝不自动 interrupt——带重试恢复，失败才显式呈现。
						// 旧连接的 AbortController 已死但未 aborted：置空 + 标记 detached，
						// 否则 reattachStream 会误判「已在收流」而跳过重连。
						set(s => ({
							sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
								statusText: '连接中断，正在重连…',
								abortRef: null,
								turnDetached: true,
							}),
						}));
						const recovered = await recoverAfterDisconnect(
							set,
							get,
							sessionId,
							backendSessionId,
						);
						if (recovered) {
							return;
						}
						const cur2 = get();
						const stream2 = getSessionStream(cur2, sessionId);
						const msgs2 = [...(cur2.messagesById[sessionId!] ?? [])];
						if (stream2.streamingText) {
							msgs2.push({
								id: uid('msg'),
								role: 'assistant',
								text: stream2.streamingText,
								createdAt: Date.now(),
							});
						}
						clearStream({
							messagesById: {...cur2.messagesById, [sessionId!]: msgs2},
							...sessionErrorBannerPatch(
								sessionId,
								`连接中断：${message}。回合保留在后端，可手动重试`,
							),
						});
						persistence.now(msgs2);
						return;
					}
					void interruptChat(backendSessionId);
					clearStream({
						messagesById: {...cur.messagesById, [sessionId!]: msgs},
						...sessionErrorBannerPatch(sessionId, message),
					});
					persistence.now(msgs);
				},
			},
			{mediaRefs, agentMode: requestedAgentMode, multiAgent: requestedMultiAgent, workspace: workspaceRoot, reasoningEffort: opts?.reasoningEffort},
			);
		} catch (err) {
			flushFrame();
			if ((err as Error).name === 'AbortError') {
				commitAssistant();
				return true;
			}
			if (settled) {
				return true;
			}
			settled = true;
			if (!sessionStillAlive()) {
				clearStream();
				return true;
			}
			const message = err instanceof Error ? err.message : String(err);
			// T29：主路径错误也走 reattach 恢复分支，不自动 interrupt——
			// 回合可能仍在后端 detached 运行；恢复失败才显式呈现断连。
			set(s => ({
				sessionStreams: patchSessionStream(s.sessionStreams, sessionId!, {
					statusText: '连接中断，正在重连…',
					abortRef: null,
					turnDetached: true,
				}),
			}));
			const recovered = await recoverAfterDisconnect(
				set,
				get,
				sessionId!,
				backendSessionId,
			);
			if (recovered) {
				return true;
			}
			const cur = get();
			const stream = getSessionStream(cur, sessionId!);
			const msgs = [...(cur.messagesById[sessionId!] ?? [])];
			if (stream.streamingText) {
				msgs.push({
					id: uid('msg'),
					role: 'assistant',
					text: stream.streamingText,
					createdAt: Date.now(),
				});
			}
			clearStream({
				messagesById: {...cur.messagesById, [sessionId!]: msgs},
				...sessionErrorBannerPatch(
					sessionId,
					`连接中断：${message}。回合保留在后端，可手动重试`,
				),
			});
		} finally {
			window.removeEventListener('pagehide', flushPersistOnExit);
			const cur = get();
			const stream = getSessionStream(cur, sessionId);
			if (
				!settled &&
				sessionStreamBusy(cur, sessionId) &&
				stream.isLoading
			) {
				commitAssistant();
			}
		}
		return true;
	},
	};
}

