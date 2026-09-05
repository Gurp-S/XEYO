/**
 * goalSync.ts — GUI 侧 goal 投影的 whole-value 写回 + /goal 命令回执后的即时同步。
 *
 * 背景（2026-09-05 调查报告 §10-④）：SSE goal 帧只在 chat turn 起点出现，
 * POST /v1/slash 不产生 SSE；/goal 命令也不发消息 → 没有 turn → store 永远为空，
 * GoalDock（仅 store 非空挂载）就永远不显示。所以 /goal 创建成功后必须
 * 主动 GET 投影写进 store，再显式 arm 让轮驱动接管续跑。
 */
import {fetchGoal, roundDriverAction, type SessionGoalState} from '@/lib/api/goals';
import {useChatStore} from '@/stores/chatStore';

/** whole-value 写回 store（SSE goal 帧 / GET 投影 / 命令回执同步三源共用同形）。 */
export function writeGoalState(
	sessionId: string,
	state: SessionGoalState | null,
) {
	useChatStore.setState(s => ({
		sessionGoalById: {...s.sessionGoalById, [sessionId]: state},
	}));
}

/**
 * /goal 发出后：拉投影 → 落 store（dock 立即挂载）→ 显式 arm。
 * arm 口径：/goal 是用户的显式意图命令，由它触发的 arm 不算「自动 armed」
 * （armed 不落盘，重启后自然回到 disarmed，41 号冻结口径不变）。
 * 落库一律写在 GUI 会话 id 上（GoalDock 按 chatStore.activeId 取数）；
 * goal 实际绑定在后端会话 id 时，对后端 id arm，展示仍归 GUI id。
 */
export async function syncGoalAfterCommand(
	guiSessionId: string,
	backendSessionId?: string,
): Promise<void> {
	const candidates =
		backendSessionId && backendSessionId !== guiSessionId
			? [backendSessionId, guiSessionId]
			: [guiSessionId];
	for (const sid of candidates) {
		const {goal, driver} = await fetchGoal(sid);
		if (!goal || goal.status === 'completed' || goal.status === 'abandoned') {
			continue;
		}
		writeGoalState(guiSessionId, {goal, driver});
		// 显式 arm：round-driver POST（内存态不落盘）；arm 后端会开轮踢 agent。
		const res = await roundDriverAction(sid, 'arm');
		if (res.ok && res.goal) {
			writeGoalState(guiSessionId, {
				goal: res.goal,
				driver: res.driver ?? driver,
			});
		}
		return;
	}
}
