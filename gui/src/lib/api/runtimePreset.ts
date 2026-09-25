import {apiUrl} from '@/lib/apiBase';
import {authHeaders, formatErrorDetail} from '@/lib/api/core';

/**
 * smoke-test #6：会话权限 preset 运行时活值读写。
 * 会话创建时 pin 的 preset 是默认值;显式切换后后端立即按新 preset 判定
 * （readonly / workspace-write / full）。
 *
 * 写**必须可 await 且带回执**：这是权限面，UI 不能在本机乐观标记"已生效"
 * 而引擎其实还按旧 preset 判定（403 loopback 门禁 / 422 非法会话 id 都会这样）。
 */
export type RuntimePresetWrite = {ok: boolean; message: string};

/**
 * 读侧同样不能把"读不出"塌成 `null`：`null` 在后端语义里是"本会话未显式切换"，
 * 而 403 / 422 / 连不上后端是"我们根本不知道它现在是什么档"。
 * 两者都画成"没有选中项"会让用户在权限面上按一个自己没验证过的状态。
 */
export type RuntimePresetRead = {ok: boolean; preset: string | null; message: string};

export async function setSessionRuntimePreset(
	sessionId: string,
	preset: string,
): Promise<RuntimePresetWrite> {
	if (!sessionId?.trim()) {
		return {ok: false, message: 'no_session'};
	}
	if (!preset?.trim()) {
		return {ok: false, message: 'no_preset'};
	}
	try {
		const res = await fetch(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/runtime-preset`),
			{
				method: 'POST',
				headers: {
					...authHeaders(),
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({permission_preset: preset}),
			},
		);
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, message: formatErrorDetail(payload, res.status)};
		}
		const body = (payload ?? {}) as {ok?: boolean};
		if (body.ok === false) {
			return {ok: false, message: formatErrorDetail(payload, res.status)};
		}
		return {ok: true, message: ''};
	} catch (err) {
		return {
			ok: false,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export async function fetchSessionRuntimePreset(
	sessionId: string,
): Promise<RuntimePresetRead> {
	if (!sessionId?.trim()) {
		return {ok: false, preset: null, message: 'no_session'};
	}
	try {
		const res = await fetch(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/runtime-preset`),
			{headers: authHeaders()},
		);
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, preset: null, message: formatErrorDetail(payload, res.status)};
		}
		const body = payload as {ok?: unknown; permission_preset?: unknown} | null;
		if (!body || typeof body !== 'object' || body.ok !== true) {
			return {
				ok: false,
				preset: null,
				message: body && typeof body === 'object'
					? formatErrorDetail(payload, res.status)
					: 'receipt_not_object',
			};
		}
		if (!('permission_preset' in body)) {
			return {ok: false, preset: null, message: 'receipt_missing_preset'};
		}
		const v = body.permission_preset;
		if (v === null) {
			// 唯一的"确实知道没有活值"：后端认了这笔账。
			return {ok: true, preset: null, message: ''};
		}
		if (typeof v !== 'string' || !v.trim()) {
			return {ok: false, preset: null, message: 'receipt_bad_preset'};
		}
		return {ok: true, preset: v.trim(), message: ''};
	} catch (err) {
		return {
			ok: false,
			preset: null,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}
