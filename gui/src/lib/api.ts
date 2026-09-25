import {useSettingsStore} from '@/stores/settingsStore';
import {apiUrl} from '@/lib/apiBase';
import type {ChatMessage, RecoveryJob, RewindCheckpointLookup, RewindEvent, RewindHotpathResult, RollbackPlan} from './types';
import {REQUEST_TIMEOUT_MS, authHeaders, fetchWithTimeout, formatErrorDetail} from './api/core';
import type {} from './api/core';
import type {ServerSession, SessionAgentMeta} from './api/chatStream';
export {VENDOR_CONTEXT_LIMIT_KEY, fetchUsage, fetchUsageBalance, fetchVendorModels, getCachedModelContextLimit, healthCheck, loadVendorContextLimits, persistVendorContextLimits, rememberVendorContextLimits, vendorContextLimitCache, vendorModelCacheKey} from './api/usage';
export type {UsageBalance, UsageBucket, UsageDayPoint, UsageModelBlock, UsageReport, VendorModel, VendorModelMode, VendorModelsReport} from './api/usage';
export {uploadFile, uploadMedia} from './api/uploads';
export {listPermissionGrants, resolveAsk, resolveFailureText, resolvePermission, resolvePlan, revokeFailureText, revokePermissionGrant} from './api/permissions';
export type {PermissionGrantInfo, ResolveReceipt} from './api/permissions';
export {requestManualCompact, syncUiThoughtsToServer} from './api/memory';
export {
	getLocalModelLog,
	getLocalModels,
	setLocalModelSettings,
	startLocalModel,
	stopLocalModel,
	switchLocalModel,
} from './api/localModels';
export type {
	LocalModelEntry,
	LocalModelSettings,
	LocalModelSettingsPatch,
	LocalModelState,
	LocalModelStatus,
	LocalModelsSnapshot,
} from './api/localModels';
export {setSessionRuntimeMode} from './api/runtimeMode';
export {fetchSkills} from './api/skills';export type {SkillInfo, SkillSource, SkillsReport} from './api/skills';
export {fetchFileReferences} from './api/references';
export type {FileReferencesReport} from './api/references';
export {
	cancelDiagExperiment,
	deleteDiagPin,
	fetchDiagCapture,
	fetchDiagMessage,
	fetchDiagPins,
	fetchDiagReportMarkdown,
	fetchDiagRun,
	fetchDiagRunEvents,
	fetchDiagRuns,
	listDiagExperiments,
	parseRunDetail,
	parseRunsResult,
	pinDiagRun,
	planDiagExperiment,
	recordDiagVerifier,
	setDiagCapture,
	startDiagExperiment,
	traceDiagFact,
} from './api/diagnostics';
export type {
	DiagAttempt,
	DiagAttribution,
	DiagBoundary,
	DiagCaptureState,
	DiagCoverageEntry,
	DiagEvent,
	DiagEvidenceRef,
	DiagFactStage,
	DiagFactTrace,
	DiagFinding,
	DiagModelRequest,
	DiagPermission,
	DiagPin,
	DiagPinInput,
	DiagRawResult,
	DiagRunDetail,
	DiagRunListItem,
	DiagRunsResult,
	DiagToolCall,
	DiagUsageRow,
	DiagUsageSummary,
	DiagWindow,
	DiagGap,
} from './api/diagnostics';
export {readTurnCursor, rememberTurnCursor, streamChat, streamTurnEvents} from './api/chatStream';
export type {ServerSession, SessionAgentMeta} from './api/chatStream';
export {MEDIA_REF_RE, REQUEST_TIMEOUT_MS, STREAM_IDLE_TIMEOUT_MS, authHeaders, createStreamWatchdog, fetchWithTimeout, formatErrorDetail, mediaUrl, parseOpenAiSse, parseSseBlock, readIdentity} from './api/core';
export type {AskQuestion, AskQuestionOption, AskUserPendingStreamEvent, AskUserResolvedStreamEvent, ChatApiMessage, ChatRequestOptions, ChatStreamHandlers, CompressionStreamEvent, SteerDeliveredStreamEvent, EventIdentity, MultiAgentDeltaStreamEvent, MultiAgentProgressStreamEvent, MultiAgentResultStreamEvent, MultiAgentStatusStreamEvent, MultiAgentTaskStreamEvent, MultiAgentTaskView, ParsedSse, PermissionPendingStreamEvent, PermissionResolvedStreamEvent, PlanPendingStreamEvent, PlanResolvedStreamEvent, ReasoningStreamEvent, SseTermination, StreamWatchdog, TaskStateStreamEvent, ToolCallStreamEvent, ToolProgressStreamEvent, ToolResultStreamEvent, UsageStreamEvent} from './api/core';

export async function listSessionAgents(sessionId: string): Promise<SessionAgentMeta[]> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/agents`),
			{cache: 'no-store'},
		);
		if (!res.ok) return [];
		const payload = (await res.json()) as {agents?: SessionAgentMeta[]};
		return Array.isArray(payload.agents) ? payload.agents : [];
	} catch {
		return [];
	}
}

/** 子 agent 对话行（与主 transcript ChatMessage 同构的子集）。 */
export type AgentDetailMessage = {
	id: string;
	role: 'user' | 'assistant' | 'tool';
	text: string;
	toolName?: string;
	toolUseId?: string;
	toolInput?: string;
	toolStatus?: 'running' | 'done' | 'error';
	isThought?: boolean;
	reasoningBefore?: string;
	thoughtMs?: number;
	mediaRefs?: string[];
	createdAt: number;
};

export type AgentDetail = {
	status: string;
	messages: AgentDetailMessage[];
};

/** 读取一个子 agent 的完整侧链对话（点击卡片进入子视图时拉取）。 */
export async function loadAgentDetail(
	sessionId: string,
	agentId: string,
): Promise<AgentDetail | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(
				`/v1/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}`,
			),
			{cache: 'no-store'},
		);
		if (!res.ok) return null;
		const payload = (await res.json()) as {
			status?: string;
			messages?: AgentDetailMessage[];
		};
		return {
			status: String(payload.status ?? 'done'),
			messages: Array.isArray(payload.messages) ? payload.messages : [],
		};
	} catch {
		return null;
	}
}

/** 取消运行中的单个子 Agent。 */
export async function cancelSessionAgent(
	sessionId: string,
	agentId: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(
				`/v1/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}/cancel`,
			),
			{method: 'POST', headers: {...authHeaders()}},
		);
		return res.ok;
	} catch {
		return false;
	}
}

export type AgentRetryResult = {
	ok: boolean;
	agentId: string;
	status: 'done' | 'failed';
	resultPreview: string;
};

/** 按 meta.task_desc 清侧链后重跑同一 agent_id。 */
export async function retrySessionAgent(
	sessionId: string,
	agentId: string,
): Promise<AgentRetryResult | null> {
	try {
		const s = useSettingsStore.getState();
		const res = await fetchWithTimeout(
			apiUrl(
				`/v1/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}/retry`,
			),
			{
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...authHeaders(),
					...(s.provider ? {'X-Provider': s.provider} : {}),
				},
				body: JSON.stringify({
					provider: s.provider || undefined,
					model: s.model || undefined,
					base_url: s.baseUrl || undefined,
				}),
			},
			120_000,
		);
		if (!res.ok) return null;
		const payload = (await res.json()) as {
			ok?: boolean;
			agent_id?: string;
			status?: string;
			resultPreview?: string;
			is_error?: boolean;
		};
		const failed = Boolean(payload.is_error) || payload.status === 'failed';
		return {
			ok: Boolean(payload.ok) && !failed,
			agentId: String(payload.agent_id || agentId),
			status: failed ? 'failed' : 'done',
			resultPreview: String(payload.resultPreview || ''),
		};
	} catch {
		return null;
	}
}

// ---------------------------------------------------------------------------
// P1 mid-turn inbox（主会话排队）+ P2 子 agent follow-up inbox
// ---------------------------------------------------------------------------
export type InboxItem = {
	queue_id: string;
	text: string;
	media_refs: string[];
	message_id: string | null;
	queued_at: number;
	attempts: number;
	state: string;
	position: number;
	delivery_id?: string | null;
};

export type InboxSnapshot = {
	autorun: boolean;
	coalesce: boolean;
	items: InboxItem[];
};

/** 主会话 inbox 快照（GUI 轮询驱动 chip）。 */
export async function inboxSnapshot(sessionId: string): Promise<InboxSnapshot | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox`),
			{cache: 'no-store'},
		);
		if (!res.ok) return null;
		return (await res.json()) as InboxSnapshot;
	} catch {
		return null;
	}
}

