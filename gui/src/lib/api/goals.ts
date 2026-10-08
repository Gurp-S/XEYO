/**
 * goals.ts — T9/41 号 Goal 域 API 客户端。
 *
 * 两个动词：
 * - fetchGoal：GET 投影（goal + driver 快照；未绑定 → null）。
 * - patchGoalAction：PATCH 动作（drop/new/edit/pause/resume）。
 *
 * 业主 2026-10-03 裁定废弃"自动续跑 + 待确认完成 + 轮次上限 + 受阻重开"这组功能：
 * `roundDriverAction`（POST round-driver）已从客户端删除，`confirm_complete` /
 * `continue` / `reopen` 也不再暴露（服务端仍接受，CLI 与远程通道未同步废弃）。
 * 类型里保留 `pending_complete` / `max_rounds` / `activation` 是因为**服务端仍发这些键**
 * ——客户端如实描述 wire，但 GUI 不再据它们行动。
 *
 * CAS 纪律（41 号 §5）：PATCH 动词带 revision 提交；409 goal_revision_conflict
 * 时返回 conflict（后端附当前 goal），调用方刷新后重试一次（禁盲写）。
 */
import {apiUrl} from '@/lib/apiBase';
import {fetchWithTimeout, formatErrorDetail} from './core';

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
		typeof g.title === 'string' &&
		typeof g.text === 'string' &&
		['active', 'paused', 'blocked', 'completed', 'abandoned'].includes(String(g.status)) &&
		Number.isInteger(g.revision) && Number(g.revision) >= 1 &&
		typeof g.pending_complete === 'boolean' &&
		Number.isInteger(g.rounds) && Number(g.rounds) >= 0 &&
		Number.isInteger(g.max_rounds) && Number(g.max_rounds) >= 0 &&
		typeof g.blocked_reason === 'string'
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
	/** false = 这一枪没读到（403/5xx/离线/形状变了）；不得据此判"没有目标"。 */
	ok: boolean;
	goal: GoalSnapshot | null;
	driver: GoalDriverSnapshot | null;
	message: string;
};

/** GET /v1/sessions/{sid}/goal → {goal, driver}；未绑定才是 {ok:true, goal:null}。 */
export async function fetchGoal(sessionId: string): Promise<GoalReadResult> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`),
		);
		if (!res.ok) {
			const payload = await res.json().catch(() => null);
			return {
				ok: false,
				goal: null,
				driver: null,
				message: formatErrorDetail(payload, res.status),
			};
		}
		const payload = (await res.json().catch(() => null)) as Record<
			string,
			unknown
		> | null;
		if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
			return {ok: false, goal: null, driver: null, message: 'receipt_not_object'};
		}
		const driver = isDriverLike(payload.driver) ? payload.driver : null;
		// GET 是 goal 字段平铺 + additive driver 键；未绑定返回 {}。
		if (Object.keys(payload).length === 0) return {ok: true, goal: null, driver, message: ''};
		if (!isGoalLike(payload)) return {ok: false, goal: null, driver: null, message: 'receipt_invalid'};
		return {ok: true, goal: payload, driver, message: ''};
	} catch (err) {
		return {
			ok: false,
			goal: null,
			driver: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

/**
 * 41 号里 GUI 会发的动作。业主 2026-10-03 裁定废弃这组功能后，
 * `confirm_complete` / `continue` / `reopen` 已从界面撤净，客户端也不再暴露；
 * 服务端仍接受它们（CLI / 远程通道未同步废弃）。
 */
export const GOAL_ACTIONS = [
	'drop',
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
	goal_id?: string;
	revision?: number;
	title?: string;
	text?: string;
};

/** PATCH /v1/sessions/{sid}/goal（T9 动作 + 41 号 edit）。 */
export async function patchGoalAction(
	sessionId: string,
	action: GoalAction,
	opts: GoalPatchOptions = {},
): Promise<GoalMutationResult> {
	const {goal_id, revision, title, text} = opts;
	return goalMutate(
		apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/goal`),
		{
			method: 'PATCH',
			body: {
				action,
				...(goal_id != null ? {goal_id} : {}),
				...(revision != null ? {revision} : {}),
				...(title != null ? {title} : {}),
				...(text != null ? {text} : {}),
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
			if (!goal) return {ok: false, conflict: null, message: 'receipt_invalid'};
			return {ok: true, goal, driver};
		}
		// 409 goal_revision_conflict：后端 handler 对含 error 的 dict detail 原样上抛
		// （app.py::_http_error），故 goal 在顶层、不在 detail 下。
		if (res.status === 409 && payload && isGoalLike(payload.goal)) {
			return {
				ok: false,
				conflict: payload.goal as GoalSnapshot,
				message: 'goal_revision_conflict',
			};
		}
		return {ok: false, conflict: null, message: formatErrorDetail(payload, res.status)};
	} catch (err) {
		return {
			ok: false,
			conflict: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}
