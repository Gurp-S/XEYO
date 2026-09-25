/** 工作区地图 API：图 / 符号大纲 / 按需解释。
 *  放在 api/ 外，避免被 dismantle rollback 清掉；api9 `workspace.ts` 落地后并入并改 import。
 */

import {apiUrl} from '@/lib/apiBase';
import {fetchWithTimeout, formatErrorDetail} from '@/lib/api/core';

export type WorkspaceGraphFile = {
	id: string;
	name: string;
	layer: string;
	pkg: string;
};

export type WorkspaceGraphPackage = {
	id: string;
	name: string;
	layer: string;
	files: number;
};

export type WorkspaceGraphEdge = {from: string; to: string};

export type WorkspaceGraph = {
	ok: boolean;
	cwd: string;
	fileCount: number;
	truncated: boolean;
	layers: string[];
	files: WorkspaceGraphFile[];
	fileEdges: WorkspaceGraphEdge[];
	packages: WorkspaceGraphPackage[];
	packageEdges: WorkspaceGraphEdge[];
};

/**
 * 地图三接口的 200 回执必须校验形状：它们的真失败走 HTTP 状态码，
 * 过去客户端把响应体直接 `as` 成结果类型，于是缺字段的 200 会被渲染成事实——
 * - `truncated` 不在体里 ⇒ 面板说"N 个文件"而不带"（已截断）"，把残缺说成完整；
 * - `fileCount` 不在体里 ⇒ 印成「undefined 个文件」；
 * - `files` 不在体里 ⇒ 卡片详情里 graph.files.find 当场抛（这一处连 ? 都没有）；
 * - `packages` / `packageEdges` 不在体里 ⇒ 图变成"这个工作区没有包、没有依赖"；
 * - `summary` 不在体里 ⇒ 摘要栏说「（无摘要）」，把读不出说成没有内容。
 * 抛错走 codeMapStore / AgentMapPanel 已有的 catch（显示 error 卡片），不改签名。
 */
function requirePayloadObject(payload: unknown, what: string): Record<string, unknown> {
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
		throw new Error(`${what}：回执不是对象，读不出结果`);
	}
	return payload as Record<string, unknown>;
}

function requireArray(o: Record<string, unknown>, key: string, what: string): void {
	if (!Array.isArray(o[key])) {
		throw new Error(`${what}：回执缺 ${key}`);
	}
}

export function parseWorkspaceGraph(payload: unknown): WorkspaceGraph {
	const o = requirePayloadObject(payload, '读取工作区地图');
	if (typeof o.ok !== 'boolean') {
		throw new Error('读取工作区地图：回执缺 ok');
	}
	if (typeof o.fileCount !== 'number' || typeof o.truncated !== 'boolean') {
		throw new Error('读取工作区地图：回执缺 fileCount / truncated —— 读不出就不能把残缺的图说成完整');
	}
	for (const key of ['files', 'fileEdges', 'packages', 'packageEdges', 'layers'] as const) {
		requireArray(o, key, '读取工作区地图');
	}
	return o as WorkspaceGraph;
}

export function parseWorkspaceOutline(payload: unknown): WorkspaceOutline {
	const o = requirePayloadObject(payload, '读取符号大纲');
	if (typeof o.ok !== 'boolean') {
		throw new Error('读取符号大纲：回执缺 ok');
	}
	requireArray(o, 'symbols', '读取符号大纲');
	for (const s of o.symbols as unknown[]) {
		if (!s || typeof s !== 'object' || typeof (s as {name?: unknown}).name !== 'string') {
			throw new Error('读取符号大纲：symbols 里有一条不是符号');
		}
	}
	return o as WorkspaceOutline;
}

export function parseMapExplain(
	payload: unknown,
): {ok: boolean; cwd: string; summary: string; source?: string} {
	const o = requirePayloadObject(payload, '读取节点说明');
	if (typeof o.ok !== 'boolean') {
		throw new Error('读取节点说明：回执缺 ok');
	}
	if (typeof o.summary !== 'string') {
		throw new Error('读取节点说明：回执缺 summary —— 读不出不等于这个节点没有说明');
	}
	return o as {ok: boolean; cwd: string; summary: string; source?: string};
}

export async function fetchWorkspaceGraph(
	opts?: {refresh?: boolean; root?: string},
): Promise<WorkspaceGraph> {
	const q = new URLSearchParams();
	if (opts?.refresh) q.set('refresh', 'true');
	if (opts?.root?.trim()) q.set('workspace', opts.root.trim());
	const suffix = q.toString() ? `?${q}` : '';
	const res = await fetchWithTimeout(
		apiUrl(`/v1/workspace/graph${suffix}`),
		{cache: 'no-store'},
		45_000,
	);
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceGraph(await res.json());
}

export type WorkspaceOutlineSymbol = {
	kind: string;
	name: string;
	start: number;
	end: number;
	parent: string | null;
	signature: string;
	approximate: boolean;
};

export type WorkspaceOutline = {
	ok: boolean;
	cwd: string;
	path: string;
	symbols: WorkspaceOutlineSymbol[];
};

export async function fetchWorkspaceOutline(
	path: string,
	root?: string,
): Promise<WorkspaceOutline> {
	const q = new URLSearchParams({path, ...(root?.trim() ? {workspace: root.trim()} : {})});
	const res = await fetchWithTimeout(
		apiUrl(`/v1/workspace/outline?${q}`),
		{cache: 'no-store'},
		20_000,
	);
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseWorkspaceOutline(await res.json());
}

export async function explainMapNode(
	id: string,
	kind: 'file' | 'package',
	root?: string,
): Promise<{ok: boolean; cwd: string; summary: string; source?: string}> {
	const res = await fetchWithTimeout(
		apiUrl('/v1/workspace/map/explain'),
		{
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({id, kind, ...(root?.trim() ? {workspace: root.trim()} : {})}),
		},
		30_000,
	);
	if (!res.ok) {
		let payload: unknown = null;
		try {
			payload = await res.json();
		} catch {
			/* 忽略 */
		}
		throw new Error(formatErrorDetail(payload, res.status));
	}
	return parseMapExplain(await res.json());
}
