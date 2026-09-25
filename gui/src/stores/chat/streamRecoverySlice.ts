/**
 * streamRecoverySlice.ts — 恢复与重新挂载方法，自
 * streamSendSlice.createStreamSendSlice() 原样拆出。行为不变；
 * createStreamSendSlice 在原位置展开 createStreamRecoverySlice(set, get)。
 */
import type {StoreApi} from 'zustand';
import {
	abandonSessionRecovery,
	fetchSessionTask,
	interruptChat,
	loadServerSessionMessages,
	readTurnCursor,
	streamTurnEvents,
	type MultiAgentTaskView,
} from '@/lib/api';
import {dispatchXeyoUi} from '@/lib/dispatchXeyoUi';
import {formatLlmRetryStarted, formatLlmRetryWaiting} from '@/lib/llmRetryStatus';
import {
	replaceMessages,
} from '@/lib/db';
import {
	toast,
} from '@/lib/toast';
import {
	formatToolInputForUi,
} from '@/lib/sanitizeToolInput';
import {
	type ChatMessage,
} from '@/lib/types';
import {
	sessionErrorBannerPatch,
} from '@/lib/pendingForSession';
import {
	getSessionStream,
	isAbortDead,
	isSessionStreamLive,
	normalizeSessionStreams,
	patchSessionStream,
	sessionStreamActive,
} from '@/lib/sessionStreams';
import {
	activeBackendSessionId,
	clearSessionStreamState,
	commitDrainForSession,
	loadSessionMessagesWithBackfill,
	normalizeChatHistoryState,
	settleAllSessionTools,
	type ChatState,
} from './preStoreHelpers';
import {createPendingStreamHandlers} from './uiChromeSlice';
import {
	WAITING_TOOL_TIMEOUT_MS,
	appendAssistantProse,
	clearWaitingToolTimer,
	flushOrphanStreamingTail,
	markRunningToolsWaiting,
	settleOrphanRunningTools,
	settleToolsFromServer,
	snapshotFromTodoTool,
	waitingToolTimers,
} from './streamHelpers';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

/**
 * 整表回写（``replaceMessages`` 先按游标删干净再写）只允许用于历史已经加载
 * 完的会话。冷会话的 ``messagesById`` 是 ``undefined``，此时拿服务端重放出来
 * 的零星几条工具卡去替换，等于把整个对话从 IndexedDB 抹掉；正在回填的会话同理。
 */
function wholeWriteIsSafe(
	s: Pick<ChatState, 'messagesById' | 'messagesLoadingIds'>,
	sessionId: string,
): boolean {
	return s.messagesById[sessionId] !== undefined && !s.messagesLoadingIds[sessionId];
}

const REATTACH_MAX_ATTEMPTS = 3;
const reattachInFlight = new Map<string, Promise<boolean>>();
const reattachBackoffMs = (attempt: number) => 500 * 2 ** attempt;
const sleep = (ms: number) =>
	new Promise<void>(resolve => setTimeout(resolve, ms));

/**
 * T29：回合在断连期间已结束 → 以服务端 transcript 收尾（不报错）。
 */
function finalizeFinishedTurn(
	set: SetState,
	sessionId: string,
	msgs: ChatMessage[],
): void {
	void replaceMessages(sessionId, msgs);
	set(s => ({
		messagesById: {...s.messagesById, [sessionId]: msgs},
		sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
			isLoading: false,
			streamingText: '',
			streamingShown: '',
			statusText: '回合已结束（连接曾中断，已恢复最终内容）',
			abortRef: null,
			turnDetached: false,
			draining: false,
			remoteStreaming: false,
		}),
	}));
}

/**
 * T29 断流恢复管线（绝不 interrupt）：
 * 重试上限内 task 探测 → reattach（其内部自带断流重连）→
 * 回合已结束则拉服务端 transcript 收尾；失败返回 false，由调用方显式呈现断连。
 */
