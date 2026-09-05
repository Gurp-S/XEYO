/**
 * preStoreHelpers.ts — shared store helpers retained after slimming.
 * Cross-module shared state / normalizers / types that cannot move without
 * creating a circular import. Behavior unchanged.
 */
import {
	loadServerSessionMessages,
	setWorkspace,
	type AgentDetail,
	type MultiAgentTaskView,
	type SessionAgentMeta,
} from '@/lib/api';
import {
	loadMessages,
	replaceMessages,
	saveRollbackState,
} from '@/lib/db';
import {
	isTransientRollbackPhase,
	legacyStatusToPhase,
	phaseToLegacyStatus,
} from '@/lib/rollbackMachine';
import {
	mergeTranscriptWithLocalThoughts,
} from '@/lib/mergeTranscript';
import type {
	ChatHistoryState,
	ChatMessage,
	ChatSession,
	ChatSpace,
	ChatUsage,
	RollbackPhase,
	RollbackPreviewState,
} from '@/lib/types';
import {
	clearSessionStreamEntry,
	type SessionStreamState,
} from '@/lib/sessionStreams';
import {type AgentMode} from '@/lib/agentMode';
import {type TodoSnapshot} from '@/lib/toolActivity';
import {type SessionGoalState} from '@/lib/api/goals';
import {type JobSnapshot} from '@/lib/api/jobs';
import {
	recoverSessionMessages,
	scheduleThoughtSync,
	shouldPreferServerMessages,
} from './streamHelpers';

/** 清除指定 session 的流状态（HMR / 崩溃 / stop / 刷新遗留）。 */
function clearSessionStreamState(
	sessionStreams: Record<string, SessionStreamState>,
	sessionId: string,
): Record<string, SessionStreamState> {
	return clearSessionStreamEntry(sessionStreams, sessionId);
}

function settleAllSessionTools(
	messagesById: Record<string, ChatMessage[]>,
	skipSessionIds?: Set<string>,
): {
	messagesById: Record<string, ChatMessage[]>;
	dirtySessionIds: string[];
} {
	const out: Record<string, ChatMessage[]> = {};
	const dirtySessionIds: string[] = [];
	for (const [sid, msgs] of Object.entries(messagesById)) {
		if (skipSessionIds?.has(sid)) {
			out[sid] = msgs;
			continue;
		}
		const settled = recoverSessionMessages(msgs);
		out[sid] = settled.messages;
		if (settled.changed) {
			dirtySessionIds.push(sid);
		}
	}
	return {messagesById: out, dirtySessionIds};
}

async function syncWorkspaceRoot(rootPath: string | undefined): Promise<boolean> {
	const path = rootPath?.trim();
	if (!path) {
		return false;
	}
	try {
		await setWorkspace(path);
		return true;
	} catch (err) {
		console.warn('set workspace failed:', err);
		return false;
	}
}

/**
 * 同会话并发去重：selectSession 后台回填 / hydrate 预载 / reattach 可能同时
 * 请求同一 session 的消息合并，共享同一个 promise，避免重复打网络与重复合并。
 */
const sessionLoadInFlight = new Map<string, Promise<ChatMessage[]>>();

/**
 * 只读本地 IDB（不碰网络）。乐观切换的第一步：先给 UI 一个可渲染的转录，
 * 服务端回填在后台继续。任何失败都降级为空数组（回填阶段再补）。
 */
async function loadLocalSessionMessages(sessionId: string): Promise<ChatMessage[]> {
	try {
		return recoverSessionMessages(await loadMessages(sessionId)).messages;
	} catch {
		return [];
	}
}

