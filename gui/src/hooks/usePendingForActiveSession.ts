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

/** Composer 融合外框：当前 session 是否有 Ask / 审批 / Plan 挂起。 */
export function useHasComposerPendingDock(): boolean {
	const activeId = useActiveSessionId();
	return useChatStore(s => {
		if (!activeId) {
			return false;
		}
		const perm = s.pendingPermission;
		const ask = s.pendingAsk;
		const plan = s.pendingPlan;
		return (
			Boolean(perm && pendingMatchesActiveSession(perm.sessionId, activeId)) ||
			Boolean(ask && pendingMatchesActiveSession(ask.sessionId, activeId)) ||
			Boolean(plan && pendingMatchesActiveSession(plan.sessionId, activeId))
		);
	});
}
