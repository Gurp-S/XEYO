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
): Promise<string | null> {
	if (!sessionId?.trim()) {
		return null;
	}
	try {
		const res = await fetch(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/runtime-preset`),
			{headers: authHeaders()},
		);
		if (!res.ok) {
			return null;
		}
		const body = (await res.json()) as {permission_preset?: string | null};
		return body.permission_preset?.trim() || null;
	} catch {
		return null;
	}
}
