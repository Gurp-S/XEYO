export type UiRole = 'user' | 'assistant' | 'tool' | 'system';

export type ToolStatus = 'running' | 'waiting' | 'done' | 'error';

export type AgentMode = 'agent' | 'plan' | 'ask';

export type ChatMessage = {
	id: string;
	role: UiRole;
	text: string;
	toolName?: string;
	/** 后端 tool_use.id；并行同名工具配对用，勿仅靠 name。 */
	toolUseId?: string;
	/** 序列化的 tool 参数（role=tool）。优先于旧版 `call …` 文本前缀。 */
	toolInput?: string;
	/** 单行 tool 的就地生命周期（避免 call→result 重挂载闪烁）。 */
	toolStatus?: ToolStatus;
	/** 来自微信文件传输助手的镜像消息 */
	source?: 'remote';
	/** 当前 user 消息关联的后端媒体引用；不保存 Base64。 */
	mediaRefs?: string[];
	/** tool 调用前累积的 reasoning 快照（role=tool）。 */
	reasoningBefore?: string;
	/** reasoning 阶段耗时 ms（role=tool）。 */
	thoughtMs?: number;
	/** 独立 reasoning 块（text 为 reasoning 正文，不渲染为 prose）。 */
	isThought?: boolean;
	/**
	 * UI-only 行（如斜杠命令回显）：只进本地列表，不进 toApiMessages、不持久化后端。
	 */
	uiOnly?: boolean;
	/** 系统行形态：cmd=命令回执卡片（命令 flow 节点）；缺省=居中系统提示。 */
	noteKind?: 'cmd';
	/** 命令回执卡片标题（命令行原文，如 `/goal 介绍自己`）。 */
	noteTitle?: string;
	/** Rewind v2：checkpointId（来自 turn before_commit）。 */
	checkpointId?: string;
	createdAt: number;
};

/**
 * 一个打开的文件夹 = 一个工作区。
 * `rootPath` 为绝对文件夹路径；空表示仅未绑定聊天。
 */
export type ChatSpace = {
	id: string;
	name: string;
	/** 绝对工作区根；文件夹及所有嵌套文件均归属于此。 */
	rootPath: string;
	createdAt: number;
	updatedAt: number;
};

export type ChatUsage = {
	promptTokens: number;
	completionTokens: number;
	cacheHitTokens: number;
	cacheMissTokens: number;
	tokens: number;
	cny: number;
	requests: number;
	costSource: 'api' | 'estimate';
	/** 后端明确提供的上下文遥测；缺失时 Pasture 会降级为估算/旧快照。 */
	contextTokens?: number;
	contextLimit?: number;
	contextPercent?: number;
	contextSource?: 'runtime' | 'stream' | 'snapshot' | 'fallback';
	dataQuality?: 'measured' | 'estimated' | 'fallback' | 'stale';
	lastContextAt?: number;
	/** 发送给模型的上下文构成（按内容分类的 token 数），用于画分段用量条。 */
	contextBreakdown?: {category: string; label: string; tokens: number; chars?: number; soft_over?: boolean}[];
	/**
	 * 最近一次请求的输入命中/未命中/输出拆分（单轮，非累计）。
	 * 与 contextTokens 同轮，供「上下文构成」回退条使用——累计值会随会话
	 * 增长超过窗口，不能拿来画"本轮上下文构成"。
	 */
	lastCacheHitTokens?: number;
	lastCacheMissTokens?: number;
	lastCompletionTokens?: number;
	/** C2：已压实消息游标；>0 表示本会话已进入压缩态。 */
	compactCursor?: number;
	lastAction?: string;
	c2SummaryChars?: number;
};

export type ChatSession = {
	id: string;
	/** 所属工作区（已打开的文件夹） */
	spaceId: string;
	title: string;
	createdAt: number;
	updatedAt: number;
	/** smoke-test #3：用户手动归档（服务端 archive sidecar 为权威源；本地标记用于默认列表隐藏 + 已归档分组渲染）。 */
	archived?: boolean;
	/** 归档时间戳（本地落账用，与服务端 archivedAt 近似）。 */
	archivedAt?: number;
	/** 来自模型 API usage 的整个会话累计消耗，持久化在本地会话记录中。 */
	usage?: ChatUsage;
};

