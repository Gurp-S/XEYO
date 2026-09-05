// T25c：LOCAL-TEST 统一收口（原散落在 12 处的 LOCAL-TEST 条件）。
//
// 「本地模型（测试）」provider 只在 dev 构建 + 显式开启（localStorage
// XEYO_ENABLE_LOCAL_TEST=1）时可用；生产构建（vite build / tauri build）恒关闭。
// 关闭时：provider 选项不渲染、空 Key 校验恢复、存量 local profile 归一化为
// deepseek（经 settingsStore.isProviderId）。

export function isLocalTestEnabled(): boolean {
	if (!import.meta.env.DEV) {
		return false;
	}
	try {
		return window.localStorage.getItem('XEYO_ENABLE_LOCAL_TEST') === '1';
	} catch {
		return false;
	}
}

/** provider 是否为受 gate 管理的本地测试 provider（'local'）。 */
export function isLocalProvider(provider: string | undefined | null): boolean {
	return !!provider && provider === 'local' && isLocalTestEnabled();
}

/**
 * 受 gate 管理的「本地/测试」provider 全集：'local' 与 'fake'。
 * 两者均允许空 API Key；fake 供 Playwright 全栈（真浏览器+真后端）测试用。
 */
export function isTestProvider(provider: string | undefined | null): boolean {
	return (
		!!provider &&
		(provider === 'local' || provider === 'fake') &&
		isLocalTestEnabled()
	);
}

/** 空 API Key 放行条件：仅本地/测试 provider 允许无 Key。 */
export function allowsEmptyApiKey(provider: string | undefined | null): boolean {
	return isTestProvider(provider);
}
