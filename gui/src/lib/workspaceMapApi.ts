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

export async function fetchWorkspaceGraph(
	opts?: {refresh?: boolean},
): Promise<WorkspaceGraph> {
	const q = opts?.refresh ? '?refresh=true' : '';
	const res = await fetchWithTimeout(
		apiUrl(`/v1/workspace/graph${q}`),
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
	return (await res.json()) as WorkspaceGraph;
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
	path: string;
	symbols: WorkspaceOutlineSymbol[];
};

export async function fetchWorkspaceOutline(
	path: string,
): Promise<WorkspaceOutline> {
	const q = new URLSearchParams({path});
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
	return (await res.json()) as WorkspaceOutline;
}

export async function explainMapNode(
	id: string,
	kind: 'file' | 'package',
): Promise<{ok: boolean; summary: string; source?: string}> {
	const res = await fetchWithTimeout(
		apiUrl('/v1/workspace/map/explain'),
		{
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({id, kind}),
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
	return (await res.json()) as {ok: boolean; summary: string; source?: string};
}
