import {create} from 'zustand';

import {
	fetchRewindCheckpoint,
	fetchRewindEvents,
	fetchRewindStatus,
	loadServerSessionMessages,
	recoverRewind,
	rewindHotpath,
	rewindHotpathUndo,
	RollbackRequestError,
} from '@/lib/api';
import {setComposerDraft} from '@/lib/composerDrafts';
import {replaceMessages} from '@/lib/db';
import type {ChatMessage, RewindEvent} from '@/lib/types';
import {uid} from '@/lib/utils';
import {
	activeBackendSessionId,
	loadSessionMessagesWithBackfill,
	recoverSessionMessages,
} from '@/stores/chat/preStoreHelpers';
import {useChatStore} from '@/stores/chatStore';

/**
 * 回溯 v3 热路径 store（合同见 #31，企业级口径 #36）。
 *
 * 相对旧版的关键加固（设计 §6.1）：
 * - C1 幂等键确定化：`rw:{sid}:{target}:{attemptId}:{hash(editedText)[:8]}`；
 *   `attemptId` 在确认时生成、重试复用、新意图才换。去掉 `Date.now()`。
 * - C2 poll 失败/超时必回滚本地截断；终态成功前一律保留兜底（不提前删）。
 * - C3 进行中回溯态持久化（bySession 落盘），重载按 `rewindId` 重对齐。
 * - C4 回滚时用 `suffixBackup` 定格快照，并把目标消息文本替换为 `editedText`。
 * - C5 只以服务端 committed/partial 为「成功」；超时一律视为未决 + 可撤销。
 */

export type RewindV3Phase = 'idle' | 'dialog' | 'running' | 'done' | 'error';

export type RewindV3Action = 'restore' | 'continue';

export type RewindV3CheckpointState = 'pending' | 'ready' | 'none';

export interface RewindV3DialogState {
	phase: RewindV3Phase;
	targetMessageId: string | null;
	editedText: string;
	action: RewindV3Action | null;
	checkpointState: RewindV3CheckpointState;
	checkpointId: string | null;
	rewindId: string | null;
	/** pill 锚定模式：非空表示弹窗动作作用于该历史回溯事件（评审定稿：恢复对话/恢复文件分离） */
	pillRewindId: string | null;
	summary: string | null;
	error: string | null;

	// —— 持久化加固字段（设计 §6.1 C1/C3）——
	/** 幂等键稳定部分：同一确认动作内重试复用；新意图才更换 */
	attemptId: string | null;
	/** 是否已达成「服务端确认成功 / 已 undo / 已明确放弃」；false = 未决，可撤销 */
	settled: boolean;
	/** 同帧截断时定格的截断后缀（含目标消息），失败回滚用；含 editedText 修正（C4） */
	suffixBackup: ChatMessage[] | null;
	/** §9.2：此回溯处于 recovery_required 中间态，弹窗应给「从检查点重试/放弃」 */
	recovery: boolean;
	/** continue 已提交但自动重发失败：弹窗给「重试发送」（迁自 v2 committed_resend_failed） */
	resendPending: boolean;
	/** §9.1：当前目标消息的 checkpoint 是否已标记为锚点（取消锚点入口用） */
	checkpointAnchor: boolean | null;
}

export interface RewindPill {
	rewindId: string;
	afterMessageId: string;
	checkpointId: string;
	editedDigest: string;
	removedRows: number;
	ts: number;
}

interface RewindV3Store {
	bySession: Record<string, RewindV3BySession>;
	pillsBySession: Record<string, RewindPill[]>;
	openDialog(sessionId: string, targetMessageId: string, editedText: string): void;
	openPillDialog(sessionId: string, pill: RewindPill): void;
	closeDialog(sessionId: string): void;
	confirm(sessionId: string, action: RewindV3Action): Promise<boolean>;
	retry(sessionId: string): Promise<boolean>;
	/** continue 提交成功但自动 send 失败后的重发（迁自 v2 retryResendAfterRollback） */
	retryResend(sessionId: string): Promise<boolean>;
	recover(sessionId: string, action: 'retry' | 'abandon'): Promise<boolean>;
	/** 明确放弃未决回溯：恢复列表（若有兜底）并 settle，不调服务端 undo */
	abandon(sessionId: string): void;
	undoLast(sessionId: string): Promise<boolean>;
	loadPills(sessionId: string): Promise<void>;
	/** 重载后按持久化 rewindId 重对齐进行中回溯（设计 §6.1 C3） */
	rehydrate(sessionId: string): Promise<void>;
}