/** 确认 GUI 已同步投递完成的消息记录。 */
export async function acknowledgeInboxItems(
	sessionId: string,
	queueIds: string[],
): Promise<boolean> {
	if (queueIds.length === 0) return true;
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/ack`),
			{
				method: 'POST',
				headers: {'Content-Type': 'application/json', ...authHeaders()},
				body: JSON.stringify({queue_ids: queueIds}),
			},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** 取消一条排队消息。 */
export async function cancelInboxItem(sessionId: string, queueId: string): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/${encodeURIComponent(queueId)}`),
			{method: 'DELETE', headers: {...authHeaders()}},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** 改写一条排队消息的文本（排队卡「编辑」动作）。 */
export async function editInboxItem(
	sessionId: string,
	queueId: string,
	text: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/${encodeURIComponent(queueId)}`),
			{
				method: 'PATCH',
				headers: {'Content-Type': 'application/json', ...authHeaders()},
				body: JSON.stringify({text}),
			},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** 重新 arm（stop 后 / stuck 后手动投递）。 */
export async function resumeInbox(
	sessionId: string,
	queueId?: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(
				queueId
					? `/v1/sessions/${encodeURIComponent(sessionId)}/inbox/${encodeURIComponent(queueId)}/resume`
					: `/v1/sessions/${encodeURIComponent(sessionId)}/inbox/resume`,
			),
			{method: 'POST', headers: {...authHeaders()}},
		);
		return res.ok;
	} catch {
		return false;
	}
}

export type AgentInboxPostResult = {
	ok?: boolean;
	deliver?: 'running' | 'pending';
	inboxCount?: number;
};

/** 向一个子 agent 投递 follow-up（park 而非注入）。 */
export async function postAgentInbox(
	sessionId: string,
	agentId: string,
	text: string,
): Promise<AgentInboxPostResult | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}/inbox`),
			{
				method: 'POST',
				headers: {'Content-Type': 'application/json', ...authHeaders()},
				body: JSON.stringify({text}),
			},
		);
		if (!res.ok) return null;
		return (await res.json()) as AgentInboxPostResult;
	} catch {
		return null;
	}
}

/** 取消一条 follow-up。 */
export async function cancelAgentInbox(sessionId: string, agentId: string, itemId: string): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}/inbox/${encodeURIComponent(itemId)}`),
			{method: 'DELETE', headers: {...authHeaders()}},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** 列出后端磁盘（用户会话清单）中的会话，供本地索引缺失时恢复历史。 */
export async function listServerSessions(): Promise<ServerSession[]> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/sessions'));
		if (!res.ok) return [];
		const payload = (await res.json()) as {sessions?: ServerSession[]};
		return payload.sessions ?? [];
	} catch {
		return [];
	}
}

/** 列出归属指定工作区路径的会话（后端 ws_index 归属映射）。
 *
 * 用于重开同一文件夹时把「移除工作区」时迁往默认分区的会话挂回来。 */
export async function listWorkspaceSessions(cwd: string): Promise<ServerSession[]> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/workspaces/sessions?cwd=${encodeURIComponent(cwd)}`),
		);
		if (!res.ok) return [];
		const payload = (await res.json()) as {sessions?: ServerSession[]};
		return payload.sessions ?? [];
	} catch {
		return [];
	}
}

/** 按精确 session_id 读取 transcript 消息（含真实时间戳）。 */
/** 把后端富化的 Resume 提示还原为原始 cue（P0-③ 泄漏修复）。

续跑时后端会把富化 prompt（``[Resume] The user asked to continue…`` +
``Original goal:`` + ``Last stop reason:`` + ``User cue:``）作为本条 user 消息
正文持久化进 transcript。实时乐观气泡显示「继续」，但服务端对账（断流/刷新/
backfill/恢复）会把它渲染成可见气泡。这里把 ``^\[Resume\]`` 开头的 user 消息
还原为 ``User cue:`` 的内容，避免英文富化文本泄漏到用户可见 UI。

仅对「以 [Resume] 开头且含 User cue:」的文本生效；其余原样返回。
*/
function restoreResumeUserCue(text: string): string {
	const raw = text ?? '';
	if (/^\[Resume\]/.test(raw.trimStart())) {
		const cue = /User cue:\s*([\s\S]*)$/.exec(raw);
		if (cue && cue[1]?.trim()) {
			return cue[1].trim();
		}
	}
	return raw;
}

function stripResumeFromMessages(messages: ChatMessage[]): ChatMessage[] {
	return messages.map(m =>
		m.role === 'user' && /^\[Resume\]/.test((m.text ?? '').trimStart())
			? {...m, text: restoreResumeUserCue(m.text ?? '')}
			: m,
	);
}

export async function loadServerSessionMessages(
	sessionId: string,
): Promise<ChatMessage[]> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/messages`),
		);
		if (!res.ok) return [];
		const payload = (await res.json()) as {
			messages?: ChatMessage[];
		};
		return stripResumeFromMessages(payload.messages ?? []);
	} catch {
		return [];
	}
}

export type SessionCompression = {
	session_id: string;
	c2_gate: boolean;
	l5_mode: string;
	active: boolean;
	compact_cursor: number;
	last_action: string;
	turns_since_c2: number;
	c2_summary_chars: number;
	c2_summary_preview: string;
};

/**
 * 压缩态读取的回执。旧签名 `Promise<SessionCompression | null>` 把三种情况压成一种：
 * HTTP 失败、离线、200 但形状变了。用量浮标于是按 `compression?.compact_cursor ?? usage?.… ?? 0`
 * 逐级回落 —— 一个没读到的字段会被渲染成"这轮还没压缩过（0）"。
 */
export type SessionCompressionRead = {
	ok: boolean;
	data: SessionCompression | null;
	message: string;
};

function isFiniteNumber(v: unknown): v is number {
	return typeof v === 'number' && Number.isFinite(v);
}

/** 后端固定回这 9 个键（无 ok 信封）；数值/布尔类缺任何一个都算没读到。 */
function parseCompression(payload: unknown): SessionCompression | null {
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
	const b = payload as Record<string, unknown>;
	if (typeof b.session_id !== 'string') return null;
	if (typeof b.c2_gate !== 'boolean' || typeof b.active !== 'boolean') return null;
	if (
		!isFiniteNumber(b.compact_cursor) ||
		!isFiniteNumber(b.turns_since_c2) ||
		!isFiniteNumber(b.c2_summary_chars)
	) {
		return null;
	}
	return {
		session_id: b.session_id,
		c2_gate: b.c2_gate,
		l5_mode: typeof b.l5_mode === 'string' ? b.l5_mode : '',
		active: b.active,
		compact_cursor: b.compact_cursor,
		last_action: typeof b.last_action === 'string' ? b.last_action : '',
		turns_since_c2: b.turns_since_c2,
		c2_summary_chars: b.c2_summary_chars,
		c2_summary_preview: typeof b.c2_summary_preview === 'string' ? b.c2_summary_preview : '',
	};
}

/** 本会话 C2 压缩态（用量预览）。 */
export async function fetchSessionCompression(
	sessionId: string,
): Promise<SessionCompressionRead> {
	const sid = sessionId.trim();
	if (!sid) {
		return {ok: false, data: null, message: 'no_session'};
	}
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sid)}/compression`),
			{cache: 'no-store'},
		);
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		const data = parseCompression(payload);
		return data
			? {ok: true, data, message: ''}
			: {ok: false, data: null, message: 'receipt_bad_compression'};
	} catch (err) {
		return {
			ok: false,
			data: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export type InterruptWrite = {ok: boolean; message: string};

/**
 * 请求后端中断本会话正在跑的回合。回执必须读：
 * 旧实现 `catch {}` + 不看 res.ok，于是 401/404/500 与断网一律"成功"，
 * 界面写「已停止」而后端仍在跑并继续写 transcript。
 * `ok:false` 有两种：后端回答"该会话没有可中断的回合"（not_running），
 * 以及根本读不出回执（网络 / HTTP / 回执形状）—— 界面对这两者说法不同。
 */
export async function interruptChat(sessionId: string): Promise<InterruptWrite> {
	const sid = sessionId.trim();
	if (!sid) {
		return {ok: false, message: 'no_session'};
	}
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/interrupt'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({session_id: sid}),
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, message: 'receipt_not_object'};
		}
		const ok = (payload as Record<string, unknown>).ok;
		if (typeof ok !== 'boolean') {
			return {ok: false, message: 'receipt_missing_ok'};
		}
		return {ok, message: ok ? '' : 'not_running'};
	} catch (err) {
		return {ok: false, message: err instanceof Error ? err.message : String(err)};
	}
}

