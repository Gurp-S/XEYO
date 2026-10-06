/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec api5: memory，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 */
import {
	apiUrl,
} from '@/lib/apiBase';
import {
	fetchWithTimeout,
} from './core';

/** 把 finalized Thought 块同步到服务端 transcript（ui_thought 行）。 */
export async function syncUiThoughtsToServer(
	sessionId: string,
	thoughts: Array<{
		id: string;
		text: string;
		thoughtMs?: number;
		createdAt: number;
	}>,
): Promise<number> {
	if (!sessionId || thoughts.length === 0) {
		return 0;
	}
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/ui-thoughts`),
			{
				method: 'POST',
				headers: {'Content-Type': 'application/json'},
				body: JSON.stringify({
					thoughts: thoughts.map(t => ({
						id: t.id,
						text: t.text,
						thought_ms: t.thoughtMs,
						ts: t.createdAt / 1000,
					})),
				}),
			},
		);
		if (!res.ok) {
			return 0;
		}
		const payload = (await res.json()) as {written?: number};
		return payload.written ?? 0;
	} catch {
		return 0;
	}
}
