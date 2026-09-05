/**
 * jobs.ts — 42 号后台任务域 API 客户端。
 *
 * - fetchSessionJobs：GET /v1/sessions/{sid}/jobs（owner 快照；播种/轮询用）。
 * - normalizeJobSnapshots：SSE jobs 帧 / GET 响应统一归一化（防御式）。
 * - sortJobsForPanel：弹层确定性排序（活跃 startedAt 升序在前，终态 finishedAt
 *   降序在后；map 序永不参与——42 号 §8）。
 *
 * 纪律（冻结口径 6）：UI 只读——无流直读、无人类中断行；数据全部来自
 * whole-value 快照（SSE 帧 + GET），渲染层零 RPC。
 */
import {apiUrl} from '@/lib/apiBase';
import {fetchWithTimeout} from './core';

export type JobStatus = 'running' | 'stopping' | 'succeeded' | 'failed' | 'killed';

/** 后端 JobRecord.to_dict() 的前端视图（只声明 GUI 用到的字段，其余透传）。 */
export type JobSnapshot = {
	job_id: string;
	kind: string;
	label: string;
	status: JobStatus;
	detail: string;
	reported: boolean;
	started_at: number;
	finished_at: number;
	[key: string]: unknown;
};

export type SessionJobsResult = {
	jobs: JobSnapshot[];
	version: number;
	wake_budget_left: number;
};

function isJobLike(v: unknown): v is JobSnapshot {
	if (!v || typeof v !== 'object') return false;
	const j = v as Record<string, unknown>;
	return (
		typeof j.job_id === 'string' &&
		j.job_id.length > 0 &&
		typeof j.status === 'string'
	);
}

/** SSE jobs 帧 / GET 响应统一归一化：逐条防御，坏行跳过（宁缺勿崩）。 */
export function normalizeJobSnapshots(raw: unknown): JobSnapshot[] {
	if (!Array.isArray(raw)) return [];
	const out: JobSnapshot[] = [];
	for (const item of raw) {
		if (isJobLike(item)) out.push(item);
	}
	return out;
}

const ACTIVE_RANK: Record<string, number> = {running: 0, stopping: 1};

/** 弹层排序：活跃行前（startedAt 升序），终态行后（finishedAt 降序），并列按启动序。 */
export function sortJobsForPanel(jobs: JobSnapshot[]): JobSnapshot[] {
	return [...jobs].sort((a, b) => {
		const ra = ACTIVE_RANK[a.status];
		const rb = ACTIVE_RANK[b.status];
		if (ra !== undefined || rb !== undefined) {
			if (ra === undefined) return 1;
			if (rb === undefined) return -1;
			if (ra !== rb) return ra - rb;
		}
		if (ra !== undefined) {
			// 同为活跃：startedAt 升序。
			return a.started_at - b.started_at || a.job_id.localeCompare(b.job_id);
		}
		// 同为终态：finishedAt 降序。
		return b.finished_at - a.finished_at || a.job_id.localeCompare(b.job_id);
	});
}

/** running + stopping 计数（角标；为零整个隐藏）。 */
export function activeJobsCount(jobs: JobSnapshot[]): number {
	return jobs.reduce(
		(n, j) => n + (j.status === 'running' || j.status === 'stopping' ? 1 : 0),
		0,
	);
}

/** GET /v1/sessions/{sid}/jobs → owner 快照。 */
export async function fetchSessionJobs(
	sessionId: string,
): Promise<SessionJobsResult> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/jobs`),
			{method: 'GET'},
		);
		if (!res.ok) {
			return {jobs: [], version: 0, wake_budget_left: 0};
		}
		const data = (await res.json()) as Record<string, unknown>;
		return {
			jobs: normalizeJobSnapshots(data.jobs),
			version: Number.isFinite(Number(data.version)) ? Number(data.version) : 0,
			wake_budget_left: Number.isFinite(Number(data.wake_budget_left))
				? Number(data.wake_budget_left)
				: 0,
		};
	} catch {
		return {jobs: [], version: 0, wake_budget_left: 0};
	}
}