async function loadSessionMessagesWithBackfill(
	sessionId: string,
	historyById: Record<string, ChatHistoryState>,
	options?: {preferServer?: boolean},
): Promise<ChatMessage[]> {
	const existing = sessionLoadInFlight.get(sessionId);
	if (existing) {
		return existing;
	}
	const promise = (async () => {
		const local = recoverSessionMessages(await loadMessages(sessionId));
		let chosen = local.messages;

		try {
			const backendId = activeBackendSessionId(historyById, sessionId);
			const server = recoverSessionMessages(
				await loadServerSessionMessages(backendId),
			);
			// preferServer：回溯改写服务端 transcript 后，本地/IDB 可能仍持有
			// 截断前的全量旧列表（比服务端“长”），shouldPreferServerMessages
			// 会误选本地 → 被回溯消息复活。此时服务端是权威，必须强制采用。
			if (
				(options?.preferServer && server.messages.length > 0) ||
				shouldPreferServerMessages(local.messages, server.messages)
			) {
				chosen = mergeTranscriptWithLocalThoughts(
					server.messages,
					local.messages,
				);
				void replaceMessages(sessionId, chosen);
				scheduleThoughtSync(backendId, chosen);
			} else if (local.changed) {
				void replaceMessages(sessionId, local.messages);
			}
		} catch {
			if (local.changed) {
				void replaceMessages(sessionId, local.messages);
			}
		}

		return chosen;
	})().finally(() => {
		sessionLoadInFlight.delete(sessionId);
	});
	sessionLoadInFlight.set(sessionId, promise);
	return promise;
}

function activeBackendSessionId(
	historyById: Record<string, ChatHistoryState>,
	sessionId: string,
): string {
	return (
		normalizeChatHistoryState(historyById[sessionId], sessionId).activeBranch
			.backendSessionId ?? sessionId
	);
}

function defaultChatHistoryState(backendSessionId?: string): ChatHistoryState {
	return {
		activeBranch: {
			branchId: 'root',
			backendSessionId,
			parentBranchId: null,
			createdAt: 0,
			forkMessageId: null,
			label: '主线',
		},
		archivedBranches: [],
	};
}

function normalizeChatHistoryState(
	raw: ChatHistoryState | null | undefined,
	backendSessionId?: string,
): ChatHistoryState {
	if (!raw?.activeBranch?.branchId) {
		return defaultChatHistoryState(backendSessionId);
	}
	return {
		activeBranch: {
			branchId: raw.activeBranch.branchId,
			backendSessionId:
				raw.activeBranch.backendSessionId ?? backendSessionId,
			parentBranchId: raw.activeBranch.parentBranchId ?? null,
			createdAt: Number.isFinite(raw.activeBranch.createdAt)
				? raw.activeBranch.createdAt
				: 0,
			forkMessageId: raw.activeBranch.forkMessageId ?? null,
			label: raw.activeBranch.label || '主线',
		},
			archivedBranches: Array.isArray(raw.archivedBranches)
				? raw.archivedBranches
						.filter(
							branch => Boolean(branch?.branchId) && Array.isArray(branch.messages),
						)
						.map(branch => ({
							...branch,
							backendSessionId: branch.backendSessionId ?? backendSessionId,
						}))
				: [],
	};
}

function withRollbackPhase(
	state: Partial<RollbackPreviewState>,
	phase: RollbackPhase,
	patch: Partial<RollbackPreviewState> = {},
): RollbackPreviewState {
	const base: RollbackPreviewState = {
		status: 'idle',
		phase: 'idle',
		targetMessageId: null,
		editedText: '',
		plan: null,
		job: null,
		idempotencyKey: null,
		error: null,
		restoreWorkspace: null,
		autoContinue: null,
		...state,
		...patch,
	};
	return {
		...base,
		phase,
		status: phaseToLegacyStatus(phase),
	};
}

function idleRollbackState(): RollbackPreviewState {
	return withRollbackPhase({}, 'idle');
}

function normalizeRollbackState(
	state: RollbackPreviewState | null | undefined,
): RollbackPreviewState {
	if (!state) {
		return idleRollbackState();
	}
	const phase = state.phase ?? legacyStatusToPhase(state.status);
	return withRollbackPhase(state, phase);
}