type RewindV3BySession = RewindV3DialogState;

const IDLE: RewindV3BySession = {
	phase: 'idle',
	targetMessageId: null,
	editedText: '',
	action: null,
	checkpointState: 'pending',
	checkpointId: null,
	rewindId: null,
	pillRewindId: null,
	summary: null,
	error: null,
	attemptId: null,
	settled: false,
	suffixBackup: null,
	recovery: false,
	resendPending: false,
	checkpointAnchor: null,
};

const STATE_PREFIX = 'xeyo.rewindV3.state';

function stateKey(sessionId: string): string {
	return `${STATE_PREFIX}.${sessionId}`;
}

/** 可持久化的字段子集（终态成功/已放弃的不再需要 suffixBackup 兜底，仍可写）。 */
function toPersistable(s: RewindV3BySession): RewindV3BySession {
	return {...s};
}

/** 写持久层：未决态（!settled）才保留 suffixBackup，避免终态后残留大对象。 */
function persistState(sessionId: string, s: RewindV3BySession): void {
	try {
		localStorage.setItem(stateKey(sessionId), JSON.stringify(toPersistable(s)));
	} catch {
		/* 存储满等异常：兜底缺失不阻断主流程 */
	}
}

function dropState(sessionId: string): void {
	try {
		localStorage.removeItem(stateKey(sessionId));
	} catch {
		/* 忽略 */
	}
}

function loadPersisted(): Record<string, RewindV3BySession> {
	const out: Record<string, RewindV3BySession> = {};
	try {
		for (let i = 0; i < localStorage.length; i++) {
			const key = localStorage.key(i);
			if (!key || !key.startsWith(STATE_PREFIX)) {
				continue;
			}
			const sessionId = key.slice(STATE_PREFIX.length + 1);
			try {
				const raw = localStorage.getItem(key);
				if (raw) {
					out[sessionId] = {...IDLE, ...JSON.parse(raw)};
				}
			} catch {
				/* 单条损坏不影响其余 */
			}
		}
	} catch {
		/* localStorage 不可用则忽略 */
	}
	return out;
}

const FALLBACK_PREFIX = 'xeyo.rewindV3.fallback';

/**
 * 兼容旧版「只存后缀」的兜底 key：migrating 到新持久态后即弃用。
 */
function migrateLegacyFallback(sessionId: string, cur: RewindV3BySession): RewindV3BySession {
	try {
		const raw = localStorage.getItem(`${FALLBACK_PREFIX}.${sessionId}`);
		if (raw && !cur.suffixBackup && cur.phase !== 'idle') {
			const suffix = JSON.parse(raw)?.suffix;
			if (Array.isArray(suffix)) {
				localStorage.removeItem(`${FALLBACK_PREFIX}.${sessionId}`);
				return {...cur, suffixBackup: suffix as ChatMessage[]};
			}
		}
	} catch {
		/* 忽略 */
	}
	return cur;
}

function dropLegacyFallback(sessionId: string): void {
	try {
		localStorage.removeItem(`${FALLBACK_PREFIX}.${sessionId}`);
	} catch {
		/* 忽略 */
	}
}

/** 确定性内容摘要（FNV-1a，32bit→hex 8）。无需 crypto，仅用于幂等键片段去碰撞。 */
function contentDigest(text: string): string {
	let hash = 0x811c9dc5;
	for (let i = 0; i < text.length; i++) {
		hash ^= text.charCodeAt(i);
		hash = Math.imul(hash, 0x01000193);
	}
	return (hash >>> 0).toString(16).padStart(8, '0');
}

/** C1 幂等键：重试复用同一 attemptId → 后端 `reused` 重放；内容摘要避免同 attempt 不同文案撞 key。 */
export function buildRewindIdempotencyKey(
	sessionId: string,
	targetMessageId: string,
	attemptId: string,
	editedText: string,
): string {
	return `rw:${sessionId}:${targetMessageId}:${attemptId}:${contentDigest(editedText)}`;
}

function idempotencyKey(
	sessionId: string,
	targetMessageId: string,
	attemptId: string,
	editedText: string,
): string {
	return buildRewindIdempotencyKey(sessionId, targetMessageId, attemptId, editedText);
}