export type ChatHistoryBranch = {
	branchId: string;
	/** 后端 Agent 会话 ID；缺失时兼容地回退到本地 session ID。 */
	backendSessionId?: string;
	parentBranchId: string | null;
	createdAt: number;
	forkMessageId: string | null;
	label: string;
	messages: ChatMessage[];
};

export type ChatHistoryActiveBranch = {
	branchId: string;
	/** 后端 Agent 会话 ID；缺失时兼容地回退到本地 session ID。 */
	backendSessionId?: string;
	parentBranchId: string | null;
	createdAt: number;
	forkMessageId: string | null;
	label: string;
};

export type ChatHistoryState = {
	activeBranch: ChatHistoryActiveBranch;
	archivedBranches: ChatHistoryBranch[];
};

export type RollbackOperation = {
	operation_id: string;
	turn_id?: string | null;
	tool_name?: string;
	operation_type?: string;
	path?: string | null;
	status?: string;
	before_hash?: string | null;
	after_hash?: string | null;
	inverse_kind?: string | null;
	inverse_payload?: Record<string, unknown>;
	/** unified diff：回滚后相对当前工作区的变更预览 */
	preview_diff?: string | null;
};

export type RollbackPlan = {
	session_id: string;
	plan_id: string;
	source_revision_id?: string | null;
	target_turn_id?: string | null;
	generated_at: number;
	plan_hash: string;
	operation_ids: string[];
	conflicts: string[];
	requires_confirmation: boolean;
	status: string;
	metadata: {
		target_message_id?: string;
		edited_text_hash?: string;
		edited_text_length?: number;
		removed_message_count?: number;
		removed_turn_count?: number;
		workspace_root?: string;
		expires_at?: number;
		operations?: RollbackOperation[];
		[key: string]: unknown;
	};
};

export type RecoveryJob = {
	session_id: string;
	plan_id: string;
	job_id: string;
	idempotency_key?: string | null;
	status: string;
	created_at: number;
	updated_at: number;
	applied_operation_ids: string[];
	error?: string | null;
	metadata?: Record<string, unknown>;
};

/**
 * 显式回溯阶段机。UI 与持久化应优先读 `phase`；
 * `status` 保留一版供旧缓存/UI 兼容，由 phase 派生。
 */
export type RollbackPhase =
	| 'idle'
	| 'previewing'
	| 'blocked'
	| 'ready'
	| 'executing'
	| 'optimistic'
	| 'workspace_pending'
	| 'committed_truncating'
	| 'committed_resend_failed'
	| 'recovery_required'
	| 'completed'
	| 'failed';

export type RollbackPreviewState = {
	/** @deprecated 由 phase 派生；新代码请读 phase */
	status: 'idle' | 'loading' | 'ready' | 'blocked' | 'executing' | 'success' | 'error';
	phase: RollbackPhase;
	targetMessageId: string | null;
	editedText: string;
	plan: RollbackPlan | null;
	job: RecoveryJob | null;
	idempotencyKey: string | null;
	error: string | null;
	/** v2：默认同拍恢复；仅脏冲突时阻断 */
	restoreWorkspace?: boolean | null;
	/** Continue-and-Revert 自动发送；恢复检查点为 false */
	autoContinue?: boolean | null;
};

/** 回溯 v3 热路径：POST /rewind 的同步返回（transcript 已提交，恢复可能仍在后台）。 */
export type RewindHotpathResult = {
	rewind_id: string;
	mode: 'restore' | 'continue';
	transcript_committed: boolean;
	removed_rows: number;
	retained_rows: number;
	checkpoint_id: string | null;
	status: string;
	reused: boolean;
};

/** 回溯 v3 事件（rewind_events.jsonl latest-wins），切点 pill 与 Undo 的数据源。 */
export type RewindEvent = {
	rewind_id: string;
	session_id: string;
	mode: 'restore' | 'continue';
	ts: number;
	target_message_id: string;
	checkpoint_id: string;
	orphan_id: string;
	orphan_count: number;
	retained_row_count: number;
	after_message_id?: string;
	idempotency_key: string;
	pill_summary?: {edited_digest?: string; removed_rows?: number};
	status: string;
	undone: boolean;
	error?: string | null;
	restore?: {
		restored?: string[];
		deleted?: string[];
		unchanged?: string[];
		skipped_dirty?: string[];
		failed?: string[];
	} | null;
	undo?: Record<string, unknown>;
};

export type RewindCheckpointLookup = {
	checkpoint_id: string | null;
	entry_count?: number;
	anchor?: boolean;
};
