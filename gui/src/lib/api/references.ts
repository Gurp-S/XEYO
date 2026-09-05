import {apiUrl} from '@/lib/apiBase';
import {authHeaders} from '@/lib/api/core';

/**
 * GUI 的 @ 文件引用候选数据源。
 *
 * 对应后端 `GET /v1/references/files`（`server/routers/references.py`）：
 * 工作区内按相对路径子串匹配的只读候选清单。插入的 `@相对路径` 不内联
 * 文件内容——由 Agent 用既有文件工具按需读取（按需引用）。
 *
 * 失败静默：返回 `null`，由调用方维持空态，不阻塞输入。
 */

export type FileReferencesReport = {
	ok: boolean;
	files: string[];
};

export async function fetchFileReferences(
	workspace: string,
	q: string,
	signal?: AbortSignal,
): Promise<FileReferencesReport | null> {
	try {
		const params = new URLSearchParams();
		params.set('workspace', workspace.trim());
		if (q.trim()) {
			params.set('q', q.trim());
		}
		// 不走 fetchWithTimeout：候选请求由调用方按键击作废（AbortController），
		// 超时合并器会吞掉调用方 signal（core.ts 覆写 init.signal）。
		const res = await fetch(apiUrl(`/v1/references/files?${params.toString()}`), {
			headers: authHeaders(),
			cache: 'no-store',
			signal,
		});
		if (!res.ok) {
			return null;
		}
		const payload = (await res.json()) as Partial<FileReferencesReport>;
		return {
			ok: payload.ok !== false,
			files: Array.isArray(payload.files) ? payload.files : [],
		};
	} catch {
		return null;
	}
}
