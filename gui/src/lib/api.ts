import {useSettingsStore} from '@/stores/settingsStore';
import {apiUrl} from '@/lib/apiBase';
import type {ChatMessage, RecoveryJob, RewindCheckpointLookup, RewindEvent, RewindHotpathResult, RollbackPlan} from './types';
import {REQUEST_TIMEOUT_MS, authHeaders, fetchWithTimeout, formatErrorDetail} from './api/core';
import type {} from './api/core';
import type {ServerSession, SessionAgentMeta} from './api/chatStream';
export {VENDOR_CONTEXT_LIMIT_KEY, fetchUsage, fetchUsageBalance, fetchVendorModels, getCachedModelContextLimit, healthCheck, loadVendorContextLimits, persistVendorContextLimits, rememberVendorContextLimits, vendorContextLimitCache, vendorModelCacheKey} from './api/usage';
export type {UsageBalance, UsageDayPoint, UsageModelBlock, UsageReport, VendorModel, VendorModelMode, VendorModelsReport} from './api/usage';
export {uploadFile, uploadMedia} from './api/uploads';
export {listPermissionGrants, resolveAsk, resolvePermission, resolvePlan, revokePermissionGrant} from './api/permissions';
export type {PermissionGrantInfo} from './api/permissions';
export {fetchMemoryNotes, requestManualCompact, syncUiThoughtsToServer} from './api/memory';
export {setSessionRuntimeMode} from './api/runtimeMode';
export {fetchSkills} from './api/skills';
export type {SkillInfo, SkillSource, SkillsReport} from './api/skills';
export {fetchFileReferences} from './api/references';
export type {FileReferencesReport} from './api/references';
export {readTurnCursor, rememberTurnCursor, streamChat, streamTurnEvents} from './api/chatStream';
export type {ServerSession, SessionAgentMeta} from './api/chatStream';
export {MEDIA_REF_RE, REQUEST_TIMEOUT_MS, STREAM_IDLE_TIMEOUT_MS, authHeaders, createStreamWatchdog, fetchWithTimeout, formatErrorDetail, mediaUrl, parseOpenAiSse, parseSseBlock, readIdentity} from './api/core';
export type {AskUserPendingStreamEvent, AskUserResolvedStreamEvent, ChatApiMessage, ChatRequestOptions, ChatStreamHandlers, CompressionStreamEvent, EventIdentity, MultiAgentDeltaStreamEvent, MultiAgentProgressStreamEvent, MultiAgentResultStreamEvent, MultiAgentStatusStreamEvent, MultiAgentTaskStreamEvent, MultiAgentTaskView, ParsedSse, PermissionPendingStreamEvent, PermissionResolvedStreamEvent, PlanPendingStreamEvent, PlanResolvedStreamEvent, ReasoningStreamEvent, SseTermination, StreamWatchdog, TaskStateStreamEvent, ToolCallStreamEvent, ToolProgressStreamEvent, ToolResultStreamEvent, UsageStreamEvent} from './api/core';

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
	toolInput?: string;
	toolStatus?: 'running' | 'done' | 'error';
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

/** 重新 arm（stop 后 / stuck 后手动投递）。 */
export async function resumeInbox(sessionId: string): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/resume`),
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

/** 本会话 C2 压缩态（用量预览）。 */
export async function fetchSessionCompression(
	sessionId: string,
): Promise<SessionCompression | null> {
	const sid = sessionId.trim();
	if (!sid) {
		return null;
	}
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sid)}/compression`),
			{cache: 'no-store'},
		);
		if (!res.ok) {
			return null;
		}
		return (await res.json()) as SessionCompression;
	} catch {
		return null;
	}
}

export type MemoryNoteRow = {
	id: string;
	type: string;
	scope: string;
	title: string;
	content: string;
	confidence: number;
	last_used_at?: string | null;
	updated_at?: string;
};

