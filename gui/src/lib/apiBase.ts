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
