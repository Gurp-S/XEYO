/** 每会话的流式 / drain 状态（支持并行会话）。 */
export type SessionStreamState = {
	streamingText: string;
	streamingShown: string;
	isLoading: boolean;
	statusText: string;
	reasoningText: string;
	thoughtStartedAt: number | null;
	abortRef: AbortController | null;
	remoteStreaming: boolean;
	/** SSE onDone 后的打字机 drain；尾部渲染期间解除发送锁定。 */
	draining: boolean;
	/**
	 * 后端 turn 仍在跑，但本页 SSE 已断（刷新 / 短暂断网）。
	 * recoverStuckStream 不得 interrupt；应 reattach。
	 */
	turnDetached?: boolean;
	/** 最近一次已知的服务端 event_id（reattach cursor）。 */
	lastEventId?: number;
};

export const EMPTY_SESSION_STREAM: SessionStreamState = {
	streamingText: '',
	streamingShown: '',
	isLoading: false,
	statusText: '',
	reasoningText: '',
	thoughtStartedAt: null,
	abortRef: null,
	remoteStreaming: false,
	draining: false,
};

/** HMR / 热更新后旧全局流字段可能还在，但 sessionStreams 缺失。 */
export type LegacyStreamSlice = {
	sessionStreams?: Record<string, SessionStreamState>;
	streamingSessionId?: string | null;
	isLoading?: boolean;
	streamingText?: string;
	streamingShown?: string;
	statusText?: string;
	reasoningText?: string;
	thoughtStartedAt?: number | null;
	abortRef?: AbortController | null;
	remoteStreaming?: boolean;
	drainingSessionId?: string | null;
};

function streamMapOf(
	state: LegacyStreamSlice | undefined,
): Record<string, SessionStreamState> {
	return state?.sessionStreams ?? {};
}

function streamInactive(s: SessionStreamState): boolean {
	return (
		!s.isLoading &&
		!s.draining &&
		!s.remoteStreaming &&
		!s.abortRef &&
		!s.streamingText &&
		!s.streamingShown &&
		!s.statusText &&
		!s.reasoningText
	);
}

/** 将旧版全局流状态迁移为 per-session map（HMR / 刷新中间态）。 */
export function normalizeSessionStreams(
	state: LegacyStreamSlice | undefined,
): Record<string, SessionStreamState> {
	const existing = streamMapOf(state);
	if (Object.keys(existing).length > 0 || !state) {
		return existing;
	}
	const sid = state.streamingSessionId;
	if (!sid) {
		return {};
	}
	const legacyActive =
		Boolean(state.isLoading) ||
		Boolean(state.remoteStreaming) ||
		Boolean(state.drainingSessionId === sid) ||
		Boolean(state.abortRef) ||
		Boolean(state.streamingText) ||
		Boolean(state.streamingShown) ||
		Boolean(state.statusText);
	if (!legacyActive) {
		return {};
	}
	return patchSessionStream({}, sid, {
		isLoading: Boolean(state.isLoading),
		streamingText: state.streamingText ?? '',
		streamingShown: state.streamingShown ?? '',
		statusText: state.statusText ?? '',
		reasoningText: state.reasoningText ?? '',
		thoughtStartedAt: state.thoughtStartedAt ?? null,
		abortRef: state.abortRef ?? null,
		remoteStreaming: Boolean(state.remoteStreaming),
		draining: state.drainingSessionId === sid,
	});
}

export function getSessionStream(
	state: LegacyStreamSlice | undefined,
	sessionId: string,
): SessionStreamState {
	const map = state?.sessionStreams;
	if (!map) {
		return EMPTY_SESSION_STREAM;
	}
	return map[sessionId] ?? EMPTY_SESSION_STREAM;
}

export function patchSessionStream(
	prev: Record<string, SessionStreamState> | undefined,
	sessionId: string,
	patch: Partial<SessionStreamState>,
): Record<string, SessionStreamState> {
	const safePrev = prev ?? {};
	const cur = safePrev[sessionId] ?? EMPTY_SESSION_STREAM;
	const next = {...cur, ...patch};
	if (streamInactive(next)) {
		if (!(sessionId in safePrev)) {
			return safePrev;
		}
		const out = {...safePrev};
		delete out[sessionId];
		return out;
	}
	return {...safePrev, [sessionId]: next};
}

export function clearSessionStreamEntry(
	prev: Record<string, SessionStreamState> | undefined,
	sessionId: string,
): Record<string, SessionStreamState> {
	const safePrev = prev ?? {};
	if (!(sessionId in safePrev)) {
		return safePrev;
	}
	const out = {...safePrev};
	delete out[sessionId];
	return out;
}

export function sessionStreamActive(
	state: LegacyStreamSlice | undefined,
	sessionId: string,
): boolean {
	const s = getSessionStream(state, sessionId);
	return s.isLoading || s.draining;
}

export function sessionStreamBusy(
	state: LegacyStreamSlice | undefined,
	sessionId: string,
): boolean {
	return getSessionStream(state, sessionId).isLoading;
}

export function selectActiveSessionStream(
	state: LegacyStreamSlice & {activeId: string | null},
): SessionStreamState {
	const id = state.activeId;
	return id ? getSessionStream(state, id) : EMPTY_SESSION_STREAM;
}

export function selectRunningSessionIds(
	state: LegacyStreamSlice | undefined,
): string[] {
	const map = state?.sessionStreams;
	if (!map) {
		return [];
	}
	return Object.entries(map)
		.filter(([, s]) => s.isLoading || s.draining)
		.map(([id]) => id);
}

/** 稳定字符串，供 zustand selector 使用（避免每次返回新数组触发无限重渲染）。 */
export function selectRunningSessionKey(
	state: LegacyStreamSlice | undefined,
): string {
	return selectRunningSessionIds(state).sort().join('\0');
}

export function hasRemoteStreaming(state: LegacyStreamSlice | undefined): boolean {
	const map = state?.sessionStreams;
	if (!map) {
		return false;
	}
	return Object.values(map).some(s => s.remoteStreaming);
}

export function isAbortDead(abort: AbortController | null): boolean {
	return !abort || abort.signal.aborted;
}

/**
 * 流仍在飞：远程镜像、打字机排水、本地 AbortController 未死、或后端 detached turn。
 * isLoading 但 abort 已死且非 detached 是崩溃残留，不算 live（recoverStuckStream 应回收）。
 */
export function isSessionStreamLive(s: SessionStreamState): boolean {
	if (s.remoteStreaming || s.draining || s.turnDetached) {
		return true;
	}
	return s.abortRef !== null && !isAbortDead(s.abortRef);
}

/** 后端仍可能在跑：用于决定是否 reattach 而非 interrupt。 */
export function isTurnLikelyDetached(s: SessionStreamState): boolean {
	return Boolean(s.turnDetached) || (s.isLoading && isAbortDead(s.abortRef));
}