/** 记忆侧栏：列出 active notes（工作区 + user）。 */
export async function interruptChat(sessionId: string): Promise<void> {

	try {
		await fetchWithTimeout(apiUrl('/v1/interrupt'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({session_id: sessionId}),
		});
	} catch {
		/* 忽略 */
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

export async function fetchSessionTask(
	sessionId: string,
): Promise<SessionTaskInfo | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/task`),
			{method: 'GET', headers: authHeaders()},
		);
		if (!res.ok) return null;
		return (await res.json()) as SessionTaskInfo;
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

export async function setWorkspace(path: string): Promise<string> {
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
): Promise<WorkspaceListing> {
	const q = new URLSearchParams();
	if (path) {
		q.set('path', path);
	}
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
	return (await res.json()) as WorkspaceListing;
}

export type WorkspaceGraphFile = {
	id: string;
	name: string;
	layer: string;
	pkg: string;
};

export type WorkspaceGraphPackage = {
	id: string;
	name: string;
	layer: string;
	files: number;
};

export type WorkspaceGraphEdge = {from: string; to: string};

export type WorkspaceGraph = {
	ok: boolean;
	cwd: string;
	fileCount: number;
	truncated: boolean;
	layers: string[];
	files: WorkspaceGraphFile[];
	fileEdges: WorkspaceGraphEdge[];
	packages: WorkspaceGraphPackage[];
	packageEdges: WorkspaceGraphEdge[];
};

export async function fetchWorkspaceGraph(): Promise<WorkspaceGraph> {
	const res = await fetchWithTimeout(
		apiUrl('/v1/workspace/graph'),
		{cache: 'no-store'},
		45_000,
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
	return (await res.json()) as WorkspaceGraph;
}

export type WorkspaceSearchResult = {
	cwd: string;
	query: string;
	hits: WorkspaceEntry[];
	truncated: boolean;
};

export async function searchWorkspace(q: string): Promise<WorkspaceSearchResult> {
	const params = new URLSearchParams({q});
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
	return (await res.json()) as WorkspaceSearchResult;
}

export async function readWorkspaceFile(path: string): Promise<WorkspaceFile> {
	const q = new URLSearchParams({path});
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
	return (await res.json()) as WorkspaceFile;
}

export async function statWorkspaceFile(path: string): Promise<WorkspaceFileStat> {
	const q = new URLSearchParams({path});
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
	return (await res.json()) as WorkspaceFileStat;
}

export async function writeWorkspaceFile(
	path: string,
	text: string,
): Promise<WorkspaceFile> {
	const res = await fetchWithTimeout(apiUrl('/v1/workspace/file'), {
		method: 'PUT',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({path, text}),
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
	return (await res.json()) as WorkspaceFile;
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
	options?: {pathPrefix?: string; agentId?: string; limit?: number},
): Promise<WorkspaceJournalResult> {
	const q = new URLSearchParams();
	if (options?.pathPrefix?.trim()) q.set('path_prefix', options.pathPrefix.trim());
	if (options?.agentId?.trim()) q.set('agent_id', options.agentId.trim());
	if (options?.limit) q.set('limit', String(options.limit));
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

export async function gitStatus(): Promise<GitStatusResult> {
	const res = await fetchWithTimeout(apiUrl('/v1/workspace/git/status'), {cache: 'no-store'});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return (await res.json()) as GitStatusResult;
}

export async function gitLog(limit = 20): Promise<GitLogResult> {
	const q = new URLSearchParams({limit: String(limit)});
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
	return (await res.json()) as GitLogResult;
}

export async function gitBranches(): Promise<GitBranchesResult> {
	const res = await fetchWithTimeout(apiUrl('/v1/workspace/git/branches'), {cache: 'no-store'});
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return (await res.json()) as GitBranchesResult;
}

export async function gitFileDiff(path: string): Promise<FileDiffResult> {
	const q = new URLSearchParams({path});
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
	return (await res.json()) as FileDiffResult;
}

export async function execWorkspaceTerminal(
	command: string,
	timeoutS?: number,
): Promise<TerminalResult> {
	const res = await fetchWithTimeout(
		apiUrl('/v1/workspace/terminal/exec'),
		{
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({
				command,
				...(timeoutS ? {timeout_s: timeoutS} : {}),
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
	return (await res.json()) as TerminalResult;
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

export async function setRewindGcSettings(
	keepRecent: number | null,
	maxBytes: number | null,
): Promise<boolean> {
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
		return res.ok;
	} catch {
		return false;
	}
}

/** 记忆系统开关：设置读取/写入（持久到 .xeyo/settings.json 的 memory 段 + 运行时 os.environ）。 */
export type MemorySwitch = {
	key: string;
	label: string;
	value: string;
	allowed: string[];
	source: 'settings' | 'env' | 'default';
	default: string;
};

export type MemorySwitchesResponse = {
	ok: boolean;
	switches?: Record<string, MemorySwitch>;
	message?: string;
	error?: string;
};

export async function getMemorySwitches(): Promise<MemorySwitchesResponse | null> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory'), {cache: 'no-store'});
		if (!res.ok) return null;
		return (await res.json()) as MemorySwitchesResponse;
	} catch {
		return null;
	}
}

export async function setMemorySwitches(
	updates: Record<string, string | boolean>,
): Promise<MemorySwitchesResponse | null> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory'), {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				...authHeaders(),
			},
			body: JSON.stringify({updates}),
		});
		if (!res.ok) return null;
		return (await res.json()) as MemorySwitchesResponse;
	} catch {
		return null;
	}
}

export type MemorySnapshotResult = {
	ok: boolean;
	day?: string;
	rc?: number;
	tail?: string;
	error?: string;
};

export async function runMemorySnapshot(): Promise<MemorySnapshotResult | null> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/settings/memory/snapshot'), {
			method: 'POST',
			headers: {...authHeaders()},
		});
		if (!res.ok) return null;
		return (await res.json()) as MemorySnapshotResult;
	} catch {
		return null;
	}
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

export async function loadBashPolicy(): Promise<BashPolicy | null> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/workspace/policy-bash'), {
			cache: 'no-store',
		});
		if (!res.ok) return null;
		return (await res.json()) as BashPolicy;
	} catch {
		return null;
	}
}

export async function saveBashPolicy(input: {
	bash_routing?: 'auto' | 'off';
	bash_escalate?: number;
}): Promise<BashPolicy | null> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/workspace/policy-bash'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify(input),
		});
		if (!res.ok) return null;
		return (await res.json()) as BashPolicy;
	} catch {
		return null;
	}
}
