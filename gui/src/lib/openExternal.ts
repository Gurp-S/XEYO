import {isTauri} from '@/lib/tauri';

/**
 * 用系统默认程序打开 URL（http/https 等）。
 *
 * - Tauri 桌面壳：``plugin-shell`` 的 ``open``。注意其 capabilities scope 只放行
 *   ``mailto:`` / ``tel:`` / ``http(s)://`` —— ``file://`` 会报
 *   "Scoped command argument … failed regex validation"，本地文件请走后端的 http 入口。
 * - 浏览器 dev：``window.open``；被拦截时抛错，调用方据此给出「路径可复制」的兜底提示。
 *
 * 与 BrowserPreviewPanel 里的同款实现保持一致（那里只开 http(s) 网页，故未合并）。
 */
export async function openExternalUrl(url: string): Promise<void> {
	const target = url.trim();
	if (!target) {
		throw new Error('空链接');
	}
	if (isTauri()) {
		const {open} = await import('@tauri-apps/plugin-shell');
		await open(target);
		return;
	}
	const win = window.open(target, '_blank', 'noopener,noreferrer');
	if (!win) {
		throw new Error('浏览器拦截了打开窗口');
	}
}
