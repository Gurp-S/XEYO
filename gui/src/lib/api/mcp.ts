import {apiUrl} from '@/lib/apiBase';
import {authHeaders, formatErrorDetail} from '@/lib/api/core';

export type McpToolView = {
	name: string;
	description: string;
	hidden: boolean;
};

export type McpServerView = {
	id: string;
	scope: string;
	enabled: boolean;
	auto_start: boolean;
	required: boolean;
	denied: boolean;
	trusted: boolean;
	status: 'declared' | 'unapproved' | 'denied' | 'ready' | 'failed' | string;
	error: string | null;
	/** 显式白名单（null = 全量可用）。 */
	enabled_tools: string[] | null;
	raw_tools: string[];
	tools: McpToolView[];
};

export type McpStatusReport = {
	ok: boolean;
	message?: string;
	enabled_extensions: boolean;
	workspace: string;
	servers: McpServerView[];
};

export async function fetchMcpStatus(): Promise<McpStatusReport> {
	try {
		const res = await fetch(apiUrl('/v1/mcp'), {headers: authHeaders()});
		if (!res.ok) {
			return {ok: false, message: `HTTP ${res.status}`, enabled_extensions: false, workspace: '', servers: []};
		}
		const body = (await res.json()) as McpStatusReport;
		if (!Array.isArray(body.servers)) {
			return {...body, servers: []};
		}
		return body;
	} catch (err) {
		return {
			ok: false,
			message: err instanceof Error ? err.message : String(err),
			enabled_extensions: false,
			workspace: '',
			servers: [],
		};
	}
}

export async function mcpOp(
	server: string,
	op: 'approve' | 'enable' | 'disable' | 'reload' | 'tool',
	extra?: {raw_tool?: string; enabled?: boolean},
): Promise<{ok: boolean; message?: string}> {
	try {
		const res = await fetch(apiUrl('/v1/mcp/op'), {
			method: 'POST',
			headers: {...authHeaders(), 'Content-Type': 'application/json'},
			body: JSON.stringify({server, op, ...extra}),
		});
		if (!res.ok) {
			// 服务端参数校验一律回 4xx，原因在 detail 里；不接住就会渲染成一条空白失败。
			const payload: unknown = await res.json().catch(() => null);
			return {ok: false, message: formatErrorDetail(payload, res.status)};
		}
		const body = (await res.json()) as {ok?: boolean; message?: string};
		return {ok: body.ok === true, message: body.message};
	} catch (err) {
		return {
			ok: false,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}

export type ExtensionToggleSet = {
	enabled: boolean;
};

export type PatchExtensionsBody = {
	enabled_extensions?: boolean;
	mcp_servers?: Record<string, ExtensionToggleSet>;
	skills?: Record<string, ExtensionToggleSet>;
	plugins?: Record<string, ExtensionToggleSet>;
};

export type PatchExtensionsResult = {
	ok: boolean;
	message?: string;
	/** 后端逐项失败清单（`plugins/x`、`skills/x`、`mcp_servers/x`）；非空即有项没落地。 */
	errors?: string[];
	applied?: {
		mcp_servers?: {id: string; enabled: boolean}[];
		skills?: {name: string; enabled: boolean}[];
		plugins?: {name: string; enabled: boolean}[];
		master?: boolean | null;
	};
};

/** 扩展层启停：整体 200 但逐项失败（后端吞异常进 errors）要显式判，否则面板假成功。 */
export async function patchExtensions(
	body: PatchExtensionsBody,
): Promise<PatchExtensionsResult> {
	try {
		const res = await fetch(apiUrl('/v1/extensions/settings'), {
			method: 'POST',
			headers: {...authHeaders(), 'Content-Type': 'application/json'},
			body: JSON.stringify(body),
		});
		const payload = (await res.json()) as PatchExtensionsResult & {message?: string};
		const errors = Array.isArray(payload.errors)
			? payload.errors.filter((e): e is string => typeof e === 'string')
			: [];
		const ok = res.ok && payload.ok === true && errors.length === 0;
		return {
			ok,
			message: payload.message || (errors.length ? errors.join('；') : undefined),
			errors,
			applied: payload.applied,
		};
	} catch (err) {
		return {
			ok: false,
			message: err instanceof Error ? err.message : String(err),
		};
	}
}