// 测试 transport 门禁。内置本地模型产品功能已移除；local / fake 仅供
// DEV 构建且显式设置 XEYO_ENABLE_LOCAL_TEST=1 的全栈测试使用。

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

/** HTTP mock transport，仅在显式开启的开发测试中可用。 */
export function isLocalProvider(provider: string | undefined | null): boolean {
	return provider === 'local' && isLocalTestEnabled();
}

/** 受 dev 门禁管理的测试 provider（仅 'fake'）。 */
export function isTestProvider(provider: string | undefined | null): boolean {
	return !!provider && provider === 'fake' && isLocalTestEnabled();
}

/**
 * 空 API Key 放行条件。
 *
 * 仅显式开启的开发测试 transport 放行。
 */
export function allowsEmptyApiKey(provider: string | undefined | null): boolean {
	return isLocalProvider(provider) || isTestProvider(provider);
}

/**
 * 已知 provider 全集（`settingsStore.isProviderId` 的判定实体）。
 *
 * 放在这里而不是 settingsStore，是为了让判定可以在不加载 store（zustand +
 * IndexedDB）的前提下被测试与复用——测试替身也直接转发本函数，不再是各写一份
 * "看起来一样"的实现。
 */
export function isKnownProvider(v: unknown): boolean {
	return (
		v === 'deepseek' ||
		v === 'openai' ||
		v === 'anthropic' ||
		isLocalProvider(v as string) ||
		isTestProvider(v as string)
	);
}
