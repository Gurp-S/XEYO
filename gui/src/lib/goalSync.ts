/**
 * goalSync.ts — GUI 侧 goal 投影的 whole-value 写回 + /goal 命令回执后的即时同步。
 *
 * 背景（2026-09-05 调查报告 §10-④）：SSE goal 帧只在 chat turn 起点出现，
 * POST /v1/slash 不产生 SSE；/goal 命令也不发消息 → 没有 turn → store 永远为空，
 * GoalDock（仅 store 非空挂载）就永远不显示。所以 /goal 创建成功后必须
 * 主动 GET 投影写进 store。
 */
import {fetchGoal, type SessionGoalState} from '@/lib/api/goals';
import {useChatStore} from '@/stores/chatStore';
import {goalReadToken, invalidateGoalReads} from './goalProjection';
import type {StoreApi} from 'zustand';
import type {ChatState} from '@/stores/chat/preStoreHelpers';

/** whole-value 写回 store（SSE goal 帧 / GET 投影 / 命令回执同步三源共用同形）。 */
export function writeGoalState(
	sessionId: string,
	state: SessionGoalState | null,
	set: StoreApi<ChatState>['setState'] = useChatStore.setState,
) {
	set(s => {
		const current = s.sessionGoalById[sessionId];
		if (current && state && current.goal.goal_id === state.goal.goal_id &&
			current.goal.revision > state.goal.revision) return s;
		invalidateGoalReads(sessionId);
		return {sessionGoalById: {...s.sessionGoalById, [sessionId]: state}};
	});
}

export type GoalSyncResult = {ok: boolean; note: string};

/**
 * 目标是否"活着"（active / paused / blocked）。这是唯一权威谓词：
 * 条带挂载、`/goal` 的反馈面选择都读它，不再各写一份状态清单。
 */
export function isGoalLive(
	state: SessionGoalState | null | undefined,
): state is SessionGoalState {
	if (!state) return false;
	const s = state.goal.status;
	return s === 'active' || s === 'paused' || s === 'blocked';
}

/**
 * /goal 发出后：拉一次权威投影并落 store（条带立即挂载）。
 * 落库一律写在 GUI 会话 id 上（GoalDock 按 chatStore.activeId 取数）。
 *
 * 业主 2026-10-03 裁定废弃"自动续跑"这组功能 ⇒ 这里不再 arm。服务端 arm 的唯一
 * 入口就是本函数（`server/routers/chat.py:924`：是否重新 armed 由用户显式操作，
 * 不自动），撤掉即停用：目标仍会创建/暂停/记账，但不会自己开下一轮。
 *
 * 返回 note 给调用方：投影读不到时用户只看到后端那句"已创建"，条带却没出现
 * ——那句沉默必须变成话。
 */
export async function syncGoalAfterCommand(
	guiSessionId: string,
	backendSessionId?: string,
): Promise<GoalSyncResult> {
	invalidateGoalReads(guiSessionId);
	const token = goalReadToken(guiSessionId);
	const candidates =
		backendSessionId && backendSessionId !== guiSessionId
			? [backendSessionId, guiSessionId]
			: [guiSessionId];
	let readFailure = '';
	for (const sid of candidates) {
		const r = await fetchGoal(sid);
		if (!token.isCurrent()) return {ok: false, note: '目标状态已更新，本次读取已失效'};
		if (!r.ok) {
			readFailure = r.message;
			continue;
		}
		const next = r.goal ? {goal: r.goal, driver: r.driver} : null;
		if (!isGoalLive(next)) {
			continue;
		}
		writeGoalState(guiSessionId, next);
		return {ok: true, note: ''};
	}
	if (readFailure) {
		return {
			ok: false,
			note: `目标投影读不到（${readFailure}）：界面没有显示目标`,
		};
	}
	return {
		ok: false,
		note: '后端已受理 /goal，但投影里没有活跃目标（可能当场已结束）',
	};
}
