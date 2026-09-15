import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout} from '@/lib/api/core';

/**
 * 本地模型（llama.cpp）控制面。
 *
 * 后端只维护**一个** llama-server 实例（单实例约束见 `python/localmodels/manager.py`
 * 头部：8GB 级显存装不下两支量化权重常驻）。所以这里的动作语义是：
 * - `setLocalModelSettings` 只改配置；
 * - `startLocalModel` 立刻返回 `state=starting`，加载进度靠轮询 `getLocalModels`；
 * - `switchLocalModel` 运行中等于"停旧起新"。
 */

export type LocalModelState = 'stopped' | 'starting' | 'running' | 'error';

/** 登记表里的一支模型（只读；来自后端 `localmodels.catalog`）。 */
export type LocalModelEntry = {
	id: string;
	label: string;
	filename: string;
	repo: string;
	repo_file: string;
	params_b: number;
	/** MoE 的激活参数量；dense 模型为 null。 */
	active_params_b: number | null;
	native_ctx: number;
	size_bytes: number;
	extra_args: string[];
	note: string;
	/** 权重是否已就绪（后端按字节数达标判定，半截文件不算）。 */
	present: boolean;
	path: string;
	/** 已落盘字节数（展示下载进度用）。 */
	downloaded_bytes: number;
};

export type LocalModelStatus = {
	state: LocalModelState;
	model: string;
	pid: number | null;
	host: string;
	port: number;
	base_url: string;
	started_at: number;
	uptime_s: number;
	error: string;
	log_path: string;
	healthy: boolean;
};

export type LocalModelSettings = {
	enabled: boolean;
	active_model: string;
	models_dir: string;
	binary: string;
	host: string;
	port: number;
	ctx: number;
	gpu_layers: number;
	extra_args: string;
};

export type LocalModelsSnapshot = {
	ok: boolean;
	settings: LocalModelSettings;
	status: LocalModelStatus;
	models: LocalModelEntry[];
	binary: {path: string; found: boolean};
	models_dir: string;
	base_url: string;
	/** `env` = 环境变量口径；`settings` = 设置面板口径；`allowed` = 二者之或。 */
	gate: {env: boolean; settings: boolean; allowed: boolean};
	error?: string;
};

export type LocalModelSettingsPatch = Partial<LocalModelSettings>;

function qs(workspace?: string): string {
	const ws = workspace?.trim();
	return ws ? `?workspace=${encodeURIComponent(ws)}` : '';
}

async function readSnapshot(res: Response): Promise<LocalModelsSnapshot | null> {
	try {
		const body = (await res.json()) as LocalModelsSnapshot;
		return body;
	} catch {
		return null;
	}
}

/** 拉取全景快照（设置 + 运行态 + 可用模型 + 二进制探测）。 */
export async function getLocalModels(
	workspace?: string,
): Promise<LocalModelsSnapshot | null> {
	try {
		const res = await fetchWithTimeout(apiUrl(`/v1/local-models${qs(workspace)}`), {
			cache: 'no-store',
		});
		return await readSnapshot(res);
	} catch {
		return null;
	}
}

/** 写设置。`enabled` 落盘即同时打开执行面与后端 SSRF 白名单。 */
export async function setLocalModelSettings(
	patch: LocalModelSettingsPatch,
	workspace?: string,
): Promise<LocalModelsSnapshot | null> {
	try {
		const res = await fetchWithTimeout(apiUrl(`/v1/local-models${qs(workspace)}`), {
			method: 'POST',
			headers: {'Content-Type': 'application/json', ...authHeaders()},
			body: JSON.stringify({settings: patch, workspace}),
		});
		return await readSnapshot(res);
	} catch {
		return null;
	}
}

/** 拉起服务（立即返回；加载进度看 `status.state`）。 */
export async function startLocalModel(
	model?: string,
	workspace?: string,
): Promise<LocalModelsSnapshot | null> {
	return post('/v1/local-models/start', {model, workspace}, workspace);
}

/** 停止服务（后端会连带收掉 pid 树）。 */
export async function stopLocalModel(
	workspace?: string,
): Promise<LocalModelsSnapshot | null> {
	return post('/v1/local-models/stop', {}, workspace);
}

/** 切换模型（运行中 = 停旧起新）。 */
export async function switchLocalModel(
	model: string,
	workspace?: string,
): Promise<LocalModelsSnapshot | null> {
	return post('/v1/local-models/switch', {model, workspace}, workspace);
}

async function post(
	path: string,
	body: Record<string, unknown>,
	workspace?: string,
): Promise<LocalModelsSnapshot | null> {
	try {
		const res = await fetchWithTimeout(apiUrl(`${path}${qs(workspace)}`), {
			method: 'POST',
			headers: {'Content-Type': 'application/json', ...authHeaders()},
			body: JSON.stringify(body),
		});
		return await readSnapshot(res);
	} catch {
		return null;
	}
}

/** llama-server 日志末若干行（加载失败时的唯一现场）。 */
export async function getLocalModelLog(
	lines = 40,
): Promise<{ok: boolean; lines: string; path: string} | null> {
	try {
		const res = await fetchWithTimeout(
			apiUrl(`/v1/local-models/log?lines=${encodeURIComponent(String(lines))}`),
			{cache: 'no-store'},
		);
		if (!res.ok) return null;
		return (await res.json()) as {ok: boolean; lines: string; path: string};
	} catch {
		return null;
	}
}