export async function recoverAfterDisconnect(
	set: SetState,
	get: GetState,
	sessionId: string,
	backendSessionId: string,
): Promise<boolean> {
	for (let attempt = 0; attempt < REATTACH_MAX_ATTEMPTS; attempt++) {
		if (!sessionStreamActive(get(), sessionId)) {
			// 用户已停止/清理：放弃恢复
			return false;
		}
		const task = await fetchSessionTask(backendSessionId);
		if (task) {
			if (task.status === 'recovery_required') {
				await get().reattachStream(sessionId);
				return true; // 显式恢复 UI 已呈现（continueRecovery / abandonRecovery）
			}
			const running =
				task.busy ||
				task.status === 'running' ||
				task.status === 'waiting_permission' ||
				task.status === 'stopping';
			if (!running) {
				const msgs = await loadServerSessionMessages(backendSessionId);
				if (msgs.length > 0) {
					finalizeFinishedTurn(set, sessionId, msgs);
					return true;
				}
				// transcript 暂时拉不到：退避后重试
			} else if (await get().reattachStream(sessionId)) {
				return true;
			} else if (get().recoveryBySession[sessionId]) {
				return true;
			}
		}
		await sleep(reattachBackoffMs(attempt));
	}
	return false;
}

/**
 * smoke-test #15：停止/断流后以服务端 transcript 对账 waiting/running 工具卡。
 * SSE 已 abort 时引擎的 abort 收尾会把未决工具的真实结果（或 "aborted" 标注）
 * 写进服务端 transcript，但客户端收不到 —— 这里按 toolUseId 用服务端结果覆盖
 * 本地猜测。best-effort：拉取失败或无变化不做任何事。
 */
function reconcileToolsWithServer(
	get: GetState,
	set: SetState,
	sid: string,
	backendSessionId: string,
): void {
	void loadServerSessionMessages(backendSessionId).then(server => {
		if (server.length === 0) {
			return;
		}
		const cur = get();
		const msgs = cur.messagesById[sid] ?? [];
		if (
			!msgs.some(
				m =>
					m.role === 'tool' &&
					(m.toolStatus === 'running' || m.toolStatus === 'waiting'),
			)
		) {
			return;
		}
		const merged = settleToolsFromServer(msgs, server);
		if (!merged.changed) {
			return;
		}
		void replaceMessages(sid, merged.messages);
		set(s => ({
			messagesById: {...s.messagesById, [sid]: merged.messages},
		}));
	});
}

export function createStreamRecoverySlice(
	set: SetState,
	get: GetState,
): Pick<
	ChatState,
	'recoverStuckStream' | 'reattachActiveStreams' | 'reattachStream' | 'continueRecovery' | 'abandonRecovery' | 'stopGeneration' | 'sendToSession'
