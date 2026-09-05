import {apiUrl} from '@/lib/apiBase';
import {authHeaders} from '@/lib/api/core';

/**
 * smoke-test #6：会话权限 preset 运行时活值读写。
 * 会话创建时 pin 的 preset 是默认值;显式切换后后端立即按新 preset 判定
 * （readonly / workspace-write / full）。fire-and-forget 写失败静默。
 */
export function setSessionRuntimePreset(
	sessionId: string,
	preset: string,
): void {
	if (!sessionId?.trim() || !preset) {
		return;
	}
	void fetch(
		apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/runtime-preset`),
		{
			method: 'POST',
			headers: {
				...authHeaders(),
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({permission_preset: preset}),
		},
	).catch(() => {
		// fire-and-forget：写失败不阻塞 UI / 当前回合。
	});
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