export type SessionTaskInfo = {
	ok: boolean;
	status: string;
	session_id: string;
	turn_id: string;
	last_event_id: number;
	stop_reason: string;
	goal_text: string;
	waiting_permission: boolean;
	revision?: number;
	model?: string;
	busy: boolean;
};

/**
 * 任务快照是"这一轮到底还在不在跑"的唯一读侧依据：streamRecoverySlice 用它决定
 * 重连还是结算。缺字段的 200 过去会被当成一个读得到内容的快照，`busy`/`status`
 * 都是 undefined ⇒ running=false ⇒ 直接 finalizeFinishedTurn，
 * 把仍在跑的回合显示成已结束。这里让形状不对就抛，函数已有的 catch 会退回 null，
 * 而 null 的含义（读不到，退避重试）才是诚实的。
 */
export function parseSessionTask(payload: unknown): SessionTaskInfo {
	const o = requirePayloadObject(payload, '读取任务快照');
	if (
		typeof o.ok !== 'boolean' ||
		typeof o.status !== 'string' ||
		typeof o.busy !== 'boolean' ||
		typeof o.waiting_permission !== 'boolean' ||
		typeof o.last_event_id !== 'number'
	) {
		throw new Error('读取任务快照：回执缺 status / busy / last_event_id');
	}
	return o as SessionTaskInfo;
}

export async function fetchSessionTask(
	sessionId: string,
): Promise<SessionTaskInfo | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/task`),
			{method: 'GET', headers: authHeaders()},
		);
		if (!res.ok) return null;
		return parseSessionTask(await res.json());
	} catch {
		return null;
	}
}

export async function abandonSessionRecovery(
	sessionId: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(
				`/v1/sessions/${encodeURIComponent(sessionId)}/recovery/abandon`,
			),
			{method: 'POST', headers: authHeaders()},
		);
		return res.ok;
	} catch {
		return false;
	}
}

export const TURN_CURSOR_KEY = 'xeyo:turnCursor:';

export async function deleteServerSession(sessionId: string): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}`),
			{method: 'DELETE'},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** 分叉结果：服务端签发的新会话 id + 标题。 */
export type ServerSessionFork = {
	newId: string;
	title: string;
};

/** smoke-test #3：服务端复制 transcript 到新 sid（fork）。失败返回 null。 */
export async function forkServerSession(
	sessionId: string,
): Promise<ServerSessionFork | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/fork`),
			{method: 'POST'},
		);
		if (!res.ok) {
			return null;
		}
		const payload = (await res.json()) as {
			new_id?: string;
			title?: string;
		};
		return payload.new_id
			? {newId: payload.new_id, title: payload.title || '分叉会话'}
			: null;
	} catch {
		return null;
	}
}

/** smoke-test #3：归档会话（服务端写 archive sidecar，不动 transcript）。 */
export async function archiveServerSession(
	sessionId: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/archive`),
			{method: 'POST'},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** smoke-test #3：找回已归档会话（服务端清 archive sidecar）。 */
export async function restoreServerSession(
	sessionId: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/restore`),
			{method: 'POST'},
		);
		return res.ok;
	} catch {
		return false;
	}
}

/** T5：服务端显式改名（pinned sidecar，永不被自动标题覆盖）。 */
export async function renameServerSession(
	sessionId: string,
	title: string,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/rename`),
			{
				method: 'POST',
				headers: {'Content-Type': 'application/json'},
				body: JSON.stringify({title}),
			},
		);
		return res.ok;
	} catch {
		return false;
	}
}

export type MediaUploadResult = {
	media_ref: string;
	mime: string;
	width: number;
	height: number;
	bytes: number;
	original_bytes: number;
	filename: string;
};

let workspaceOperationTail: Promise<void> = Promise.resolve();

function enqueueWorkspaceOperation<T>(operation: () => Promise<T>): Promise<T> {
	const result = workspaceOperationTail.then(operation, operation);
	workspaceOperationTail = result.then(
		() => undefined,
		() => undefined,
	);
	return result;
}

async function setWorkspaceNow(path: string): Promise<string> {
	const res = await fetchWithTimeout(apiUrl('/v1/workspace'), {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({path}),
	});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	const data = (await res.json()) as {cwd?: string};
	return data.cwd ?? path;
}

/** Serialize legacy global cwd changes; workspace APIs accept explicit roots. */
export function setWorkspace(path: string): Promise<string> {
	return enqueueWorkspaceOperation(() => setWorkspaceNow(path));
}

/** Set the requested root and dispatch its cwd-dependent request in order. */
export function withWorkspaceRoot<T>(
	path: string,
	request: () => Promise<T>,
): Promise<T> {
	const root = path.trim();
	if (!root) {
		return request();
	}
	return enqueueWorkspaceOperation(async () => {
		await setWorkspaceNow(root);
		// Start fetch synchronously before releasing the cwd mutation queue. Keep
		// waiting for its response outside the queue so slow jobs do not block a
		// later workspace switch. Callers reject results from stale roots.
		return {pending: request()};
	}).then(({pending}) => pending);
}

export type WorkspaceEntry = {
	name: string;
	path: string;
	kind: 'file' | 'dir';
	size?: number;
};

export type WorkspaceListing = {
	cwd: string;
	path: string;
	name: string;
	entries: WorkspaceEntry[];
	truncated?: boolean;
};

export type WorkspaceFile = {
	cwd: string;
	path: string;
	name: string;
	mime: string;
	size: number;
	/** 毫秒 mtime；后端 read/stat 均返回，用于预览去重与轻量轮询。 */
	mtime?: number;
	kind: 'text' | 'image' | 'binary';
	text?: string;
	data_url?: string;
	truncated?: boolean;
};

export type WorkspaceFileStat = {
	cwd: string;
	path: string;
	name: string;
	size: number;
	mtime: number;
};

export async function listWorkspaceEntries(
	path = '',
	workspace?: string,
): Promise<WorkspaceListing> {
	const q = new URLSearchParams();
	if (path) {
		q.set('path', path);
	}
	if (workspace) q.set('workspace', workspace);
	const qs = q.toString();
	const res = await fetchWithTimeout(
		apiUrl(`/v1/workspace/entries${qs ? `?${qs}` : ''}`),
	);
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceListing(await res.json());
}

export type WorkspaceSearchResult = {
	cwd: string;
	query: string;
	hits: WorkspaceEntry[];
	truncated: boolean;
};

