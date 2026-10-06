import {useMemo} from 'react';
import {pendingMatchesActiveSession} from '@/lib/pendingForSession';
import {
	useChatStore,
	type PendingAskInfo,
	type PendingPermissionInfo,
	type PendingPlanInfo,
} from '@/stores/chatStore';
import {useChatUiStore} from '@/stores/chatUiStore';

function useActiveSessionId() {
	return useChatUiStore(s => s.activeId);
}

export function usePendingAskForActiveSession(): PendingAskInfo | null {
	const activeId = useActiveSessionId();
	const pending = useChatStore(s => s.pendingAsk);
	return useMemo(
		() =>
			pending && pendingMatchesActiveSession(pending.sessionId, activeId)
				? pending
				: null,
		[pending, activeId],
	);
}

export function usePendingPermissionForActiveSession(): PendingPermissionInfo | null {
	const activeId = useActiveSessionId();
	const pending = useChatStore(s => s.pendingPermission);
	return useMemo(
		() =>
			pending && pendingMatchesActiveSession(pending.sessionId, activeId)
				? pending
				: null,
		[pending, activeId],
	);
}

export function usePendingPlanForActiveSession(): PendingPlanInfo | null {
	const activeId = useActiveSessionId();
	const pending = useChatStore(s => s.pendingPlan);
	return useMemo(
		() =>
			pending && pendingMatchesActiveSession(pending.sessionId, activeId)
				? pending
				: null,
		[pending, activeId],
	);
}

/** Composer 融合外框已随 DSH 对齐拆除（dock 卡各自独立），故不再需要"有没有挂起面板"的聚合谓词。 */
