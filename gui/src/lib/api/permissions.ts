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

/**
 * 裁决回执：ok=false 必须带上"为什么"。
 *
 * 后端（server/routers/control.py::_resolve_miss_reason）区分两种没生效：
 * - `already_resolved`：别处已经答过（远程/微信，或双击）—— 裁决其实落地了；
 * - `no_such_request`：内存挂起项不在（最常见是服务重启）—— 重试也修不好。
 * 旧实现只回一个 boolean，界面于是把这两类都念成"提交失败，请重试"。
 */
export type ResolveReceipt = {ok: boolean; reason: string; message: string};

const NETWORK_FAIL: ResolveReceipt = {
	ok: false,
	reason: 'network',
	message: '请求未送达后端',
};

async function receiptOf(res: Response): Promise<ResolveReceipt> {
	const payload = await res.json().catch(() => null);
	if (!res.ok) {
		return {ok: false, reason: 'http', message: formatErrorDetail(payload, res.status)};
	}
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
		return {ok: false, reason: 'receipt_not_object', message: '回执不是对象'};
	}
	const body = payload as Record<string, unknown>;
	if (body.ok === true) {
		return {ok: true, reason: '', message: ''};
	}
	if (typeof body.ok !== 'boolean') {
		// 200 却没写 ok：不能读成生效，也不能拿 HTTP 措辞凑话（"HTTP 200"对人没有信息量）。
		return {ok: false, reason: 'receipt_missing_ok', message: '回执缺少 ok 字段'};
	}
	const reason = typeof body.reason === 'string' ? body.reason : '';
	return {
		ok: false,
		reason,
		message: reason || 'not_applied',
	};
}

/**
 * 把"没生效"翻译成人话。三类要分开：
 * 已被别处答复不是失败（裁决落地了，面板该收起）；挂起项不在服务端时重试无意义；
 * 其余才带后端原话。旧实现三种都念成"提交失败，请重试"。
 */
export function resolveFailureText(r: ResolveReceipt): {tone: 'info' | 'error'; text: string} {
	if (r.reason === 'already_resolved') {
		return {tone: 'info', text: '这项已在别处答复（远程或另一次点击），面板已收起'};
	}
	if (r.reason === 'no_such_request') {
		return {tone: 'error', text: '挂起项已不在服务端（服务可能重启过）：请等待引擎重新发起'};
	}
	return {tone: 'error', text: `提交未生效：${r.message || '未知原因'}`};
}

export async function resolvePermission(
	requestId: string,
	approved: boolean,
	actor = 'desktop',
	outcome?: 'allow' | 'deny' | 'remind',
	remember = false,
): Promise<ResolveReceipt> {
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
		return await receiptOf(res);
	} catch (err) {
		return {
			...NETWORK_FAIL,
			message: err instanceof Error ? err.message : NETWORK_FAIL.message,
		};
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

/**
 * T10：撤销一个 always-allow 授权。
 *
 * 回执不是 boolean：这个端点 200 + ok:false 的唯一含义是"台账里没有这条"
 * （loopback 与 id 形态不合法都在前面 4xx 掉了，见 control.py::revoke_permission_grant）。
 * 旧实现回 false，界面据此说"撤销失败，请重试"——重试一条已经消失的授权永远修不好，
 * 而且那一行还可能只是列表过期了。
 */
export async function revokePermissionGrant(
	grantId: string,
): Promise<ResolveReceipt> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/permissions/grants/${encodeURIComponent(grantId)}`),
			{method: 'DELETE'},
		);
		return await receiptOf(res);
	} catch (err) {
		return {
			...NETWORK_FAIL,
			message: err instanceof Error ? err.message : NETWORK_FAIL.message,
		};
	}
}

/** 撤销没生效的说法：已不在台账 ≠ 失败重试。 */
export function revokeFailureText(r: ResolveReceipt): {
	tone: 'info' | 'error';
	text: string;
} {
	if (r.reason === 'grant_not_found') {
		return {
			tone: 'info',
			text: '这条授权已不在台账里（可能已到期或在别处撤销过），列表已重新读取',
		};
	}
	return {tone: 'error', text: `撤销未生效：${r.message || '未知原因'}`};
}

/** 提交对一个挂起提问（AskUserQuestion）的作答。 */
export async function resolveAsk(
	requestId: string,
	answer: string,
	actor = 'desktop',
): Promise<ResolveReceipt> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/ask/resolve'), {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({request_id: requestId, answer, actor}),
		});
		return await receiptOf(res);
	} catch (err) {
		return {
			...NETWORK_FAIL,
			message: err instanceof Error ? err.message : NETWORK_FAIL.message,
		};
	}
}

/** 批准或拒绝一个 Plan 模式下挂起的实现计划。 */
export async function resolvePlan(
	requestId: string,
	approved: boolean,
	actor = 'desktop',
): Promise<ResolveReceipt> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/plan/${encodeURIComponent(requestId)}/approve`),
			{
				method: 'POST',
				headers: {'Content-Type': 'application/json'},
				body: JSON.stringify({approved, actor}),
			},
		);
		return await receiptOf(res);
	} catch (err) {
		return {
			...NETWORK_FAIL,
			message: err instanceof Error ? err.message : NETWORK_FAIL.message,
		};
	}
}

/** 删除后端 session transcript 与内存 engine；成功返回 true。 */