function isTransientRollbackState(
	state: RollbackPreviewState | null | undefined,
): boolean {
	if (!state) {
		return false;
	}
	const phase = state.phase ?? legacyStatusToPhase(state.status);
	return isTransientRollbackPhase(phase);
}

function persistRollback(
	sessionId: string,
	state: RollbackPreviewState,
): void {
	void saveRollbackState(sessionId, normalizeRollbackState(state)).catch(err => {
		console.warn('persist rollback state failed:', err);
	});
}

const activeDrains = new Map<
	string,
	{commit: () => void; discard: () => void}
>();

function commitDrainForSession(sessionId: string): void {
	const drain = activeDrains.get(sessionId);
	if (drain) {
		drain.commit();
		activeDrains.delete(sessionId);
	}
}

function discardDrainForSession(sessionId: string): void {
	const drain = activeDrains.get(sessionId);
	if (drain) {
		drain.discard();
		activeDrains.delete(sessionId);
	}
}

export type SessionUsageView = ChatUsage & {
	usdLimit: number | null;
};

export type PendingPermissionInfo = {
	requestId: string;
	toolName: string;
	prompt: string;
	reason: string;
	sessionId: string;
	/** 三选 peer ASK：deny / remind / allow。 */
	choices?: string[];
	peerSummary?: string;
	/** T3 渲染意图：confirm（普通确认）/ choice（三选冲突）。 */
	intent?: string;
	/** T3 到期时间（epoch 秒）；null/undefined = 不超时。 */
	expiresAt?: number | null;
};

export type PendingAskInfo = {
	requestId: string;
	question: string;
	options: string[];
	default?: string | null;
	expiresAt?: number | null;
	sessionId: string;
};

export type PendingPlanInfo = {
	requestId: string;
	plan: string;
	sessionId?: string;
	turnId?: string;
	expiresAt?: number | null;
};

/** 视图历史栈的基准项：主对话视图。 */
export const AGENT_VIEW_MAIN = 'main';

/**
 * 多 Agent 浏览状态（浏览器式 上一个/下一个）。
 * 栈项为 'main' 或 agentId；点击卡片 = 前进式入栈（截断 forward 分支）；
 * 箭头只移动指针，不重复入栈（与浏览器一致）。
 */
type MultiAgentNav = {
	agentViewStack: string[];
	agentViewIndex: number;
};

function initAgentNav(): MultiAgentNav {
	return {agentViewStack: [AGENT_VIEW_MAIN], agentViewIndex: 0};
}

/** 从 nav 状态解析当前视图：null = 主对话。 */
export function currentAgentView(nav: MultiAgentNav): string | null {
	const cur = nav.agentViewStack[nav.agentViewIndex];
	return cur && cur !== AGENT_VIEW_MAIN ? cur : null;
}

/** P1 mid-turn inbox：一条排队中的用户消息（后端 202 返回；GUI 渲染 chip）。 */
export type InboxQueuedItem = {
	queue_id: string;
	text: string;
	media_refs: string[];
	message_id: string | null;
	queued_at: number;
	attempts: number;
	state: 'queued' | 'delivering' | 'stuck';
	position: number;
};