/**
 * 工作区读写的 200 回执必须校验形状：这些接口的失败过去只在 HTTP 层拦，
 * 200 但缺字段会原样进 store，界面于是写出假事实 ——
 * `kind=text` 而 `text` 不在体里 = 编辑器显示空文件，用户一按保存就覆盖真内容；
 * `entries` 不在体里 = 文件树显示"这个目录是空的"。
 * 抛错走的是各 store 已有的 catch 分支（保留旧值 + 显示错误），不改任何签名。
 */
function requirePayloadObject(payload: unknown, what: string): Record<string, unknown> {
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
		throw new Error(`${what}：回执不是对象，读不出结果`);
	}
	return payload as Record<string, unknown>;
}

export function parseWorkspaceFile(payload: unknown, what = '读取文件'): WorkspaceFile {
	const o = requirePayloadObject(payload, what);
	if (typeof o.path !== 'string' || typeof o.name !== 'string' || typeof o.size !== 'number') {
		throw new Error(`${what}：回执缺 path / name / size`);
	}
	const kind = o.kind;
	if (kind !== 'text' && kind !== 'image' && kind !== 'binary') {
		throw new Error(`${what}：回执缺 kind（不是可判定的文件类型）`);
	}
	if (kind === 'text' && typeof o.text !== 'string') {
		throw new Error(`${what}：kind=text 但正文不在回执里 —— 这不代表文件是空的`);
	}
	if (kind === 'image' && typeof o.data_url !== 'string') {
		throw new Error(`${what}：kind=image 但 data_url 不在回执里`);
	}
	return o as WorkspaceFile;
}

export function parseWorkspaceFileStat(payload: unknown): WorkspaceFileStat {
	const o = requirePayloadObject(payload, '读取文件信息');
	if (typeof o.path !== 'string' || typeof o.size !== 'number' || typeof o.mtime !== 'number') {
		throw new Error('读取文件信息：回执缺 path / size / mtime');
	}
	return o as WorkspaceFileStat;
}

export function parseWorkspaceListing(payload: unknown, what = '读取目录'): WorkspaceListing {
	const o = requirePayloadObject(payload, what);
	if (!Array.isArray(o.entries)) {
		throw new Error(`${what}：回执缺 entries —— 读不出不等于目录为空`);
	}
	return o as WorkspaceListing;
}

export function parseWorkspaceSearch(payload: unknown): WorkspaceSearchResult {
	const o = requirePayloadObject(payload, '搜索工作区');
	if (!Array.isArray(o.hits)) {
		throw new Error('搜索工作区：回执缺 hits —— 读不出不等于没有命中');
	}
	return o as WorkspaceSearchResult;
}

export async function searchWorkspace(q: string, workspace?: string): Promise<WorkspaceSearchResult> {
	const params = new URLSearchParams({q, ...(workspace ? {workspace} : {})});
	const res = await fetchWithTimeout(
		apiUrl(`/v1/workspace/search?${params}`),
		{cache: 'no-store'},
	);
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceSearch(await res.json());
}

export async function readWorkspaceFile(path: string, workspace?: string): Promise<WorkspaceFile> {
	const q = new URLSearchParams({path, ...(workspace ? {workspace} : {})});
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/file?${q}`));
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceFile(await res.json());
}

export async function statWorkspaceFile(path: string, workspace?: string): Promise<WorkspaceFileStat> {
	const q = new URLSearchParams({path, ...(workspace ? {workspace} : {})});
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/file/stat?${q}`), {
		cache: 'no-store',
	});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceFileStat(await res.json());
}

export async function writeWorkspaceFile(
	path: string,
	text: string,
	workspace?: string,
): Promise<WorkspaceFile> {
	const res = await fetchWithTimeout(apiUrl('/v1/workspace/file'), {
		method: 'PUT',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({path, text, ...(workspace ? {workspace} : {})}),
	});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceFile(await res.json(), '保存文件');
}

export type GitStatusEntry = {
	path: string;
	status: string;
	index?: string;
	worktree?: string;
};

export type GitStatusResult = {
	ok: boolean;
	repo: boolean;
	cwd: string;
	branch?: string;
	head?: string;
	clean?: boolean;
	counts?: {staged: number; unstaged: number; untracked: number};
	staged?: GitStatusEntry[];
	unstaged?: GitStatusEntry[];
	untracked?: GitStatusEntry[];
};

export type GitCommit = {
	hash: string;
	short: string;
	author: string;
	date: string;
	subject: string;
};

export type GitLogResult = {
	ok: boolean;
	repo: boolean;
	cwd: string;
	commits: GitCommit[];
};

export type GitBranchesResult = {
	ok: boolean;
	repo: boolean;
	cwd: string;
	current?: string | null;
	branches?: string[];
};

export type FileDiffResult = {
	ok: boolean;
	cwd?: string;
	repo: boolean;
	path: string;
	kind: 'diff' | 'untracked' | 'binary' | 'unchanged' | 'none';
	diff?: string | null;
};

export type TerminalResult = {
	ok: boolean;
	cwd: string;
	command: string;
	shell: string;
	exit_code: number | null;
	stdout: string;
	stderr: string;
	timed_out: boolean;
	truncated: {stdout: boolean; stderr: boolean};
	elapsed_ms: number;
};

export type WorkspacePeerInfo = {
	session_id: string;
	title: string;
	busy: boolean;
	owned_files: string[];
	todo_brief: string[];
	current_tool: string;
	git_op: string;
	updated_at: number;
};

export type WorkspacePeersResult = {
	ok: boolean;
	cwd: string;
	peers: WorkspacePeerInfo[];
};

export type JournalChange = {
	seq: number;
	agent_id: string;
	path: string;
	action: string;
	ts: number;
	brief: string;
	syntax_valid: boolean;
	conflict_task: boolean;
	diff: string;
	session_id: string;
};

export type WorkspaceJournalResult = {
	ok: boolean;
	cwd: string;
	changes: JournalChange[];
};

export async function fetchWorkspaceJournal(
	options?: {pathPrefix?: string; agentId?: string; limit?: number; workspace?: string},
): Promise<WorkspaceJournalResult> {
	const q = new URLSearchParams();
	if (options?.pathPrefix?.trim()) q.set('path_prefix', options.pathPrefix.trim());
	if (options?.agentId?.trim()) q.set('agent_id', options.agentId.trim());
	if (options?.limit) q.set('limit', String(options.limit));
	if (options?.workspace?.trim()) q.set('workspace', options.workspace.trim());
	const suffix = q.toString() ? `?${q}` : '';
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/journal${suffix}`), {
		cache: 'no-store',
	});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	const body = (await res.json()) as WorkspaceJournalResult;
	return {
		ok: body.ok !== false,
		cwd: String(body.cwd || ''),
		changes: Array.isArray(body.changes) ? body.changes : [],
	};
}

/** 同工作区其他会话在场摘要（人类可见；不含对话正文）。 */
export async function fetchWorkspacePeers(
	cwd?: string,
	sessionId?: string,
): Promise<WorkspacePeersResult> {
	const q = new URLSearchParams();
	if (cwd?.trim()) q.set('cwd', cwd.trim());
	if (sessionId?.trim()) q.set('session_id', sessionId.trim());
	const suffix = q.toString() ? `?${q}` : '';
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/peers${suffix}`), {
		cache: 'no-store',
	});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	const body = (await res.json()) as WorkspacePeersResult;
	return {
		ok: body.ok !== false,
		cwd: String(body.cwd || ''),
		peers: Array.isArray(body.peers) ? body.peers : [],
	};
}

