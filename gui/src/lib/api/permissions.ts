/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec api6: permissions，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 */
import {
	apiUrl,
} from '@/lib/apiBase';
import {
	fetchWithTimeout,
	formatErrorDetail,
} from './core';

export async function resolvePermission(
	requestId: string,
	approved: boolean,
	actor = 'desktop',
	outcome?: 'allow' | 'deny' | 'remind',
	remember = false,
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/permission/resolve'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({
				request_id: requestId,
				approved,
				actor,
				remember,
				...(outcome ? {outcome} : {}),
			}),
		});
		if (!res.ok) return false;
		const payload = (await res.json()) as {ok?: boolean};
		return payload.ok === true;
	} catch {
		return false;
	}
}

/** T10：always-allow 授权（"don't ask again"）条目。 */
export type PermissionGrantInfo = {
	grant_id: string;
	tool_name: string;
	fingerprint: string;
	scope: string;
	created_at: number;
	expires_at: number | null;
	actor: string;
};

/** T10：列出 always-allow 授权（空 scope = 全部）。 */
export type GrantsReport = {
	ok: boolean;
	grants: PermissionGrantInfo[];
	message: string;
};

/**
 * 授权台账是安全面：读不出绝不能画成"一条授权都没有"。
 * 所以 `ok:false` 与"空列表"是两种结果，`message` 带后端原话。
 */
export async function listPermissionGrants(
	scope?: string,
): Promise<GrantsReport> {
	const q = scope ? `?scope=${encodeURIComponent(scope)}` : '';
	try {
		const res = await fetchWithTimeout(apiUrl(`/v1/permissions/grants${q}`));
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, grants: [], message: formatErrorDetail(payload, res.status)};
		}
		if (!payload || !Array.isArray((payload as GrantsReport).grants)) {
			return {ok: false, grants: [], message: '后端回执缺少 grants 字段'};
		}
		if ((payload as {ok?: boolean}).ok === false) {
			return {
				ok: false,
				grants: [],
				message: formatErrorDetail(payload, res.status),
			};
		}
		return {ok: true, grants: (payload as GrantsReport).grants, message: ''};
	} catch (err) {
		return {ok: false, grants: [], message: (err as Error).message || '请求未送达后端'};
	}
}

/** T10：撤销一个 always-allow 授权。 */
export async function revokePermissionGrant(grantId: string): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/permissions/grants/${encodeURIComponent(grantId)}`),
			{method: 'DELETE'},
		);
		if (!res.ok) return false;
		const payload = (await res.json()) as {ok?: boolean};
		return payload.ok === true;
	} catch {
		return false;
	}
}

/** 提交对一个挂起提问（AskUserQuestion）的作答。 */
export async function resolveAsk(
	requestId: string,
	answer: string,
	actor = 'desktop',
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/ask/resolve'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({request_id: requestId, answer, actor}),
		});
		if (!res.ok) return false;
		const payload = (await res.json()) as {ok?: boolean};
		return payload.ok === true;
	} catch {
		return false;
	}
}

/** 批准或拒绝一个 Plan 模式下挂起的实现计划。 */
export async function resolvePlan(
	requestId: string,
	approved: boolean,
	actor = 'desktop',
): Promise<boolean> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/plan/${encodeURIComponent(requestId)}/approve`),
			{
				method: 'POST',
				headers: {'Content-Type': 'application/json'},
				body: JSON.stringify({approved, actor}),
			},
		);
		if (!res.ok) return false;
		const payload = (await res.json()) as {ok?: boolean};
		return payload.ok === true;
	} catch {
		return false;
	}
}

/** 删除后端 session transcript 与内存 engine；成功返回 true。 */