function friendlyRewindError(err: unknown): string {
	if (err instanceof RollbackRequestError) {
		if (err.errorType === 'session_busy' || err.status === 409) {
			return 'Agent 正运行，请停止后再试。';
		}
		return err.message;
	}
	return err instanceof Error ? err.message : String(err);
}

function isSessionBusyError(err: unknown): boolean {
	return (
		err instanceof RollbackRequestError &&
		(err.errorType === 'session_busy' || err.status === 409)
	);
}

function eventsToPills(events: RewindEvent[]): RewindPill[] {
	const pills: RewindPill[] = [];
	for (const event of events) {
		if (event.mode !== 'continue' || event.undone || event.status === 'failed') {
			continue;
		}
		pills.push({
			rewindId: event.rewind_id,
			afterMessageId: event.after_message_id || '',
			checkpointId: event.checkpoint_id || '',
			editedDigest: event.pill_summary?.edited_digest || '',
			removedRows: event.pill_summary?.removed_rows || event.orphan_count || 0,
			ts: event.ts,
		});
	}
	// 同一锚点只保留最新一个 pill（合同：旧的合并省略，当前以最新为准）。
	const latestByAnchor = new Map<string, RewindPill>();
	for (const pill of pills.sort((a, b) => a.ts - b.ts)) {
		latestByAnchor.set(pill.afterMessageId, pill);
	}
	return [...latestByAnchor.values()].sort((a, b) => a.ts - b.ts);
}

function summarizeRestore(event: RewindEvent): string | null {
	const restore = event.restore;
	if (!restore) {
		return null;
	}
	const parts: string[] = [];
	const restored = restore.restored?.length ?? 0;
	const deleted = restore.deleted?.length ?? 0;
	const dirty = restore.skipped_dirty?.length ?? 0;
	if (restored) {
		parts.push(`已恢复 ${restored} 个文件`);
	}
	if (deleted) {
		parts.push(`已移除 ${deleted} 个新建文件`);
	}
	if (dirty) {
		parts.push(`跳过手改路径：${restore.skipped_dirty!.join('、')}`);
	}
	return parts.length ? parts.join('；') : '工作区已是检查点状态';
}

	async function pollSettled(
		sessionId: string,
		rewindId: string,
		timeoutMs = 15_000,
	): Promise<RewindEvent | null> {
		const deadline = Date.now() + timeoutMs;
		let delay = 60;
		while (Date.now() < deadline) {
			try {
				const event = await fetchRewindStatus(sessionId, rewindId);
				if (
					['committed', 'partial', 'failed', 'recovery_required', 'recovery_abandoned'].includes(
						event.status,
					)
				) {
					return event;
				}
			} catch (err) {
				// 确定性 404（rewind_not_found：服务端重启/状态丢失）不是网络抖动：
				// 继续轮询只会把已 commit 的回溯误判成「未确认」并回滚本地列表。
				if (
					err instanceof RollbackRequestError &&
					(err.status === 404 || err.errorType === 'rewind_not_found')
				) {
					return {
						rewind_id: rewindId,
						session_id: sessionId,
						mode: 'continue',
						ts: Date.now() / 1000,
						target_message_id: '',
						checkpoint_id: '',
						orphan_id: '',
						orphan_count: 0,
						retained_row_count: 0,
						idempotency_key: '',
						status: 'failed',
						undone: false,
						error: '回溯状态在服务端已不存在（可能因服务重启）。',
					};
				}
				/* 网络抖动继续轮询，超时则放弃 */
			}
			await new Promise(resolve => setTimeout(resolve, delay));
			delay = Math.min(delay * 1.5, 500);
		}
		return null;
	}