/**
 * Git 只读面板的 200 回执必须校验形状。这四个端点的真失败会走 HTTP 状态码
 * （api_error），所以过去没人看响应体；但"200 且缺字段"会原样进组件，
 * 界面于是写出假事实：
 * - `repo` 不在体里 ⇒ Git 面板显示「当前工作区不是 Git 仓库」；
 * - `repo=true` 而 `clean` / 三个清单都不在 ⇒ 三个 StatusGroup 各自渲染 null，
 *   看起来就是「没有任何改动」；
 * - `commits` 不在体里 ⇒ `commits.length` 当场抛，提交记录面板整块崩掉；
 * - `branches` 不在体里 ⇒ 分支树只剩当前分支。
 * 抛错走各面板已有的 catch（显示「加载失败：…」并把数据留空），不改任何签名。
 */
function requireGitBase(payload: unknown, what: string): Record<string, unknown> {
	const o = requirePayloadObject(payload, what);
	if (typeof o.ok !== 'boolean' || typeof o.repo !== 'boolean') {
		throw new Error(`${what}：回执缺 ok / repo —— 读不出不代表这不是 Git 仓库`);
	}
	return o;
}

function requireGitStatusLists(o: Record<string, unknown>, what: string): void {
	const lists = ['staged', 'unstaged', 'untracked'] as const;
	for (const key of lists) {
		if (o[key] !== undefined && !Array.isArray(o[key])) {
			throw new Error(`${what}：回执的 ${key} 不是清单`);
		}
	}
	if (o.clean === false && !lists.some(key => Array.isArray(o[key]) && (o[key] as unknown[]).length > 0)) {
		throw new Error(`${what}：clean=false 但改动清单不在回执里 —— 读不出不等于没有改动`);
	}
}

export function parseGitStatus(payload: unknown): GitStatusResult {
	const o = requireGitBase(payload, '读取 Git 状态');
	if (o.repo === true) {
		if (typeof o.clean !== 'boolean') {
			throw new Error('读取 Git 状态：repo=true 但 clean 不在回执里 —— 读不出不代表工作区干净');
		}
		requireGitStatusLists(o, '读取 Git 状态');
	}
	return o as GitStatusResult;
}

export function parseGitLog(payload: unknown): GitLogResult {
	const o = requireGitBase(payload, '读取提交记录');
	if (o.repo !== true) {
		return o as GitLogResult;
	}
	if (!Array.isArray(o.commits)) {
		throw new Error('读取提交记录：回执缺 commits —— 读不出不等于没有提交');
	}
	for (const item of o.commits) {
		if (
			!item ||
			typeof item !== 'object' ||
			!['hash', 'short', 'subject', 'author', 'date'].every(k => typeof (item as Record<string, unknown>)[k] === 'string')
		) {
			throw new Error('读取提交记录：commits 里有一条不是提交');
		}
	}
	return o as GitLogResult;
}

export function parseGitBranches(payload: unknown): GitBranchesResult {
	const o = requireGitBase(payload, '读取分支列表');
	if (o.repo !== true) {
		return o as GitBranchesResult;
	}
	if (!Array.isArray(o.branches) || !o.branches.every(b => typeof b === 'string')) {
		throw new Error('读取分支列表：回执缺 branches —— 读不出不等于只有当前分支');
	}
	if (o.current !== undefined && o.current !== null && typeof o.current !== 'string') {
		throw new Error('读取分支列表：current 不是分支名');
	}
	return o as GitBranchesResult;
}

export function parseGitFileDiff(payload: unknown): FileDiffResult {
	const o = requireGitBase(payload, '读取文件差异');
	const kind = o.kind;
	if (kind !== 'diff' && kind !== 'untracked' && kind !== 'binary' && kind !== 'unchanged' && kind !== 'none') {
		throw new Error('读取文件差异：回执缺 kind（不知道这个文件算什么状态）');
	}
	if ((kind === 'diff' || kind === 'untracked') && (typeof o.diff !== 'string' || !o.diff.trim())) {
		throw new Error(`读取文件差异：kind=${kind} 但差异正文不在回执里 —— 这不代表改动是空的`);
	}
	return o as FileDiffResult;
}

export async function gitStatus(workspace?: string): Promise<GitStatusResult> {
	const query = workspace ? `?${new URLSearchParams({workspace})}` : '';
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/git/status${query}`), {cache: 'no-store'});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseGitStatus(await res.json());
}

export async function gitLog(limit = 20, workspace?: string): Promise<GitLogResult> {
	const q = new URLSearchParams({limit: String(limit), ...(workspace ? {workspace} : {})});
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/git/log?${q}`), {cache: 'no-store'});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseGitLog(await res.json());
}

