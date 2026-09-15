// 本地/测试 provider 门禁。
//
// 'local' 与 'fake' 走的是相反的路，2026-09-14 起分开管理：
//
// * **'local' = 正式功能**（本地模型服务，llama.cpp / 任何 OpenAI 兼容的环回服务）。
//   它**不再受 dev 构建门禁**——生产包同样可用，因为要不要开放由用户在本机决定
//   （设置 → 模型与账号 → 本地模型）。后端对应的授权位是
//   `settings.local_models.enabled`（见 `python/localmodels/gate.py`）。
//   本地服务通常不校验 Key，所以空 Key 合法。
// * **'fake' = 测试专用**（Playwright 全栈测试的确定性假模型）。仍然只在
//   dev 构建 + 显式开启（localStorage `XEYO_ENABLE_LOCAL_TEST=1`）时可用，
//   生产构建恒关闭。

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

/** provider 是否为本地模型服务（'local'）。正式功能，不受 dev 门禁限制。 */
export function isLocalProvider(provider: string | undefined | null): boolean {
	return !!provider && provider === 'local';
}

/** 受 dev 门禁管理的测试 provider（仅 'fake'）。 */
export function isTestProvider(provider: string | undefined | null): boolean {
	return !!provider && provider === 'fake' && isLocalTestEnabled();
}

/**
 * 空 API Key 放行条件。
 *
 * 'local' 恒放行（本机服务不校验 Key）；'fake' 仅门禁开启时放行。
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