export const useRewindV3Store = create<RewindV3Store>((set, get) => {
	/** 统一 set：写 bySession 并落盘。 */
	const patchSession = (
		sessionId: string,
		patch: Partial<RewindV3BySession>,
	): RewindV3BySession => {
		let next = IDLE;
		set(s => {
			const cur = s.bySession[sessionId] ?? IDLE;
			next = {...cur, ...patch};
			return {bySession: {...s.bySession, [sessionId]: next}};
		});
		if (next.phase === 'idle' || next.settled) {
			// 终态成功 / 已放弃：不再保留截断兜底（避免持久化大对象残留）。
			if (next.settled) {
				next = {...next, suffixBackup: null};
			}
			if (next.phase === 'idle') {
				dropState(sessionId);
				dropLegacyFallback(sessionId);
				return next;
			}
		}
		persistState(sessionId, next);
		return next;
	};

	/** 从持久层恢复某会话的兜底截断并回读进 state（重载对齐用）。 */
	const restoreFromSnapshot = (sessionId: string, s: RewindV3BySession): void => {
		if (!s.suffixBackup || s.suffixBackup.length === 0) {
			return;
		}
		// C4：目标消息文本替换为 editedText，让回滚后可见用户输入内容。
		const restored = [...s.suffixBackup];
		if (restored[0] && restored[0].role === 'user' && s.editedText) {
			restored[0] = {...restored[0], text: s.editedText};
		}
		const current = useChatStore.getState().messagesById[sessionId] ?? [];
		const firstId = restored[0]?.id;
		const overlapIdx = firstId
			? current.findIndex(m => m.id === firstId)
			: -1;
		// 截断后 current 是前缀（无重叠）→ 拼接；若列表已含后缀 → 从重叠点替换。
		const prefix =
			overlapIdx >= 0 ? current.slice(0, overlapIdx) : current;
		const merged = [...prefix, ...restored];
		useChatStore.setState({
			messagesById: {
				...useChatStore.getState().messagesById,
				[sessionId]: merged,
			},
		});
		// 与 confirm 截断对称：回滚也要落 IDB，否则截断态残留在持久层。
		void replaceMessages(sessionId, merged);
	};

	const initialBySession = loadPersisted();

	return {
		bySession: initialBySession,
		pillsBySession: {},

		openDialog(sessionId, targetMessageId, editedText) {
			// 新意图：重置 attemptId/settled/suffixBackup（避免沿用上一次的幂等键与兜底快照）。
			// 上一次未决的失败回溯已回滚到列表，其兜底在此作废；undo 走服务端 rewindId，不依赖本地快照。
			const fresh: RewindV3BySession = {
				...IDLE,
				phase: 'dialog',
				targetMessageId,
				editedText,
				action: null,
				suffixBackup: null,
			};
			patchSession(sessionId, fresh);
			// checkpoint 可用性异步查询：ready → Restore 可用；none → 禁用。
			void fetchRewindCheckpoint(sessionId, targetMessageId)
				.then(lookup => {
					set(s => {
						const cur = s.bySession[sessionId];
						if (!cur || cur.targetMessageId !== targetMessageId || cur.phase !== 'dialog') {
							return s;
						}
						return {
							bySession: {
								...s.bySession,
								[sessionId]: {
									...cur,
									checkpointState: lookup.checkpoint_id ? 'ready' : 'none',
									checkpointId: lookup.checkpoint_id,
									checkpointAnchor: lookup.anchor === true,
								},
							},
						};
					});
				})
				.catch(() => {
					set(s => {
						const cur = s.bySession[sessionId];
						if (!cur || cur.targetMessageId !== targetMessageId || cur.phase !== 'dialog') {
							return s;
						}
						return {
							bySession: {
								...s.bySession,
								[sessionId]: {...cur, checkpointState: 'none'},
							},
						};
					});
				});
		},

		openPillDialog(sessionId, pill) {
			const fresh: RewindV3BySession = {
				...IDLE,
				phase: 'dialog',
				targetMessageId: pill.afterMessageId,
				checkpointState: pill.checkpointId ? 'ready' : 'none',
				checkpointId: pill.checkpointId || null,
				pillRewindId: pill.rewindId,
			};
			patchSession(sessionId, fresh);
		},

		closeDialog(sessionId) {
			patchSession(sessionId, {...IDLE});
		},

		async confirm(sessionId, action) {
			const state = get().bySession[sessionId];
			if (!state?.targetMessageId || state.phase === 'running') {
				return false;
			}
			const targetId = state.targetMessageId;
			const editedText = state.editedText.trim();
			if (action === 'continue' && !editedText) {
				return false;
			}
			const chatState = useChatStore.getState();
			const messages: ChatMessage[] = chatState.messagesById[sessionId] ?? [];
			const targetIdx = messages.findIndex(m => m.id === targetId);

			// 把本地编辑目标对齐到服务端 transcript id（本地 id 可能与后端不一致）。
			// - 命中（id 或唯一文本）→ 用服务端 id 走服务端 rewind；
			// - 服务端完全没有该消息（典型：上一轮厂商报错未落盘）→ 本地截断+重发（不 POST）；
			// - 文本命中多条 → 无法安全定位，明确报错。
			let serverTargetId: string | null = targetId;
			const backendSessionId = activeBackendSessionId(
				useChatStore.getState().historyById,
				sessionId,
			);
			if (backendSessionId) {
				try {
					const serverMessages = await loadServerSessionMessages(backendSessionId);
					if (serverMessages.length && !serverMessages.some(m => m.id === targetId)) {
						const local = targetIdx >= 0 ? messages[targetIdx] : undefined;
						if (local?.role === 'user' && local.text.trim()) {
							const matches = serverMessages.filter(
								m => m.role === 'user' && m.text.trim() === local.text.trim(),
							);
							if (matches.length === 1) {
								serverTargetId = matches[0]!.id;
							} else if (matches.length === 0) {
								// 该轮从未落盘：服务端 rewind 无意义，走本地降级。
								serverTargetId = null;
							} else {
								serverTargetId = targetId; // 保持原 id，交由后端报错并映射友好文案
								patchSession(sessionId, {
									phase: 'error',
									error:
										'找不到可回溯的用户消息：会话中存在多条相同文案，无法唯一定位。请刷新后重试。',
									settled: false,
									recovery: false,
								});
								return false;
							}
						} else {
							serverTargetId = null;
						}
					}
				} catch {
					/* 服务端历史不可达时仍尝试本地 id */
				}
			}
			if (serverTargetId === null && action === 'restore') {
				patchSession(sessionId, {
					phase: 'error',
					error: '该消息在服务端记录中不存在，无法恢复文件检查点。',
					settled: false,
					recovery: false,
				});
				return false;
			}

			// C1：同一确认动作内复用 attemptId（error/重试路径），新意图才新建。
			const reuseAttempt =
				state.attemptId &&
				state.targetMessageId === targetId &&
				state.action === action
					? state.attemptId
					: null;
			const attemptId = reuseAttempt ?? uid('rw');
			const key = idempotencyKey(sessionId, targetId, attemptId, editedText);

			// C2/C3：同帧截断前先把截断后缀冻结并落盘（评审 #3；现在进持久态而非独立 key）。
			let suffixBackup: ChatMessage[] | null = null;
			if (action === 'continue' && targetIdx >= 0) {
				suffixBackup = messages.slice(targetIdx);
				const truncated = messages.slice(0, targetIdx);
				useChatStore.setState({
					messagesById: {
						...chatState.messagesById,
						[sessionId]: truncated,
					},
				});
				// 截断必须落 IDB：否则刷新后 loadSessionMessagesWithBackfill 会用
				// IDB 里的旧全量列表“复活”被回溯掉的消息（服务端 transcript 已截断）。
				void replaceMessages(sessionId, truncated);
			}

			patchSession(sessionId, {
				phase: 'running',
				action,
				error: null,
				attemptId,
				suffixBackup,
				settled: false,
			});

			// C2：任何未达终态成功的退出都回滚列表（C4 用 suffixBackup + editedText）。
			const revertTruncation = () => {
				if (action !== 'continue' || targetIdx < 0 || !suffixBackup) {
					return;
				}
				restoreFromSnapshot(sessionId, {
					...get().bySession[sessionId],
					targetMessageId: targetId,
					editedText,
					suffixBackup,
				});
			};

			// 本地降级：该轮从未落盘（服务端 transcript 无此消息），服务端 rewind 无意义。
			// 直接本地截断 + 重发（文件不回滚，对齐 v2 shouldFallbackToLocalResend 语义）。
			if (serverTargetId === null && action === 'continue') {
				patchSession(sessionId, {
					phase: 'done',
					settled: true,
					rewindId: null,
					recovery: false,
					summary: '服务端无该轮记录，已本地截断并重发（文件未回滚）。',
				});
				dropLegacyFallback(sessionId);
				void get().loadPills(sessionId);
				void useChatStore
					.getState()
					.sendMessage(editedText, [], [])
					.then(ok => {
						if (!ok) {
							setComposerDraft(sessionId, {text: editedText, attachments: []});
						}
					});
				return true;
			}

			const doRewind = async (idKey: string): Promise<boolean> => {
				const result = await rewindHotpath(sessionId, {
					mode: action,
					targetMessageId: serverTargetId ?? targetId,
					checkpointId: state.checkpointId,
					editedText: action === 'continue' ? editedText : null,
					idempotencyKey: idKey,
					confirmed: true,
				});
				patchSession(sessionId, {rewindId: result.rewind_id});
				const settledEvent = await pollSettled(sessionId, result.rewind_id);
				if (settledEvent && settledEvent.status === 'failed') {
					// 服务端确认失败：回滚本地，保留兜底与 rewindId（可撤销）。C2。
					revertTruncation();
					patchSession(sessionId, {
						phase: 'error',
						error: settledEvent.error || '回溯失败',
						settled: false,
						recovery: false,
					});
					return false;
				}
				if (settledEvent && settledEvent.status === 'recovery_required') {
					// §9.2：工作区处于中间态。transcript 已提交 → 保留截断列表，给「重试/放弃」。
					patchSession(sessionId, {
						phase: 'error',
						error:
							settledEvent.error ||
							'工作区未完全恢复，可从检查点重试或放弃。',
						settled: false,
						recovery: true,
					});
					return false;
				}
				// committed / partial / recovery_abandoned（或超时 null）：C5 只有确认终态才算成功。
				if (settledEvent) {
					patchSession(sessionId, {
						phase: 'done',
						settled: true,
						summary: summarizeRestore(settledEvent),
						recovery: false,
						resendPending: false,
					});
					dropLegacyFallback(sessionId);
					void get().loadPills(sessionId);
					if (action === 'continue') {
						// 自动发送（复用输入框链路）；失败则进 resendPending（迁自 v2 committed_resend_failed）。
						void useChatStore
							.getState()
							.sendMessage(editedText, [], [])
							.then(ok => {
								if (!ok) {
									setComposerDraft(sessionId, {text: editedText, attachments: []});
									patchSession(sessionId, {
										phase: 'error',
										settled: true,
										resendPending: true,
										error: '对话已回溯，但重新发送失败。可重试发送或把文案留在输入框。',
									});
								}
							});
					}
					return true;
				}
				// 超时未确认：C2/C5 一律回滚 + 未决可撤销，不判成功。
				revertTruncation();
				patchSession(sessionId, {
					phase: 'error',
					error: '未确认回溯完成，已恢复为回溯前状态；可撤销或稍后重试。',
					settled: false,
					recovery: false,
				});
				return false;
			};

			try {
				try {
					return await doRewind(key);
				} catch (firstErr) {
					// busy：不重试、必回滚列表、弹窗提示（§11-9）。
					if (isSessionBusyError(firstErr)) {
						revertTruncation();
						patchSession(sessionId, {
							phase: 'error',
							error: friendlyRewindError(firstErr),
							settled: false,
							recovery: false,
							resendPending: false,
						});
						return false;
					}
					// C1：可能丢响应（服务端已 commit）；同 key 重放一次取回 rewind_id。
					const retried = await doRewind(key);
					if (retried) {
						return true;
					}
					return false;
				}
			} catch (err) {
				revertTruncation();
				patchSession(sessionId, {
					phase: 'error',
					error: friendlyRewindError(err),
					settled: false,
					resendPending: false,
				});
				return false;
			}
		},

		async retry(sessionId) {
			const state = get().bySession[sessionId];
			if (!state?.targetMessageId || !state?.action) {
				return false;
			}
			// 复用同一 attemptId（同级 confirm 内会识别并复用 → 同 key）。
			return get().confirm(sessionId, state.action);
		},

		async retryResend(sessionId) {
			const st = get().bySession[sessionId];
			const text = st?.editedText?.trim();
			if (!st?.resendPending || !text) {
				return false;
			}
			patchSession(sessionId, {phase: 'running', error: null});
			const ok = await useChatStore.getState().sendMessage(text, [], []);
			if (ok) {
				patchSession(sessionId, {
					phase: 'done',
					settled: true,
					resendPending: false,
					error: null,
					summary: st.summary ?? '已重新发送',
				});
				return true;
			}
			setComposerDraft(sessionId, {text, attachments: []});
			patchSession(sessionId, {
				phase: 'error',
				settled: true,
				resendPending: true,
				error: '重新发送仍失败。可再试，或从输入框手动发送。',
			});
			return false;
		},

		abandon(sessionId) {
			const st = get().bySession[sessionId];
			if (!st) {
				return;
			}
			// recovery 中间态：transcript 已提交，suffixBackup 拼回会制造分叉。
			// 只结束 recovery，保留截断列表（与 recover('abandon') 同语义）。
			if (st.recovery && st.rewindId) {
				patchSession(sessionId, {
					...IDLE,
					phase: 'idle',
					settled: true,
				});
				return;
			}
			if (!st.settled && st.rewindId) {
				// 超时未决：服务端可能已 commit。先确认再决定对齐方向，
				// 盲目恢复本地列表会与已改写的服务端 transcript 永久分叉。
				void (async () => {
					try {
						const ev = await fetchRewindStatus(sessionId, st.rewindId!);
						if (
							['committed', 'partial', 'recovery_abandoned'].includes(ev.status)
						) {
							const backendId = activeBackendSessionId(
								useChatStore.getState().historyById,
								sessionId,
							);
							const server = recoverSessionMessages(
								await loadServerSessionMessages(backendId),
							);
							if (server.messages.length > 0) {
								useChatStore.setState({
									messagesById: {
										...useChatStore.getState().messagesById,
										[sessionId]: server.messages,
									},
								});
								void replaceMessages(sessionId, server.messages);
							}
							patchSession(sessionId, {
								...IDLE,
								phase: 'done',
								settled: true,
								summary: '已与服务端回溯结果对齐。',
							});
							return;
						}
					} catch {
						/* 状态不可达：保留未决态（含 rewindId），刷新后 rehydrate 仍可对齐 */
						const cur = get().bySession[sessionId];
						if (cur && !cur.settled && cur.suffixBackup?.length) {
							restoreFromSnapshot(sessionId, cur);
						}
						patchSession(sessionId, {
							phase: 'error',
							error:
								'无法确认服务端回溯状态；已恢复本地列表，可稍后重试或刷新后对齐。',
							settled: false,
							recovery: false,
						});
						return;
					}
					// 明确未 commit（failed/undone/其它）：旧行为——恢复列表并落定。
					const cur = get().bySession[sessionId];
					if (cur && !cur.settled && cur.suffixBackup?.length) {
						restoreFromSnapshot(sessionId, cur);
					}
					patchSession(sessionId, {
						...IDLE,
						phase: 'idle',
						settled: true,
					});
				})();
				return;
			}
			// 未达服务端 commit 的放弃：恢复截断列表；已 commit 的放弃：保留截断列表。
			if (!st.settled && st.suffixBackup?.length) {
				restoreFromSnapshot(sessionId, st);
			}
			patchSession(sessionId, {
				...IDLE,
				phase: 'idle',
				settled: true,
			});
		},

		async recover(sessionId, action) {
			const st = get().bySession[sessionId];
			const rewindId = st?.rewindId;
			if (!rewindId) {
				return false;
			}
			try {
				await recoverRewind(sessionId, rewindId, action);
			} catch (err) {
				patchSession(sessionId, {
					phase: 'error',
					error: err instanceof Error ? err.message : String(err),
					settled: false,
				});
				return false;
			}
			if (action === 'abandon') {
				// 保留当前磁盘/截断状态，结束 recovery。
				patchSession(sessionId, {
					phase: 'done',
					settled: true,
					recovery: false,
					error: null,
					suffixBackup: null,
				});
				dropLegacyFallback(sessionId);
				return true;
			}
			// retry：服务端回到 restoring，后台线程重跑；轮询到终态。
			patchSession(sessionId, {
				phase: 'running',
				settled: false,
				recovery: false,
				error: null,
			});
			const settled = await pollSettled(sessionId, rewindId);
			if (settled && ['committed', 'partial', 'recovery_abandoned'].includes(settled.status)) {
				patchSession(sessionId, {
					phase: 'done',
					settled: true,
					summary: summarizeRestore(settled),
					recovery: false,
				});
				dropLegacyFallback(sessionId);
				return true;
			}
			if (settled && settled.status === 'recovery_required') {
				patchSession(sessionId, {
					phase: 'error',
					settled: false,
					recovery: true,
					error: settled.error || '工作区仍未完全恢复，可再次重试或放弃。',
				});
				return false;
			}
			if (settled && settled.status === 'failed') {
				patchSession(sessionId, {
					phase: 'error',
					settled: false,
					recovery: false,
					error: settled.error || '重试失败',
				});
				return false;
			}
			// 仍在处理中
			patchSession(sessionId, {phase: 'running', settled: false, recovery: false});
			return false;
		},

		async undoLast(sessionId) {
			const state = get().bySession[sessionId];
			// pill 打开的弹窗只带 pillRewindId（rewindId 恒 null）——两个入口都必须可用。
			const rewindId = state?.rewindId ?? state?.pillRewindId;
			if (!rewindId) {
				return false;
			}
			try {
				await rewindHotpathUndo(sessionId, rewindId);
				patchSession(sessionId, {...IDLE});
				void get().loadPills(sessionId);
				try {
					const cur = useChatStore.getState();
					// undo 后服务端是权威（orphan 已回放，本地可能是截断+新回合的混合）。
					const msgs = await loadSessionMessagesWithBackfill(
						sessionId,
						cur.historyById,
						{preferServer: true},
					);
					useChatStore.setState({
						messagesById: {...useChatStore.getState().messagesById, [sessionId]: msgs},
					});
				} catch {
					/* 消息重载失败不打断 Undo 反馈 */
				}
				return true;
			} catch (err) {
				patchSession(sessionId, {
					phase: 'error',
					error: err instanceof Error ? err.message : String(err),
				});
				return false;
			}
		},

		async loadPills(sessionId) {
			try {
				const events = await fetchRewindEvents(sessionId);
				set(s => ({
					pillsBySession: {...s.pillsBySession, [sessionId]: eventsToPills(events)},
				}));
			} catch {
				/* pill 数据拉取失败不阻断聊天 */
			}
		},

		async rehydrate(sessionId) {
			const cur = get().bySession[sessionId];
			if (!cur || cur.settled) {
				return;
			}
			const reconciled = migrateLegacyFallback(sessionId, cur);
			if (reconciled !== cur) {
				patchSession(sessionId, reconciled);
			}
		const st = get().bySession[sessionId];
		if (!st.rewindId) {
			// running 态且无 rewindId：POST 尚未发出/未返回就中断。恢复列表并给出口，
			// 否则重载后弹窗停在 running（无按钮、ESC/X 被拦）→ 会话永久卡死。
			if (st.phase === 'running' && st.suffixBackup?.length) {
				restoreFromSnapshot(sessionId, st);
				patchSession(sessionId, {
					phase: 'error',
					error: '回溯未完成（页面中断），已恢复列表。可重试或放弃。',
					settled: false,
					recovery: false,
				});
			}
			// 有兜底但无 rewindId：说明上次 POST 后未提交/丢失，保留兜底供撤销/重试。
			return;
		}
		try {
			const ev = await fetchRewindStatus(sessionId, st.rewindId);
			if (['committed', 'partial', 'recovery_abandoned'].includes(ev.status)) {
				const msgs =
					ev.status === 'recovery_abandoned'
						? (useChatStore.getState().messagesById[sessionId] ?? [])
						: await loadSessionMessagesWithBackfill(
								sessionId,
								useChatStore.getState().historyById,
								{preferServer: true},
							);
					useChatStore.setState({
						messagesById: {...useChatStore.getState().messagesById, [sessionId]: msgs},
					});
					patchSession(sessionId, {
						phase: 'done',
						settled: true,
						summary: summarizeRestore(ev),
						suffixBackup: null,
						recovery: false,
					});
					dropLegacyFallback(sessionId);
					// 若 continue 的自动发送没发生（刷新过早），把文案放回输入框，避免丢失。
					if (st.action === 'continue' && st.editedText) {
						setComposerDraft(sessionId, {text: st.editedText, attachments: []});
					}
				} else if (ev.status === 'recovery_required') {
					// §9.2：中间态，transcript 已提交 → 保留截断列表，给「重试/放弃」。
					patchSession(sessionId, {
						phase: 'error',
						error: ev.error || '工作区未完全恢复，可从检查点重试或放弃。',
						settled: false,
						recovery: true,
					});
				} else if (ev.status === 'failed') {
					restoreFromSnapshot(sessionId, st);
					patchSession(sessionId, {
						phase: 'error',
						error: ev.error || '回溯失败',
						settled: false,
						recovery: false,
					});
				} else {
					// 仍在后台：未决态，给出可撤销/稍后重试。
					patchSession(sessionId, {
						phase: 'error',
						error: '后台仍在处理该回溯，可撤销或稍后重试。',
						settled: false,
					});
				}
			} catch {
				// 状态不可达：保留兜底，未决可撤销。
				patchSession(sessionId, {
					phase: 'error',
					error: '回溯状态暂不可达，可撤销或稍后重试。',
					settled: false,
				});
			}
		},
	};
});
