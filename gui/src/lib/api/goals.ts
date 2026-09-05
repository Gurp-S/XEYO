/**
 * goals.ts — T9/41 号 Goal 域 API 客户端。
 *
 * 三个动词族：
 * - fetchGoal：GET 投影（goal + driver 快照；未绑定 → null）。
 * - patchGoalAction：PATCH 动作（confirm_complete/continue/drop/reopen/new/edit）。
 * - roundDriverAction：POST round-driver（41 号 armed 内存态显式开关）。
 *
 * CAS 纪律（41 号 §5）：PATCH 动词带 revision 提交；409 goal_revision_conflict
 * 时返回 conflict（后端附当前 goal），调用方刷新后重试一次（禁盲写）。
 * arm/disarm 不需要 CAS（armed 不落盘；arm 内部需要改 cap 时后端自取新鲜 revision）。
 */
import {apiUrl} from '@/lib/apiBase';
import {fetchWithTimeout} from './core';

export type GoalStatus = 'active' | 'paused' | 'blocked' | 'completed' | 'abandoned';

/** 后端 Goal.to_dict() 的前端视图（只声明 GUI 用到的字段，其余透传）。 */
export type GoalSnapshot = {
	goal_id: string;
	title: string;
	text: string;
	status: GoalStatus;
	pending_complete: boolean;
	candidate?: string;
	rounds: number;
	max_rounds: number;
	blocked_reason: string;
	revision: number;
	[key: string]: unknown;
};

/** 41 号 round-driver 内存态投影（GET/PATCH 响应与 SSE goal 帧同形）。 */
export type GoalDriverSnapshot = {
	activation: 'armed' | 'disarmed';
	pending: boolean;
	active_round: [string, number] | null;
};

/** chatStore 的 per-session goal 投影（whole-value；SSE 帧与 GET 双源同形写入）。 */
export type SessionGoalState = {
	goal: GoalSnapshot;
	driver: GoalDriverSnapshot | null;
};

function isGoalLike(v: unknown): v is GoalSnapshot {
	if (!v || typeof v !== 'object') return false;
	const g = v as Record<string, unknown>;
	return (
		typeof g.goal_id === 'string' &&
		g.goal_id.length > 0 &&
		typeof g.status === 'string'
	);
}

function isDriverLike(v: unknown): v is GoalDriverSnapshot {
	if (!v || typeof v !== 'object') return false;
	const d = v as Record<string, unknown>;
	return (
		(d.activation === 'armed' || d.activation === 'disarmed') &&
		typeof d.pending === 'boolean'
	);
}

/** SSE goal 帧 / GET 响应的统一归一化：非法载荷 → null（不渲染）。 */
export function normalizeSessionGoalState(
	goal: unknown,
	driver?: unknown,
): SessionGoalState | null {
	if (!isGoalLike(goal)) return null;
	return {
		goal,
		driver: isDriverLike(driver) ? driver : null,
	};
}

export type GoalReadResult = {
	goal: GoalSnapshot | null;
	driver: GoalDriverSnapshot | null;
};

/** GET /v1/sessions/{sid}/goal → {goal, driver}；未绑定为 {null, driver?}。 */
export async function fetchGoal(sessionId: string): Promise<GoalReadResult> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`),
		);
		if (!res.ok) return {goal: null, driver: null};
		const payload = (await res.json().catch(() => null)) as Record<
			string,
			unknown
		> | null;
		if (!payload) return {goal: null, driver: null};
		const driver = isDriverLike(payload.driver) ? payload.driver : null;
		// GET 是 goal 字段平铺 + additive driver 键；未绑定返回 {}。
		if (!isGoalLike(payload)) return {goal: null, driver};
		return {goal: payload, driver};
	} catch {
		return {goal: null, driver: null};
	}
}

export const GOAL_ACTIONS = [
	'confirm_complete',
	'continue',
	'drop',
	'reopen',
	'new',
	'edit',
	'pause',
	'resume',
] as const;
export type GoalAction = (typeof GOAL_ACTIONS)[number];

export type GoalMutationResult =
	| {
			ok: true;
			goal: GoalSnapshot | null;
			driver: GoalDriverSnapshot | null;
	  }
	| {ok: false; conflict: GoalSnapshot | null; message: string};

export type GoalPatchOptions = {
	revision?: number;
	title?: string;
	text?: string;
	maxRounds?: number;
};

/** PATCH /v1/sessions/{sid}/goal（T9 动作 + 41 号 edit）。 */
export async function patchGoalAction(
	sessionId: string,
	action: GoalAction,
	opts: GoalPatchOptions = {},
): Promise<GoalMutationResult> {
	const {revision, title, text, maxRounds} = opts;
	return goalMutate(
		apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`),
		{
			method: 'PATCH',
			body: {
				action,
				...(revision != null ? {revision} : {}),
				...(title != null ? {title} : {}),
				...(text != null ? {text} : {}),
				...(maxRounds != null ? {max_rounds: maxRounds} : {}),
			},
		},
	);
}

/** POST /v1/sessions/{sid}/goal/round-driver（41 号 arm/disarm；内存态不落盘）。 */
export async function roundDriverAction(
	sessionId: string,
	action: 'arm' | 'disarm',
	maxRounds?: number,
): Promise<GoalMutationResult> {
	return goalMutate(
		apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/goal/round-driver`),
		{
			method: 'POST',
			body: {
				action,
				...(maxRounds != null ? {max_rounds: maxRounds} : {}),
			},
		},
	);
}

async function goalMutate(
	url: string,
	init: {method: string; body: Record<string, unknown>},
): Promise<GoalMutationResult> {
	try {
		const res = await fetchWithTimeout(url, {
			method: init.method,
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify(init.body),
		});
		const payload = (await res.json().catch(() => null)) as
			| (Record<string, unknown> & {detail?: unknown})
			| null;
		if (res.ok) {
			// PATCH 平铺返回 goal；round-driver 返回 {goal, driver}。两者兼容。
			const goal =
				payload && isGoalLike(payload.goal)
					? (payload.goal as GoalSnapshot)
					: payload && isGoalLike(payload)
						? (payload as GoalSnapshot)
						: null;
			const driver =
				payload && isDriverLike(payload.driver) ? payload.driver : null;
			return {ok: true, goal, driver};
		}
		// 409 goal_revision_conflict：detail 附当前 goal（客户端刷新再提交，禁盲写）。
		const detail =
			payload && typeof payload.detail === 'object' && payload.detail !== null
				? (payload.detail as Record<string, unknown>)
				: null;
		if (res.status === 409 && detail && isGoalLike(detail.goal)) {
			return {
				ok: false,
				conflict: detail.goal as GoalSnapshot,
				message: 'goal_revision_conflict',
			};
		}
		return {ok: false, conflict: null, message: `HTTP ${res.status}`};
	} catch (err) {
		return {
			ok: false,
			conflict: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}