export async function gitBranches(workspace?: string): Promise<GitBranchesResult> {
	const query = workspace ? `?${new URLSearchParams({workspace})}` : '';
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/git/branches${query}`), {cache: 'no-store'});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseGitBranches(await res.json());
}

export async function gitFileDiff(path: string, workspace?: string): Promise<FileDiffResult> {
	const q = new URLSearchParams({path, ...(workspace ? {workspace} : {})});
	const res = await fetchWithTimeout(apiUrl(`/v1/workspace/file/diff?${q}`), {cache: 'no-store'});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseGitFileDiff(await res.json());
}

/**
 * 终端面板把回执的每一栏都印成事实：`[退出码 X · Yms · 输出已截断]`。
 * 200 但缺字段时，过去会印成「退出码 — · undefinedms」并把 stdout 当没有输出，
 * 或在读 `truncated.stdout` 时抛错、把已经跑完的命令整条换成一行错误。
 * 校验后一律走调用方已有的 catch：面板显示后端 detail，不显示编出来的读数。
 */
export function parseTerminalResult(payload: unknown): TerminalResult {
	const o = requirePayloadObject(payload, '执行命令');
	if (typeof o.ok !== 'boolean') {
		throw new Error('执行命令：回执缺 ok');
	}
	if (typeof o.stdout !== 'string' || typeof o.stderr !== 'string') {
		throw new Error('执行命令：回执缺 stdout / stderr —— 读不出不等于命令没有输出');
	}
	if (typeof o.timed_out !== 'boolean' || typeof o.elapsed_ms !== 'number') {
		throw new Error('执行命令：回执缺 timed_out / elapsed_ms');
	}
	if (o.exit_code !== null && typeof o.exit_code !== 'number') {
		throw new Error('执行命令：exit_code 既不是数字也不是"没有退出码"');
	}
	const t = o.truncated;
	if (
		!t ||
		typeof t !== 'object' ||
		typeof (t as {stdout?: unknown}).stdout !== 'boolean' ||
		typeof (t as {stderr?: unknown}).stderr !== 'boolean'
	) {
		throw new Error('执行命令：回执缺 truncated 标记 —— 不知道有没有截断就不能说输出是完整的');
	}
	return o as TerminalResult;
}

export async function execWorkspaceTerminal(
	command: string,
	timeoutS?: number,
	workspace?: string,
): Promise<TerminalResult> {
	const res = await fetchWithTimeout(
		apiUrl('/v1/workspace/terminal/exec'),
		{
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({
				command,
				...(timeoutS ? {timeout_s: timeoutS} : {}),
				...(workspace ? {workspace} : {}),
			}),
		},
		(timeoutS ?? 600) * 1000 + REQUEST_TIMEOUT_MS,
	);
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseTerminalResult(await res.json());
}

export type FileHelperEvent = {
	id: string;
	kind: 'inbound' | 'outbound' | string;
	text: string;
	ts: number;
	command?: string | null;
	session_id?: string | null;
	request_id?: string | null;
	tool_name?: string | null;
	reason?: string | null;
};

export type FileHelperStatus = {
	state: 'stopped' | 'starting' | 'qr' | 'scanned' | 'logged_in' | 'error' | string;
	logged_in: boolean;
	has_qr: boolean;
	qr_rev?: number;
	error: string | null;
	hint?: string | null;
	session_id: string;
	last_session_id?: string;
	stream_session_id?: string;
	recent_jobs?: unknown[];
	events: FileHelperEvent[];
	streaming?: boolean;
	stream_text?: string;
	stream_status?: string;
	stream_len?: number;
	stream_reset?: boolean;
	stream_tools?: Array<{
		id?: string;
		kind?: string;
		name?: string;
		input?: unknown;
		output?: string;
		is_error?: boolean;
		session_id?: string;
	}>;
	channel?: 'filehelper' | 'ilink' | string;
	last_poll_error?: string | null;
	poll_timeouts?: number;
	poll_alive?: boolean;
};

async function readFilehelperJson(res: Response): Promise<FileHelperStatus> {
	const payload: unknown = await res.json().catch(() => ({}));
	if (!res.ok) {
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return payload as FileHelperStatus;
}

export async function filehelperStatus(
	after = '',
	opts?: {omitJobs?: boolean; streamFrom?: number},
): Promise<FileHelperStatus> {
	const q = new URLSearchParams();
	if (after) {
		q.set('after', after);
	}
	if (opts?.omitJobs) {
		q.set('omit_jobs', '1');
	}
	if (opts?.streamFrom != null && opts.streamFrom >= 0) {
		q.set('stream_from', String(opts.streamFrom));
	}
	const qs = q.toString();
	const res = await fetchWithTimeout(apiUrl(`/v1/filehelper/status${qs ? `?${qs}` : ''}`));
	return readFilehelperJson(res);
}

export async function filehelperStart(body: {
	api_key: string;
	provider: string;
	model: string;
	base_url: string;
}): Promise<FileHelperStatus> {
	const res = await fetchWithTimeout(apiUrl('/v1/filehelper/start'), {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify(body),
	});
	return readFilehelperJson(res);
}

export async function filehelperStop(): Promise<FileHelperStatus> {
	const res = await fetchWithTimeout(apiUrl('/v1/filehelper/stop'), {method: 'POST'});
	return readFilehelperJson(res);
}

export function filehelperQrUrl(rev = 0): string {
	return apiUrl(`/v1/filehelper/qr.png?n=${rev}`);
}

export async function ilinkStatus(
	after = '',
	opts?: {omitJobs?: boolean; streamFrom?: number},
): Promise<FileHelperStatus> {
	const q = new URLSearchParams();
	if (after) {
		q.set('after', after);
	}
	if (opts?.omitJobs) {
		q.set('omit_jobs', '1');
	}
	if (opts?.streamFrom != null && opts.streamFrom >= 0) {
		q.set('stream_from', String(opts.streamFrom));
	}
	const qs = q.toString();
	const res = await fetchWithTimeout(apiUrl(`/v1/ilink/status${qs ? `?${qs}` : ''}`));
	return readFilehelperJson(res);
}

export async function ilinkStart(body: {
	api_key: string;
	provider: string;
	model: string;
	base_url: string;
}): Promise<FileHelperStatus> {
	const res = await fetchWithTimeout(apiUrl('/v1/ilink/start'), {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify(body),
	});
	return readFilehelperJson(res);
}

export async function ilinkStop(): Promise<FileHelperStatus> {
	const res = await fetchWithTimeout(apiUrl('/v1/ilink/stop'), {method: 'POST'});
	return readFilehelperJson(res);
}

export function ilinkQrUrl(rev = 0): string {
	return apiUrl(`/v1/ilink/qr.png?n=${rev}`);
}


export class RollbackRequestError extends Error {
	readonly status: number;
	readonly errorType: string | null;

	constructor(message: string, status: number, errorType: string | null = null) {
		super(message);
		this.name = 'RollbackRequestError';
		this.status = status;
		this.errorType = errorType;
	}
}

export function rollbackApiErrorType(payload: unknown): string | null {
	if (!payload || typeof payload !== 'object') {
		return null;
	}
	const obj = payload as {error?: unknown; detail?: unknown};
	const errObj = obj.error;
	if (errObj && typeof errObj === 'object' && !Array.isArray(errObj)) {
		const type = (errObj as {type?: unknown}).type;
		if (typeof type === 'string' && type.trim()) {
			return type;
		}
	}
	const detail = obj.detail;
	if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
		const type = (detail as {type?: unknown}).type;
		if (typeof type === 'string' && type.trim()) {
			return type;
		}
	}
	return null;
}

export function formatStreamHttpError(payload: unknown, status: number): string {
	if (status === 409 && rollbackApiErrorType(payload) === 'session_busy') {
		return 'Agent 仍在运行，请稍候或点停止后重试。';
	}
	return formatErrorDetail(payload, status);
}

async function rollbackJsonRequest<T>(
	path: string,
	body?: Record<string, unknown>,
): Promise<T> {
	let res: Response;
	try {
		res = await fetchWithTimeout(
			apiUrl(path),
			{
				method: body ? 'POST' : 'GET',
				headers: body ? {'Content-Type': 'application/json'} : undefined,
				body: body ? JSON.stringify(body) : undefined,
				cache: 'no-store',
			},
			90_000,
		);
	} catch (err) {
		throw new RollbackRequestError(
			`无法连接回溯服务（${err instanceof Error ? err.message : String(err)}）`,
			0,
			'network_error',
		);
	}
	let payload: unknown = null;
	try {
		payload = await res.json();
	} catch {
		/* 非 JSON 错误响应由状态码兜底 */
	}
	if (!res.ok) {
		throw new RollbackRequestError(
			formatErrorDetail(payload, res.status),
			res.status,
			rollbackApiErrorType(payload),
		);
	}
	return payload as T;
}

export async function previewRollback(
	sessionId: string,
	request: {targetMessageId: string; editedText: string},
): Promise<RollbackPlan> {
	const payload = await rollbackJsonRequest<{ok: boolean; plan: RollbackPlan}>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rollback/preview`,
		{
			target_message_id: request.targetMessageId,
			edited_text: request.editedText,
		},
	);
	return payload.plan;
}

/** 回溯 v3 热路径：跳过 preview，transcript 提交后立即返回。 */
export async function rewindHotpath(
	sessionId: string,
	request: {
		mode: 'restore' | 'continue';
		targetMessageId: string;
		checkpointId?: string | null;
		editedText?: string | null;
		idempotencyKey?: string | null;
		confirmed: boolean;
	},
): Promise<RewindHotpathResult> {
	return rollbackJsonRequest<RewindHotpathResult>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rewind`,
		{
			mode: request.mode,
			target_message_id: request.targetMessageId,
			checkpoint_id: request.checkpointId ?? undefined,
			edited_text: request.editedText ?? undefined,
			idempotency_key: request.idempotencyKey ?? undefined,
			confirmed: request.confirmed,
		},
	);
}

export async function rewindHotpathUndo(
	sessionId: string,
	rewindId: string,
): Promise<Record<string, unknown>> {
	return rollbackJsonRequest<Record<string, unknown>>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rewind/${encodeURIComponent(rewindId)}/undo`,
		{confirmed: true},
	);
}

/** 处理回溯 recovery_required 中间态（§9.2）：retry / abandon。 */
export async function recoverRewind(
	sessionId: string,
	rewindId: string,
	action: 'retry' | 'abandon',
): Promise<Record<string, unknown>> {
	return rollbackJsonRequest<Record<string, unknown>>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rewind/${encodeURIComponent(rewindId)}/recover`,
		{action, confirmed: true},
	);
}

export async function fetchRewindEvents(sessionId: string): Promise<RewindEvent[]> {
	return rollbackJsonRequest<RewindEvent[]>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rewind`,
	);
}

export async function fetchRewindStatus(
	sessionId: string,
	rewindId: string,
): Promise<RewindEvent> {
	return rollbackJsonRequest<RewindEvent>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rewind/${encodeURIComponent(rewindId)}`,
	);
}

export async function fetchRewindCheckpoint(
	sessionId: string,
	messageId: string,
): Promise<RewindCheckpointLookup> {
	return rollbackJsonRequest<RewindCheckpointLookup>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rewind/checkpoint/${encodeURIComponent(messageId)}`,
	);
}

/** 回溯 blob GC 设置（设计 §36 §9.1）。 */
export type RewindGcSettings = {
	keep_recent: number | null;
	max_bytes: number | null;
	defaults?: {enabled: boolean; dry_run: boolean; max_bytes: number | null};
};

