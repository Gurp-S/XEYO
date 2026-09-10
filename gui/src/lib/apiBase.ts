import {isTauri} from '@/lib/tauri';

// Tauri 运行时端口覆盖：后端可能迁移端口（守护 respawn / 8000 被占）。
// apiBase 保持同步，靠 refreshRuntimeBackendPort 惰性刷新缓存。
let _runtimePort: string | null = null;
export function setRuntimeBackendPort(port: string | null) {
	_runtimePort = port && /^\d+$/.test(port) ? port : null;
}

/** 后端 origin — Tauri 无 Vite 代理，因此使用绝对 URL。端口跟随后端实际监听端口，默认 8000。 */
export function apiBase(): string {
	if (isTauri()) {
		const port = _runtimePort || import.meta.env.VITE_XEYO_HTTP_PORT || '8000';
		return `http://127.0.0.1:${port}`;
	}
	return '';
}

/** Tauri 下向壳查询后端实时端口（读端口文件），成功则刷新缓存。 */
export async function refreshRuntimeBackendPort(): Promise<string> {
	if (!isTauri()) {
		return apiBase();
	}
	try {
		const {invoke} = await import('@tauri-apps/api/core');
		const port = await invoke<number | string>('get_backend_port');
		const s = String(port ?? '').trim();
		setRuntimeBackendPort(s);
		return apiBase();
	} catch {
		// 壳不可达：维持现有缓存
		return apiBase();
	}
}

export function apiUrl(path: string): string {
	const p = path.startsWith('/') ? path : `/${path}`;
	return `${apiBase()}${p}`;
}

/** 当前后端端口字面量，用于错误文案（避免各处再读一次 env 而读不到运行时迁移值）。 */
export function backendPortLabel(): string {
	return _runtimePort || import.meta.env.VITE_XEYO_HTTP_PORT || '8000';
}

/**
 * 向壳查询最近一次后端启动失败的原因。
 *
 * 历史事故：内嵌 Python 是薄壳 venv（缺 python3xx.dll / 标准库），装到没装
 * Python 的机器上 spawn 必然失败，但壳只把错误写进 stderr，界面统一显示
 * "无法连接后端"，用户只能猜是端口或网络问题。这里把壳里的真实原因取出来，
 * 让错误横幅直接说明"内嵌 Python 不可用"。
 */
export async function fetchBackendSpawnError(): Promise<string | null> {
	if (!isTauri()) {
		return null;
	}
	try {
		const {invoke} = await import('@tauri-apps/api/core');
		const msg = await invoke<string | null>('get_backend_error');
		const s = typeof msg === 'string' ? msg.trim() : '';
		return s || null;
	} catch {
		return null;
	}
}
