import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout} from '@/lib/api/core';

/**
 * 插件管理面板数据源（扩展中心「插件」页）。
 *
 * 对应后端 `GET /v1/plugins`（`server/routers/plugins.py`）：返回发现视图 +
 * lockfile 登记 + 漂移 + 坏清单。只读展示；启停走
 * `POST /v1/extensions/settings`（plugins 逐项 enabled，见 api/mcp.ts 的
 * `patchExtensions`）。
 */

export type PluginView = {
	name: string;
	/** 当前生效态（settings.json plugins.<name>.enabled）。 */
	enabled: boolean;
	/** manifest 声明态（plugin.yaml/manifest 的 enabled）。 */
	declared: boolean;
	source_scope: string;
	version: string;
	min_xeyo: string;
	description: string;
	source: string;
	source_type: string;
	skills: string[];
	mcp_servers: string[];
	has_hooks: boolean;
};

export type PluginsReport = {
	ok: boolean;
	message?: string;
	enabled_extensions: boolean;
	plugin_market: boolean;
	workspace_settings: string;
	plugins: PluginView[];
	registered: string[];
	errors: string[];
	drift: boolean;
};

/** 显式启停配置视图（home+workspace 合并，只含 settings.json 中显式声明的条目）。 */
export type ExtensionSettingsView = {
	ok: boolean;
	message?: string;
	enabled_extensions: boolean;
	plugins: Record<string, {enabled: boolean}>;
	skills: Record<string, {enabled: boolean}>;
	mcp_servers: Record<string, {enabled: boolean; auto_start: boolean}>;
};

export async function fetchExtensionSettings(): Promise<ExtensionSettingsView> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/extensions/settings'), {
			headers: authHeaders(),
			cache: 'no-store',
		});
		if (!res.ok) {
			return {ok: false, message: `HTTP ${res.status}`, enabled_extensions: false, plugins: {}, skills: {}, mcp_servers: {}};
		}
		const body = (await res.json()) as Partial<ExtensionSettingsView>;
		return {
			ok: body.ok !== false,
			message: body.message,
			enabled_extensions: body.enabled_extensions === true,
			plugins: body.plugins || {},
			skills: body.skills || {},
			mcp_servers: body.mcp_servers || {},
		};
	} catch (err) {
		return {
			ok: false,
			message: err instanceof Error ? err.message : String(err),
			enabled_extensions: false,
			plugins: {},
			skills: {},
			mcp_servers: {},
		};
	}

}

export async function fetchPlugins(): Promise<PluginsReport> {
	try {
		const res = await fetchWithTimeout(apiUrl('/v1/plugins'), {
			headers: authHeaders(),
			cache: 'no-store',
		});
		if (!res.ok) {
			return {
				ok: false,
				message: `HTTP ${res.status}`,
				enabled_extensions: false,
				plugin_market: false,
				workspace_settings: '',
				plugins: [],
				registered: [],
				errors: [],
				drift: false,
			};
		}
		const body = (await res.json()) as Partial<PluginsReport>;
		return {
			ok: body.ok !== false,
			message: body.message,
			enabled_extensions: body.enabled_extensions === true,
			plugin_market: body.plugin_market === true,
			workspace_settings: body.workspace_settings || '',
			plugins: Array.isArray(body.plugins) ? body.plugins : [],
			registered: Array.isArray(body.registered) ? body.registered : [],
			errors: Array.isArray(body.errors) ? body.errors.map(String) : [],
			drift: body.drift === true,
		};
	} catch (err) {
		return {
			ok: false,
			message: err instanceof Error ? err.message : String(err),
			enabled_extensions: false,
			plugin_market: false,
			workspace_settings: '',
			plugins: [],
			registered: [],
			errors: [],
			drift: false,
		};
	}
}