export async function getRewindGcSettings(): Promise<RewindGcSettings | null> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/rewind-gc'), {
			cache: 'no-store',
		});
		if (!res.ok) return null;
		return (await res.json()) as RewindGcSettings;
	} catch {
		return null;
	}
}

/**
 * 写入回执。后端专门因为 GUI 只看 `res.ok` 过一次假绿
 * （路由 docstring 点名："keep_recent=0 被拒在前端渲染成保存成功"），
 * 现在非法值走 422/500 —— 但"HTTP 成功"仍不等于"落盘的就是我以为的那份"：
 * 回执带回 `**saved`，调用方要按它写本地，而不是按自己发出去的值。
 */
export type RewindGcWrite = {
	ok: boolean;
	settings: {keep_recent: number | null; max_bytes: number | null} | null;
	message: string;
};

export async function setRewindGcSettings(
	keepRecent: number | null,
	maxBytes: number | null,
): Promise<RewindGcWrite> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/rewind-gc'), {
			method: 'PUT',
			headers: {
				'Content-Type': 'application/json',
				...authHeaders(),
			},
			body: JSON.stringify({
				keep_recent: keepRecent ?? null,
				max_bytes: maxBytes ?? null,
			}),
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, settings: null, message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, settings: null, message: 'receipt_not_object'};
		}
		const b = payload as Record<string, unknown>;
		if (b.ok !== true) {
			return {ok: false, settings: null, message: formatErrorDetail(payload, res.status)};
		}
		// null 是合法的"该项未设置"；缺键才是回执不完整。
		if (!('keep_recent' in b) || !('max_bytes' in b)) {
			return {ok: false, settings: null, message: 'receipt_missing_fields'};
		}
		const kr = b.keep_recent;
		const mb = b.max_bytes;
		if ((kr !== null && !isFiniteNumber(kr)) || (mb !== null && !isFiniteNumber(mb))) {
			return {ok: false, settings: null, message: 'receipt_bad_fields'};
		}
		return {
			ok: true,
			settings: {keep_recent: kr as number | null, max_bytes: mb as number | null},
			message: '',
		};
	} catch (err) {
		return {
			ok: false,
			settings: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

/** 记忆系统开关：设置读取/写入（持久到 .xeyo/settings.json 的 memory 段 + 运行时 os.environ）。
 *
 * `exposed` = 是否在设置面板暴露（测试/评测便捷开关为 false，仅后端可切）；
 * `ignored` = 运行时是否忽略该键（已下线/恒关占位）；`effective` = 运行时真值。
 * 前端一律按 `exposed` 过滤、按 `effective` 显示开关态。
 */
export type MemorySwitch = {
	key: string;
	label: string;
	value: string;
	allowed: string[];
	source: 'settings' | 'env' | 'default' | 'ignored';
	default: string;
	exposed?: boolean;
	ignored?: boolean;
	effective?: string;
};

export type MemorySwitchesResponse = {
	ok: boolean;
	switches?: Record<string, MemorySwitch>;
	/** settings.memory 里的已删/未知残留键（只读报告；保存时后端会自动清理）。 */
	stale?: string[];
	/** 保存时被清理的残留键（仅 POST 回执）。 */
	pruned?: string[];
	message?: string;
	error?: string;
};

/**
 * 开关读写的统一回执：ok=false 时 data 一定是 null，message 是能直接上屏的原因。
 *
 * 旧签名 `Promise<MemorySwitchesResponse | null>` 有两处塌缩：
 * - null 同时表示"HTTP 失败""离线""后端按 200 回了 ok:false"，面板只能一律当成
 *   "没有可切换的开关"，把读不出画成一句关于开关的事实；
 * - 后端拒绝未知键时回的是 200 + {ok:false, error}，旧面板只读 `message`，
 *   那句"未知记忆开关: XEYO_…"就这样丢了。
 */
export type MemorySwitchesRead = {
	ok: boolean;
	data: MemorySwitchesResponse | null;
	message: string;
};

function readSwitchesReceipt(payload: unknown, status: number): MemorySwitchesRead {
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
		return {ok: false, data: null, message: formatErrorDetail(payload, status)};
	}
	const b = payload as MemorySwitchesResponse;
	if (b.ok !== true) {
		return {
			ok: false,
			data: null,
			message: b.error || b.message || formatErrorDetail(payload, status),
		};
	}
	const sw = b.switches;
	if (!sw || typeof sw !== 'object' || Array.isArray(sw)) {
		return {ok: false, data: null, message: 'receipt_missing_switches'};
	}
	return {ok: true, data: b, message: ''};
}

export async function getMemorySwitches(): Promise<MemorySwitchesRead> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory'), {cache: 'no-store'});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		return readSwitchesReceipt(payload, res.status);
	} catch (err) {
		return {
			ok: false,
			data: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export async function setMemorySwitches(
	updates: Record<string, string | boolean>,
): Promise<MemorySwitchesRead> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory'), {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				...authHeaders(),
			},
			body: JSON.stringify({updates}),
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		return readSwitchesReceipt(payload, res.status);
	} catch (err) {
		return {
			ok: false,
			data: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export type MemorySnapshotResult = {
	ok: boolean;
	day?: string;
	/** auto 会补齐「上次快照日之后 → 最新日」的所有天；按写入顺序排列。 */
	days?: string[];
	rc?: number;
	tail?: string;
	error?: string;
};

/**
 * 快照回执：ok=false 只表示"没读到结果"（HTTP 失败/离线/形状变了），
 * 与"后端跑了但说失败"（ok:true + data.ok:false + error）是两件事。
 */
export type MemorySnapshotRead = {
	ok: boolean;
	data: MemorySnapshotResult | null;
	message: string;
};

export async function runMemorySnapshot(): Promise<MemorySnapshotRead> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory/snapshot'), {
			method: 'POST',
			headers: {...authHeaders()},
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, data: null, message: 'receipt_bad_snapshot'};
		}
		const data = payload as MemorySnapshotResult;
		if (typeof data.ok !== 'boolean') {
			return {ok: false, data: null, message: 'receipt_bad_snapshot'};
		}
		if (data.rc != null && !isFiniteNumber(data.rc)) {
			return {ok: false, data: null, message: 'receipt_bad_snapshot'};
		}
		return {ok: true, data, message: ''};
	} catch (err) {
		return {
			ok: false,
			data: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export type MemoryReportInfo = {
	/** 报告已生成且可读；不存在时 false（按钮据此禁用，不算错误）。 */
	ok: boolean;
	exists?: boolean;
	/** 磁盘绝对路径；打不开时给用户复制用。 */
	path?: string;
	/** 可直接交给系统浏览器的 file:// 链接。 */
	url?: string;
	bytes?: number;
	mtime?: number;
	generated_at?: string | null;
	/** 报告覆盖的日期（升序）。 */
	days?: string[];
	error?: string;
};

/**
 * 报告回执。`ok:false + exists:false` 是后端**给得出的正面答案**（报告确实还没生成），
 * 与"我们没读到"（HTTP 失败 / 离线 / 形状变了）必须分开：前者才能禁按钮并写"尚未生成"，
 * 后者只能写"未读到"。后端自己也守这条 —— 报告存在却读不出时它回 500，不谎报"尚未生成"。
 */
export type MemoryReportRead = {
	ok: boolean;
	data: MemoryReportInfo | null;
	message: string;
};

/** A3 监控报告（docs/A3-monitor.html）落点与元信息；设置页「打开报告」按钮用。 */
export async function getMemoryReport(): Promise<MemoryReportRead> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory/report'), {
			cache: 'no-store',
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, data: null, message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, data: null, message: 'receipt_bad_report'};
		}
		const data = payload as MemoryReportInfo;
		if (typeof data.ok !== 'boolean' || typeof data.exists !== 'boolean') {
			return {ok: false, data: null, message: 'receipt_bad_report'};
		}
		return {ok: true, data, message: ''};
	} catch (err) {
		return {
			ok: false,
			data: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

/**
 * 「打开报告」用的网页入口：后端把报告按 text/html 吐出来。
 *
 * 不能直接用 ``report.url``（file://）交给系统浏览器——桌面壳的 ``shell:allow-open``
 * scope 只放行 ``mailto:``/``tel:``/``http(s)://``，会报 Scoped command argument
 * failed regex validation。
 */
export function memoryReportViewUrl(): string {
	return apiUrl('/v1/settings/memory/report/view');
}

/** 给某条 user 消息的 checkpoint 打/取消锚点（§9.1 锚点写入方）。 */
export async function setCheckpointAnchor(
	sessionId: string,
	messageId: string,
	anchor: boolean,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(
				`/v1/sessions/${encodeURIComponent(sessionId)}/rewind/checkpoint/${encodeURIComponent(messageId)}/anchor`,
			),
			{
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...authHeaders(),
				},
				body: JSON.stringify({anchor}),
			},
		);
		return res.ok;
	} catch {
		return false;
	}
}

