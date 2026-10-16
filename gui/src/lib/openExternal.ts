import {isTauri} from '@/lib/tauri';

/**
 * 用系统默认程序打开 URL（http/https 等）。
 *
 * - Tauri 桌面壳：``plugin-shell`` 的 ``open``。注意其 capabilities scope 只放行
 *   ``mailto:`` / ``tel:`` / ``http(s)://`` —— ``file://`` 会报
 *   "Scoped command argument … failed regex validation"，本地文件请走后端的 http 入口。
 * - 浏览器 dev：``window.open``，不以返回的 WindowProxy 推断打开结果。
 *
 * BrowserPreviewPanel 与附件、文件链接共用此入口。
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
	window.open(target, '_blank', 'noopener,noreferrer');
}