> {
	return {
	recoverStuckStream() {
		const s = get();
		const sessionStreams = normalizeSessionStreams(s);
		let messagesById = s.messagesById;
		// 活流 / 排水 / 后端 detached 标记：不要当成崩溃去 stamp interrupted。
		const skipSettle = new Set<string>();
		for (const [sid, stream] of Object.entries(sessionStreams)) {
			if (isSessionStreamLive(stream)) {
				skipSettle.add(sid);
			}
		}
		for (const sid of [...waitingToolTimers.keys()]) {
			const msgs = messagesById[sid] ?? [];
			const hasWaiting = msgs.some(
				m => m.role === 'tool' && m.toolStatus === 'waiting',
			);
			if (hasWaiting) {
				skipSettle.add(sid);
			} else {
				clearWaitingToolTimer(sid);
			}
		}
		for (const sid of Object.keys(messagesById)) {
			if (!skipSettle.has(sid)) {
				clearWaitingToolTimer(sid);
			}
		}
		const settled = settleAllSessionTools(messagesById, skipSettle);
		messagesById = settled.messagesById;
		for (const sid of settled.dirtySessionIds) {
			void replaceMessages(sid, messagesById[sid]!);
		}
		let nextStreams = sessionStreams;
		let orphanFlushed = false;
		for (const [sid, stream] of Object.entries(sessionStreams)) {
			if (isSessionStreamLive(stream)) {
				continue;
			}
			const dead = isAbortDead(stream.abortRef);
			if (stream.isLoading && dead) {
				const flushed = flushOrphanStreamingTail(messagesById, sid, stream);
				if (flushed.changed) {
					messagesById = flushed.messagesById;
					orphanFlushed = true;
					void replaceMessages(sid, messagesById[sid]!);
				}
				// 不再 interruptChat：后端可能仍 detached 在跑；由 reattachActiveStreams 重连。
				nextStreams = clearSessionStreamState(nextStreams, sid);
			}
		}
		const streamsChanged = nextStreams !== sessionStreams;
		const needsNormalize = s.sessionStreams !== sessionStreams;
		if (
			streamsChanged ||
			needsNormalize ||
			settled.dirtySessionIds.length > 0 ||
			orphanFlushed
		) {
			set({
				sessionStreams: nextStreams,
				messagesById,
			});
		}
	},

	async reattachActiveStreams() {
		const {sessions, activeId} = get();
		const ids = new Set<string>();
		if (activeId) ids.add(activeId);
		for (const sess of sessions.slice(0, 12)) {
			ids.add(sess.id);
		}
		for (const sid of ids) {
			await get().reattachStream(sid);
		}
	},

	async reattachStream(sessionId: string) {
		const inFlight = reattachInFlight.get(sessionId);
		if (inFlight) return inFlight;
		const work = (async () => {
			const backendSessionId = activeBackendSessionId(
				get().historyById,
				sessionId,
			);
			const task = await fetchSessionTask(backendSessionId);
			if (!task) {
				return false;
			}
			if (task.status === 'recovery_required') {
				set(s => ({
					recoveryBySession: {
						...s.recoveryBySession,
						[sessionId]: {
							goalText: task.goal_text || '',
							turnId: task.turn_id || '',
							stopReason: task.stop_reason || 'process_restart',
						},
					},
				}));
				return false;
			}
			const running =
				task.busy ||
				task.status === 'running' ||
				task.status === 'waiting_permission' ||
				task.status === 'stopping';
			if (!running) {
				return false;
			}
			// 已有活 abort → 已在收流
			const curStream = getSessionStream(get(), sessionId);
			if (curStream.abortRef && !isAbortDead(curStream.abortRef) && curStream.isLoading) {
				return true;
			}
			// Reattach writes a complete message list. Join hydrate/selectSession's
			// deduplicated local + server backfill first, including when it is already
			// loading; subscribing to a cold list would make later hydration skip its
			// authoritative rows after the first replay event.
			const beforeLoad = get();
			if (
				beforeLoad.messagesById[sessionId] === undefined ||
				beforeLoad.messagesLoadingIds[sessionId]
			) {
				let loaded: ChatMessage[];
				try {
					const history = normalizeChatHistoryState(
						beforeLoad.historyById[sessionId],
						sessionId,
					);
					loaded = await loadSessionMessagesWithBackfill(sessionId, {
						[sessionId]: history,
					});
				} catch {
					return false;
				}
				set(s => {
					if (!s.sessions.some(item => item.id === sessionId)) return s;
					const byId = new Map(loaded.map(message => [message.id, message]));
					// Preserve current UI-only notes and optimistic messages created while
					// the shared backfill was in flight. Current rows win on matching ids.
					for (const message of s.messagesById[sessionId] ?? []) {
						byId.set(message.id, message);
					}
					const merged = [...byId.values()].sort(
						(a, b) => a.createdAt - b.createdAt,
					);
					const messagesLoadingIds = {...s.messagesLoadingIds};
					delete messagesLoadingIds[sessionId];
					return {
						messagesById: {...s.messagesById, [sessionId]: merged},
						messagesLoadingIds,
					};
				});
				const ready = get();
				if (
					ready.messagesById[sessionId] === undefined ||
					ready.messagesLoadingIds[sessionId]
				) {
					return false;
				}
			}
			const abort = new AbortController();
			const cursor = Math.max(
				readTurnCursor(backendSessionId),
				curStream.lastEventId ?? 0,
				0,
			);
			set(s => ({
				sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
					isLoading: true,
					statusText: '重新连接中…',
					abortRef: abort,
					turnDetached: true,
					lastEventId: cursor,
					draining: false,
					remoteStreaming: false,
				}),
			}));
			let pendingDelta = '';
			const flushDelta = () => {
				if (!pendingDelta) return;
				const chunk = pendingDelta;
				pendingDelta = '';
				set(s => {
					const st = getSessionStream(s, sessionId);
					const nextText = st.streamingText + chunk;
					return {
						sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
							streamingText: nextText,
							statusText: '生成中',
							turnDetached: true,
						}),
					};
				});
			};
			// T29：重连流自身的断流也走有界重试；恢复期间挂起权限/提问/计划弹窗照常接住。
			const pending = createPendingStreamHandlers({get, sessionId});
			let connectionLost = false;
			// 本次订阅是否收到过后端重放空洞帧（环形缓冲已挤掉一段）。
			let sawGap = false;
			/** 无洞时的收尾：把本地累积的尾巴作为正文提交（带末行同文去重）。 */
			const commitLocalTail = () => {
				set(s => {
					const st = getSessionStream(s, sessionId);
					const text = st.streamingText;
					let msgs = [...(s.messagesById[sessionId] ?? [])];
					if (text.trim()) {
						// appendAssistantProse 带末行同文去重：重放(cursor 落后)
						// 会把已提交的尾巴再放一遍，裸 push 会产生重复气泡。
						msgs = appendAssistantProse(msgs, text);
						if (wholeWriteIsSafe(s, sessionId)) {
							void replaceMessages(sessionId, msgs);
						}
					}
					return {
						messagesById: {...s.messagesById, [sessionId]: msgs},
						sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
							isLoading: false,
							streamingText: '',
							streamingShown: '',
							statusText: '',
							abortRef: null,
							turnDetached: false,
							draining: false,
						}),
					};
				});
			};
			for (let attempt = 0; attempt < REATTACH_MAX_ATTEMPTS; attempt++) {
				connectionLost = false;
				sawGap = false;
				// cursor 每次重取：上一次断流前已收到的事件不重放
				const cursorNow = Math.max(cursor, readTurnCursor(backendSessionId));
				try {
					await streamTurnEvents(backendSessionId, cursorNow, {
						...pending,
						signal: abort.signal,
						onLlmRetry(ev) {
							set(s => ({
								sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
									statusText: formatLlmRetryWaiting(ev.attempt, ev.nextRetryMs),
								}),
							}));
						},
						onLlmRetryStarted(ev) {
							set(s => ({
								sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
									statusText: formatLlmRetryStarted(ev.attempt),
								}),
							}));
						},
						onReasoningDelta() {
							set(s => ({
								sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
									statusText: '生成中',
								}),
							}));
						},
						onDelta(text) {
						pendingDelta += text;
						flushDelta();
					},
					onToolCall({name, input, toolUseId}) {
						set(s => {
							const msgs = [...(s.messagesById[sessionId] ?? [])];
							const id = toolUseId || `tool-${Date.now()}`;
							const existing = msgs.findIndex(
								m => m.role === 'tool' && m.toolUseId === id,
							);
							const row: ChatMessage = {
								id: existing >= 0 ? msgs[existing]!.id : id,
								role: 'tool',
								text: '',
								toolName: name,
								toolInput: formatToolInputForUi(input),
								toolUseId: id,
								toolStatus: 'running',
								createdAt: Date.now(),
							};
							if (existing >= 0) {
								msgs[existing] = {...msgs[existing]!, ...row, id: msgs[existing]!.id};
							} else {
								msgs.push(row);
							}
							if (wholeWriteIsSafe(s, sessionId)) {
								void replaceMessages(sessionId, msgs);
							}
							return {
								messagesById: {...s.messagesById, [sessionId]: msgs},
								sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
									statusText: name,
								}),
							};
						});
					},
					onToolResult({name, output, is_error, toolUseId, todos, ui}) {
						dispatchXeyoUi(ui, {
							toolUseId,
							isError: Boolean(is_error),
						});
						set(s => {
							let msgs = [...(s.messagesById[sessionId] ?? [])];
							const id = toolUseId || '';
							const idx = msgs.findIndex(
								m =>
									m.role === 'tool' &&
									(id
										? m.toolUseId === id
										: m.toolName === name && m.toolStatus === 'running'),
							);
							if (idx >= 0) {
								msgs[idx] = {
									...msgs[idx]!,
									text: String(output ?? ''),
									toolStatus: is_error ? 'error' : 'done',
								};
							}
							if (wholeWriteIsSafe(s, sessionId)) {
								void replaceMessages(sessionId, msgs);
							}
							const patch: Partial<ChatState> = {
								messagesById: {...s.messagesById, [sessionId]: msgs},
							};
							if (Array.isArray(todos)) {
								const snap = snapshotFromTodoTool({
									id: `todo-reattach-${Date.now()}`,
									input: '',
									todos,
									running: false,
								});
								if (snap) {
									patch.sessionTodosById = {
										...s.sessionTodosById,
										[sessionId]: snap,
									};
								}
							}
							return patch;
						});
					},
					onMultiAgentTask(ev) {
						set(s => {
							const list = s.multiAgentTasksBySession[sessionId] ?? [];
							const uid = String(
								(ev as {uid?: string; agentId?: string}).uid ||
									(ev as {agentId?: string}).agentId ||
									'',
							);
							if (!uid || list.some(t => t.uid === uid)) return {};
							return {
								multiAgentTasksBySession: {
									...s.multiAgentTasksBySession,
									[sessionId]: [
										...list,
										{
											uid,
											taskId: String((ev as {taskId?: string}).taskId || uid),
											agentId: String((ev as {agentId?: string}).agentId || ''),
											desc: String((ev as {desc?: string}).desc || '').slice(0, 120),
											status: 'running',
										} as MultiAgentTaskView,
									],
								},
							};
						});
					},
					onMultiAgentProgress(ev) {
						set(s => {
							const list = [...(s.multiAgentTasksBySession[sessionId] ?? [])];
							const agentId = String((ev as {agentId?: string}).agentId || '');
							const idx = list.findIndex(
								t => t.agentId === agentId || t.uid === agentId,
							);
							if (idx < 0) return {};
							list[idx] = {
								...list[idx]!,
								status: (['pending', 'running', 'done', 'failed'].includes(
									String((ev as {status?: string}).status || ''),
								)
									? String((ev as {status?: string}).status)
									: list[idx]!.status) as MultiAgentTaskView['status'],
								result: String(
									(ev as {result?: string; message?: string}).result ||
										(ev as {message?: string}).message ||
										list[idx]!.result ||
										'',
								).slice(0, 400),
							};
							return {
								multiAgentTasksBySession: {
									...s.multiAgentTasksBySession,
									[sessionId]: list,
								},
							};
						});
					},
					onStreamGap() {
						sawGap = true;
					},
					onDone() {
						flushDelta();
						if (sawGap) {
							// 重放有洞：本地尾巴是缺段，绝不能当完整内容提交 ⇒ 用服务端
							// transcript 收尾；拉不到（网络/空集）再退回本地提交，不静默卡住。
							void loadServerSessionMessages(backendSessionId).then(server => {
								if (server.length > 0) {
									finalizeFinishedTurn(set, sessionId, server);
									return;
								}
								commitLocalTail();
							});
							return;
						}
						commitLocalTail();
					},
					onError(message, opts) {
						flushDelta();
						if (opts?.kind === 'connection_lost') {
							// T29：回合仍在后端跑——保留流状态由重试循环重连；不 interrupt。
							connectionLost = true;
							return;
						}
						set(s => ({
							sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
								isLoading: false,
								abortRef: null,
								turnDetached: false,
								statusText: '',
							}),
							...sessionErrorBannerPatch(sessionId, message),
						}));
					},
					});
				} catch (err) {
					// streamTurnEvents 自身不抛连接错误（都走 onError）；保守按连接失败重试
					if ((err as Error).name !== 'AbortError') {
						connectionLost = true;
					}
				}
				if (abort.signal.aborted) {
					// 用户在恢复期间主动停止：不再重试
					return true;
				}
				if (!connectionLost) {
					return true;
				}
				await sleep(reattachBackoffMs(attempt));
			}
			// T29：重试上限已到——显式呈现断连（不静默、不假装在跑、不 interrupt）。
			set(s => ({
				sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
					isLoading: false,
					abortRef: null,
					turnDetached: false,
					statusText: '',
				}),
				...sessionErrorBannerPatch(
					sessionId,
					`后端不可达：重连 ${REATTACH_MAX_ATTEMPTS} 次失败。回合保留在后端，可稍后手动重试。`,
				),
			}));
			return false;
		})();
		reattachInFlight.set(sessionId, work);
		try {
			return await work;
		} finally {
			if (reattachInFlight.get(sessionId) === work) {
				reattachInFlight.delete(sessionId);
			}
		}
	},

	async continueRecovery(sessionId: string) {
		set(s => {
			const next = {...s.recoveryBySession};
			delete next[sessionId];
			return {recoveryBySession: next};
		});
		await get().sendMessage('继续');
	},

	async abandonRecovery(sessionId: string) {
		const backendSessionId = activeBackendSessionId(
			get().historyById,
			sessionId,
		);
		await abandonSessionRecovery(backendSessionId);
		set(s => {
			const next = {...s.recoveryBySession};
			delete next[sessionId];
			return {recoveryBySession: next};
		});
	},

	async stopGeneration() {
		const sid = get().activeId;
		if (!sid) {
			return;
		}
		clearWaitingToolTimer(sid);
		commitDrainForSession(sid);
		let {messagesById} = get();
		const stream = getSessionStream(get(), sid);
		if (!sessionStreamActive(get(), sid)) {
			return;
		}
		stream.abortRef?.abort();
		// 立刻发请求，但回执要在到手后读：本地 abort 只证明"我不再读这条流"，
		// 不证明引擎停了。旧实现 `void interruptChat(...)` 把 401/500/断网全吞掉。
		const interrupting = interruptChat(activeBackendSessionId(get().historyById, sid));
		const flushed = flushOrphanStreamingTail(messagesById, sid, stream);
		if (flushed.changed) {
			messagesById = flushed.messagesById;
			void replaceMessages(sid, flushed.messagesById[sid]!);
		}
		const raw = messagesById[sid] ?? [];
		// 停止是 best-effort：引擎在 chunk 边界才响应 abort，正在跑的工具
		// 可能仍会成功返回。标 waiting 走 320s 宽限（晚到结果按 toolUseId
		// 覆盖），而不是立即盖 "[error] interrupted"（工具实际成功却永久
		// 显示错误的原始 bug 之 stop 版）。
		const settled = markRunningToolsWaiting(raw);
		const cleared = clearSessionStreamState(get().sessionStreams, sid);
		const clearBannerIfOwned = (s: ChatState) =>
			s.errorBannerSessionId === sid || s.errorBannerSessionId == null
				? sessionErrorBannerPatch(null, null)
				: {};
		if (settled.changed || flushed.changed) {
			void replaceMessages(sid, settled.messages);
		}
		set(s => ({
			sessionStreams: patchSessionStream(cleared, sid, {
				statusText: '已停止',
			}),
			...clearBannerIfOwned(s),
			...(settled.changed || flushed.changed
				? {messagesById: {...messagesById, [sid]: settled.messages}}
				: {}),
			// 流已 abort，permission/ask/plan 的 resolved 帧不会再来；
			// 不清的话弹窗悬挂，作答会打到已死的 request 上。
			pendingPermission:
				s.pendingPermission?.sessionId === sid ? null : s.pendingPermission,
			pendingAsk: s.pendingAsk?.sessionId === sid ? null : s.pendingAsk,
			pendingPlan: s.pendingPlan?.sessionId === sid ? null : s.pendingPlan,
		}));
		void interrupting.then(receipt => {
			// not_running = 后端回答"这个会话没有可中断的回合"：那「已停止」就是对的。
			if (receipt.ok || receipt.message === 'not_running') {
				return;
			}
			// 读不出回执 ⇒ 不能说"已停止"：引擎可能仍在跑并继续写这条会话的历史。
			set(s => ({
				sessionStreams: patchSessionStream(s.sessionStreams, sid, {
					statusText: '本地已停止，后端未确认',
				}),
			}));
			toast.warn(`停止请求未被后端确认（${receipt.message}）：回合可能仍在运行`);
		});
		if (settled.messages.some(m => m.role === 'tool' && m.toolStatus === 'waiting')) {
			// smoke-test #15：立即以服务端 transcript 对账（引擎 abort 收尾已把
			// 真实结果/标注落史），避免"工具成功落盘但 GUI 显示 error/等待"。
			const bsId = activeBackendSessionId(get().historyById, sid);
			if (bsId) {
				reconcileToolsWithServer(get, set, sid, bsId);
			}
			// 与 sendMessage 的宽限定时器同款：超时仍未被晚到结果覆盖才落 error。
			waitingToolTimers.set(
				sid,
				window.setTimeout(() => {
					waitingToolTimers.delete(sid);
					// 超时兜底同样先对账服务端一次，再猜 error。
					const bsId2 = activeBackendSessionId(get().historyById, sid);
					void loadServerSessionMessages(bsId2 || '').then(server => {
						const cur = get();
						let msgsNow = cur.messagesById[sid] ?? [];
						const merged = settleToolsFromServer(msgsNow, server);
						if (merged.changed) {
							void replaceMessages(sid, merged.messages);
							set(s => ({
								messagesById: {
									...s.messagesById,
									[sid]: merged.messages,
								},
							}));
							msgsNow = merged.messages;
						}
						if (
							!msgsNow.some(
								m => m.role === 'tool' && m.toolStatus === 'waiting',
							)
						) {
							return;
						}
						const settledNow = settleOrphanRunningTools(msgsNow);
						if (!settledNow.changed) {
							return;
						}
						void replaceMessages(sid, settledNow.messages);
						set(s => ({
							messagesById: {
								...s.messagesById,
								[sid]: settledNow.messages,
							},
						}));
					});
				}, WAITING_TOOL_TIMEOUT_MS),
			);
		}
	},

	async sendToSession(sessionId: string, text: string) {
		const target = sessionId.trim();
		const body = text.trim();
		if (!target || !body) {
			toast.error('跨对话发送需要 session_id 与 text');
			return false;
		}
		if (!get().sessions.some(s => s.id === target)) {
			toast.error('目标对话不存在');
			return false;
		}
		if (sessionStreamActive(get(), target)) {
			toast.error('目标对话正在运行，请稍后再试');
			return false;
		}
		return get().sendMessage(body, undefined, [], 'agent', undefined, false, {
			sessionId: target,
			background: true,
		});
	},
	};
}