export async function executeRollback(
	sessionId: string,
	request: {
		planId: string;
		planHash: string;
		idempotencyKey: string;
		confirmed: boolean;
		expectedWorkspaceRevision?: string | null;
		/** 可选的 shadow-git 整树恢复；默认 false = 仅恢复 Agent 改动的文件。 */
		fullTreeRestore?: boolean | null;
		/** false = 仅回滚 transcript；工作区文件保持原样。 */
		restoreWorkspace?: boolean | null;
		/** v2：transcript_committed 后即返回；工作区在后台继续完成。 */
		asyncWorkspace?: boolean | null;
	},
): Promise<{
	job: RecoveryJob;
	revision?: Record<string, unknown>;
	retainedMessages?: ChatMessage[];
}> {
	const payload = await rollbackJsonRequest<{
		ok: boolean;
		job: RecoveryJob;
		revision?: Record<string, unknown>;
		retained_messages?: Array<Record<string, unknown>>;
	}>(`/v1/sessions/${encodeURIComponent(sessionId)}/rollback/execute`, {
		plan_id: request.planId,
		plan_hash: request.planHash,
		idempotency_key: request.idempotencyKey,
		confirmed: request.confirmed,
		expected_workspace_revision: request.expectedWorkspaceRevision ?? null,
		full_tree_restore: request.fullTreeRestore ?? false,
		restore_workspace: request.restoreWorkspace ?? null,
		async_workspace: request.asyncWorkspace ?? true,
	});
	const retainedMessages = Array.isArray(payload.retained_messages)
		? retainedTranscriptRowsToChatMessages(payload.retained_messages)
		: undefined;
	return {
		job: payload.job,
		revision: payload.revision,
		retainedMessages,
	};
}

export async function getRollbackJobStatus(
	sessionId: string,
	jobId: string,
): Promise<RecoveryJob> {
	const payload = await rollbackJsonRequest<{ok: boolean; job: RecoveryJob}>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rollback/status/${encodeURIComponent(jobId)}`,
	);
	return payload.job;
}

export async function resolveRollbackRecovery(
	sessionId: string,
	jobId: string,
	action: 'retry_checkpoint' | 'abandon',
): Promise<{job: RecoveryJob}> {
	const payload = await rollbackJsonRequest<{ok: boolean; job: RecoveryJob}>(
		`/v1/sessions/${encodeURIComponent(sessionId)}/rollback/jobs/${encodeURIComponent(jobId)}/recover`,
		{action},
	);
	return {job: payload.job};
}

/** 将 rollback execute 返回的后端 transcript 行映射为 ChatMessage 结构。 */
function retainedTranscriptRowsToChatMessages(
	rows: Array<Record<string, unknown>>,
): ChatMessage[] {
	const out: ChatMessage[] = [];
	for (let i = 0; i < rows.length; i++) {
		const row = rows[i]!;
		const role = String(row.role || '');
		if (role !== 'user' && role !== 'assistant' && role !== 'system' && role !== 'tool') {
			continue;
		}
		const id = String(row.id || `retained_${i}`);
		const content = row.content;
		let text = '';
		if (typeof content === 'string') {
			text = content;
		} else if (Array.isArray(content)) {
			text = content
				.map(block => {
					if (typeof block === 'string') return block;
					if (block && typeof block === 'object' && 'text' in block) {
						return String((block as {text?: unknown}).text ?? '');
					}
					return '';
				})
				.filter(Boolean)
				.join('\n');
		} else if (content != null) {
			text = String(content);
		}
		const ts = row.ts;
		const createdAt =
			typeof ts === 'number' ? Math.round(ts * 1000) : Date.now();
		out.push({
			id,
			role: role as ChatMessage['role'],
			text,
			createdAt,
			...(typeof row.name === 'string' && row.name
				? {toolName: row.name}
				: {}),
		});
	}
	return out;
}

/** 43 号：Bash 路由/渐进强制策略（含推荐值/上限）。 */
export type BashPolicy = {
	ok: boolean;
	cwd: string;
	bash_routing: 'auto' | 'off';
	bash_escalate: number;
	escalate_recommended: number;
	escalate_max: number;
	escalate_min: number;
};

/**
 * 读 / 写策略的回执。ok=false 时 policy 一定是 null，message 是能直接上屏的原因。
 *
 * 旧签名是 `Promise<BashPolicy | null>` 且 200 直接 `as BashPolicy` 返回：
 * 后端少回一个键（比如 escalate_max），界面就按客户端自己编的默认值显示
 * "上限 5 / 推荐 3"——那两个数字本来是工作区策略事实，不是 UI 的猜测。
 */
export type BashPolicyRead = {
	ok: boolean;
	policy: BashPolicy | null;
	message: string;
};

/** 后端固定回这 7 个键；缺任何一个都不算"读到了策略"。 */
function parseBashPolicy(payload: unknown): BashPolicy | null {
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
	const b = payload as Record<string, unknown>;
	if (b.ok !== true || typeof b.cwd !== 'string') return null;
	if (b.bash_routing !== 'auto' && b.bash_routing !== 'off') return null;
	if (!isFiniteNumber(b.bash_escalate) || b.bash_escalate < 0) return null;
	if (
		!isFiniteNumber(b.escalate_max) ||
		!isFiniteNumber(b.escalate_min) ||
		!isFiniteNumber(b.escalate_recommended)
	) {
		return null;
	}
	return {
		ok: true,
		cwd: b.cwd,
		bash_routing: b.bash_routing,
		bash_escalate: b.bash_escalate,
		escalate_recommended: b.escalate_recommended,
		escalate_max: b.escalate_max,
		escalate_min: b.escalate_min,
	};
}

export async function loadBashPolicy(
	workspace?: string,
): Promise<BashPolicyRead> {
	try {
		const query = workspace ? `?${new URLSearchParams({workspace})}` : '';
		const res = await fetchWithTimeout(apiUrl(`/v1/workspace/policy-bash${query}`), {
			cache: 'no-store',
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, policy: null, message: formatErrorDetail(payload, res.status)};
		}
		const policy = parseBashPolicy(payload);
		return policy
			? {ok: true, policy, message: ''}
			: {ok: false, policy: null, message: 'receipt_bad_policy'};
	} catch (err) {
		return {
			ok: false,
			policy: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export async function saveBashPolicy(input: {
	bash_routing?: 'auto' | 'off';
	bash_escalate?: number;
	workspace?: string;
}): Promise<BashPolicyRead> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/workspace/policy-bash'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify(input),
		});
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, policy: null, message: formatErrorDetail(payload, res.status)};
		}
		const policy = parseBashPolicy(payload);
		return policy
			? {ok: true, policy, message: ''}
			: {ok: false, policy: null, message: 'receipt_bad_policy'};
	} catch (err) {
		return {
			ok: false,
			policy: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}