export type ChatState = {
	hydrated: boolean;	spaces: ChatSpace[];
	sessions: ChatSession[];
	activeId: string | null;
activeSpaceId: string;
	collapsedSpaces: Record<string, boolean>;
	messagesById: Record<string, ChatMessage[]>;
	/**
	 * 消息仍在后台装载的 session（乐观切换：activeId 已就位、消息未到）。
	 * UI 据此渲染等待骨架，而不是把冷会话误当空对话闪 EmptyState。
	 */
	messagesLoadingIds: Record<string, true>;
	historyById: Record<string, ChatHistoryState>;
	/**
	 * 每个 session 的实时 TodoWrite 清单（镜像后端 AppState.todos）。
	 * 在 tool_call/tool_result 时更新；transcript 仍是持久化来源。
	 */
	sessionTodosById: Record<string, TodoSnapshot | null>;
	/**
	 * 41 号：每个 session 的 goal + round-driver 投影（whole-value）。
	 * 双源写入：SSE goal 帧（turn 起点）+ GET 轮询/动词响应；终态
	 * （completed/abandoned）保留记录但 Dock 不渲染。
	 */
	sessionGoalById: Record<string, SessionGoalState | null>;
	/**
	 * 42 号：每个 session 的后台任务 whole-value 快照。
	 * 双源写入：SSE jobs 帧（turn 起点播种）+ GET 轮询；last-wins，
	 * 空集 = 删除键（缺失与 [] 同一表示，消费方永不测哨兵）。
	 */
	sessionJobsById: Record<string, JobSnapshot[]>;
	/**
	 * P1 mid-turn inbox：每个 session 的排队消息快照（会话忙时后端 202 排队，
	 * settle 后自动投递）。GUI 据此渲染 Composer chip；轮询刷新、可逐条取消。
	 */
	inboxBySession: Record<string, InboxQueuedItem[]>;
	/** 当前会话是否有可见的排队 chip（Composer 渲染开关）。 */
	hasInboxChip: boolean;
	setHasInboxChip: (v: boolean) => void;
	/** 刷新某会话的排队快照（2s 轮询；队空 = 已投递/取消 → 清 chip）。 */
	refreshInbox: (sessionId: string) => Promise<void>;
	/** 取消一条排队消息（服务端 DELETE 成功后从本地移除）。 */
	cancelInboxItem: (sessionId: string, queue_id: string) => Promise<void>;
	editInboxItem: (sessionId: string, queue_id: string, text: string) => Promise<void>;
	/** 清空当前会话排队 chip 状态。 */
	clearInboxChip: () => void;
		/** 每个 session 整个对话累计的厂商 usage，随会话持久化。 */
	sessionUsageById: Record<string, SessionUsageView | null>;
	/** 每个 session 的回溯预览、确认和恢复作业状态。 */
	rollbackById: Record<string, RollbackPreviewState>;
	/** 当前待确认的权限请求（PermissionDialog 渲染）。 */
	pendingPermission?: PendingPermissionInfo | null;
	/** 设置待确认权限，并持久化到 localStorage（跨刷新恢复）。 */
	setPendingPermission?: (value: PendingPermissionInfo | null) => void;
	/** 当前待作答的用户提问（AskUserDialog 渲染）。 */
	pendingAsk?: PendingAskInfo | null;
	/** 设置待作答提问（不持久化：属于实时流内状态）。 */
	setPendingAsk?: (value: PendingAskInfo | null) => void;
	/** 当前待确认的 Plan 模式计划（PlanDialog 渲染）。 */
	pendingPlan?: PendingPlanInfo | null;
	/** 设置待确认计划（不持久化：属于实时流内状态）。 */
	setPendingPlan?: (value: PendingPlanInfo | null) => void;
	/** Composer 当前会话 Agent 模式：agent / plan / ask。 */
	agentMode: AgentMode;
	/** 设置 Composer Agent 模式；发送时随请求传给后端。 */
	setAgentMode: (mode: AgentMode) => void;
	/** 每个 session 独立的流式 / 排水状态（支持并行对话）。 */
	sessionStreams: Record<string, SessionStreamState>;
	/** 输入框上方临时横幅（401 / 网络 / 无密钥）。不擦除历史。 */
	errorBanner: string | null;
	/** 错误横幅所属 session；null 表示全局（如远程镜像）。 */
	errorBannerSessionId: string | null;
	sidebarOpen: boolean;
	/** 沉浸模式（P3-⑫）：隐藏侧边栏/工作区/用量，仅保留对话；入口在「XEYO CHAT」面板。 */
	immersive: boolean;
	searchFocusSeq: number;
	/** 预览选区 / 文件引用插入输入框时递增。 */
	composerInsertSeq: number;
	lastComposerInsert: {
		name: string;
		text?: string;
		path?: string;
	} | null;
	/** 输入框聚焦（预览 Add to Chat 后）。 */
	composerFocusSeq: number;
	/** 新建聊天聚焦空 session 时递增 — 空态 hero 重新随机俏皮话。 */
	emptyQuipSeq: number;

	/** 多 Agent：进行中/最近一批子任务卡片（key = 本地 sessionId；SSE 实时更新）。 */
	multiAgentTasksBySession: Record<string, MultiAgentTaskView[]>;
	/** 多 Agent：会话跑过的子 agent 元数据（服务端侧链 meta，含历史批）。 */
	agentsBySession: Record<string, SessionAgentMeta[]>;
	/** 子 agent transcript 缓存（key = `${sessionId}::${agentId}`；null = 最近一次拉取失败，允许重试）。 */
	agentTranscriptsById: Record<string, AgentDetail | null>;
	/**
	 * 子 agent 运行中的 token 级增量缓冲（key 同上）。
	 * 渲染时按快照 assistant 文本总长对齐截尾：`buf.slice(snapLen)`；
	 * 任务落定由 finalizeAgentStream 刷快照后清空，实现无缝续接。
	 */
	liveAgentTextById: Record<string, string>;

	/** 多 Agent 浏览：视图历史栈 + 当前指针（浏览器式 上一个/下一个）。 */
	agentViewStack: string[];
	agentViewIndex: number;
	pushAgentView: (agentId: string) => void;
	backAgentView: () => void;
	forwardAgentView: () => void;
	resetAgentView: () => void;
	/** 点击卡片进入子视图（确保栈语义正确），并预取 transcript。 */
	openAgentView: (agentId: string) => void;
	/** 拉取会话的子 agent 元数据列表并合并进卡片（幂等）。 */
	loadAgentsFor: (sessionId: string) => Promise<void>;
	/**
	 * 拉取子 agent 侧链对话。已有终态快照时直接复用；
	 * `force` 跳过缓存（运行中轮询用）。失败不落永久缓存，
	 * 避免把「运行中还没写盘」误缓存成空记录。
	 */
	ensureAgentTranscript: (
		sessionId: string,
		agentId: string,
		opts?: {force?: boolean},
	) => Promise<void>;
	/** 追加子 agent 输出增量（SSE multi_agent_delta；运行中逐字回放用）。 */
	appendAgentDelta: (sessionId: string, agentId: string, text: string) => void;
	/**
	 * 任务落定（done/failed）：强制刷新 transcript 快照（此时侧链已完整），
	 * 然后清掉增量缓冲 —— 完成从「流式缓冲」到「持久化快照」的无缝交接。
	 */
	finalizeAgentStream: (sessionId: string, agentId: string) => Promise<void>;
	/** 取消运行中的单个子 Agent。 */
	cancelAgentTask: (sessionId: string, agentId: string) => Promise<boolean>;
	/** 失败/取消后按原任务重跑同一 agent_id。 */
	retryAgentTask: (sessionId: string, agentId: string) => Promise<boolean>;

	hydrate: () => Promise<void>;
	setSidebarOpen: (open: boolean) => void;
	setImmersive: (open: boolean) => void;
	requestSearchFocus: () => void;
	requestComposerInsert: (file: {
		name: string;
		text?: string;
		path?: string;
	}) => void;
	requestComposerFocus: () => void;
	setActiveSpace: (spaceId: string) => Promise<void>;
	toggleSpaceCollapsed: (spaceId: string) => void;
	/** 将文件夹打开为工作区。按路径幂等。 */
	openFolder: (rootPath: string) => Promise<string>;
	/**
	 * 聚焦工作区：最新 session，或若无则新建空聊天。
	 * @returns 要导航到的 session id
	 */
	enterSpace: (spaceId: string) => Promise<string>;
	removeSpace: (spaceId: string) => Promise<void>;
	renameSpace: (spaceId: string, name: string) => Promise<void>;
	createSession: (spaceId?: string) => Promise<string>;
	/** 侧聊会话：side- 前缀 id + 虚拟 space；后端 body.side 走只读模式。 */
	createSideSession: () => Promise<string>;
	selectSession: (id: string) => Promise<void>;
	removeSession: (id: string) => Promise<void>;
	/** smoke-test #3：会话改名——写服务端 pinned sidecar，本地同步 title。 */
	renameSession: (id: string, title: string) => Promise<void>;
	/** smoke-test #3：分叉会话——服务端复制 transcript 到新 sid；本地建行并返回新会话 id。 */
	forkSession: (id: string) => Promise<string>;
	/** smoke-test #3：归档会话——服务端写 archive sidecar；本地标记 archived（默认列表隐藏）。 */
	archiveSession: (id: string) => Promise<void>;
	/** smoke-test #3：找回已归档会话——服务端清 sidecar，本地取消 archived 标记。 */
	restoreSession: (id: string) => Promise<void>;
	/** @returns 用户消息是否已被 UI 接受 */
	sendMessage: (
		text: string,
		mediaRefs?: string[],
		mediaPreviewUrls?: string[],
		agentMode?: AgentMode,
		onAccepted?: () => void,
		multiAgent?: boolean,
		opts?: {
			sessionId?: string;
			background?: boolean;
			/** 会话输入框手动选的思考等级；优先级最高（与 streamSendSlice 实现对齐）。 */
			reasoningEffort?: string;
		},
	) => Promise<boolean>;
	/**
	 * 向另一会话后台发送并开跑；不切换 activeId。
	 * 供 XeyoUI send_to_session 旁路调用。
	 */
	sendToSession: (sessionId: string, text: string) => Promise<boolean>;
	/** 镜像微信远程入站/出站到当前对话（不触发新的模型请求） */
	appendRemoteMessage: (role: 'user' | 'assistant', text: string) => void;
	/** 追加一条 UI-only 系统行（斜杠命令回执）；不进 toApiMessages、不持久化。 */
	appendLocalNote: (text: string, opts?: {kind?: 'cmd'; title?: string}) => void;
	syncRemoteStream: (text: string, status?: string) => void;
	applyRemoteToolCall: (name: string, input: unknown) => void;
	applyRemoteToolResult: (
		name: string,
		output: string,
		isError?: boolean,
	) => void;
	commitRemoteStream: (text: string) => void;
	finishRemoteStream: () => void;
	stopGeneration: () => Promise<void>;
	clearErrorBanner: () => void;
	/** 崩溃 / HMR / 硬刷新遗留后清除幽灵 isLoading。 */
	recoverStuckStream: () => void;
	/** 查询后端 task；若仍 running 则 reattach，若 recovery_required 则展示条。 */
	reattachActiveStreams: () => Promise<void>;
	reattachStream: (sessionId: string) => Promise<boolean>;
	/** 进程重启后需用户确认续跑。 */
	recoveryBySession: Record<
		string,
		{goalText: string; turnId: string; stopReason: string}
	>;
	continueRecovery: (sessionId: string) => Promise<void>;
	abandonRecovery: (sessionId: string) => Promise<void>;
};

export {
	activeBackendSessionId,
	activeDrains,
	clearSessionStreamState,
	commitDrainForSession,
	defaultChatHistoryState,
	discardDrainForSession,
	idleRollbackState,
	initAgentNav,
	isTransientRollbackState,
	loadLocalSessionMessages,
	loadSessionMessagesWithBackfill,
	normalizeChatHistoryState,
	normalizeRollbackState,
	persistRollback,
	settleAllSessionTools,
	syncWorkspaceRoot,
	withRollbackPhase,
};
export type {MultiAgentNav};
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
} from './streamHelpers';
