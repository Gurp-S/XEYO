/** 挂起 UI（Ask / 审批 / Plan）是否属于当前活跃会话。 */
export function pendingMatchesActiveSession(
	pendingSessionId: string | null | undefined,
	activeId: string | null | undefined,
): boolean {
	if (!activeId) {
		return false;
	}
	if (!pendingSessionId) {
		return true;
	}
	return pendingSessionId === activeId;
}

export type SessionPendingSlice = {
	pendingAsk?: {sessionId: string} | null;
	pendingPermission?: {sessionId: string} | null;
	pendingPlan?: {sessionId?: string | null} | null;
};

/** 删除/结束某 session 流时，清掉属于该 session 的全局 pending 挂起项。 */
export function clearPendingFieldsForSession<T extends SessionPendingSlice>(
	state: T,
	sessionId: string,
): Pick<T, 'pendingAsk' | 'pendingPermission' | 'pendingPlan'> {
	return {
		pendingAsk:
			state.pendingAsk?.sessionId === sessionId ? null : state.pendingAsk,
		pendingPermission:
			state.pendingPermission?.sessionId === sessionId
				? null
				: state.pendingPermission,
		pendingPlan:
			state.pendingPlan?.sessionId === sessionId ? null : state.pendingPlan,
	};
}

export type SessionErrorBannerSlice = {
	errorBanner: string | null;
	errorBannerSessionId?: string | null;
};

/** 错误横幅绑定到 session；message 为空则整体清除。 */
export function sessionErrorBannerPatch(
	sessionId: string | null | undefined,
	message: string | null,
): SessionErrorBannerSlice {
	if (!message) {
		return {errorBanner: null, errorBannerSessionId: null};
	}
	return {
		errorBanner: message,
		errorBannerSessionId: sessionId ?? null,
	};
}

export function errorBannerMatchesActiveSession(
	bannerSessionId: string | null | undefined,
	activeId: string | null | undefined,
): boolean {
	if (!bannerSessionId) {
		return true;
	}
	return pendingMatchesActiveSession(bannerSessionId, activeId);
}

/** Store 内读取：仅当错误条属于 activeId 时返回文案。 */
export function visibleErrorBanner(
	banner: string | null,
	bannerSessionId: string | null | undefined,
	activeId: string | null | undefined,
): string | null {
	if (!banner) {
		return null;
	}
	return errorBannerMatchesActiveSession(bannerSessionId, activeId)
		? banner
		: null;
}
