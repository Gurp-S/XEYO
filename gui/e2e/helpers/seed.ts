import type {Page} from '@playwright/test';

/**
 * 在页面脚本运行前注入测试用 localStorage：
 * - `XEYO_ENABLE_LOCAL_TEST=1`：打开前端 localTestGate（DEV 构建下），
 *   让 `fake`/`local` 成为可用的空 Key provider。
 * - `xeyo-settings`：provider=fake / model=fake，无 API Key。
 */
export async function seedFakeTestSettings(page: Page): Promise<void> {
	await page.addInitScript(() => {
		window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		window.localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'fake',
				model: 'fake',
				apiKey: '',
				baseUrl: '',
				thinking: 'disabled',
				reasoningEffort: '',
				permissionMode: 'risk',
				outputCompact: false,
				codeCompact: false,
				hydrated: false,
			}),
		);
	});
}

export type LocalSeedOptions = {
	/** mock_llm 的 /v1 基地址，如 http://127.0.0.1:8490/v1 */
	baseUrl: string;
	/** 审批模式；设为 'always' 可让任何工具触发审批面板（T3）。 */
	permissionMode?: 'always' | 'risk' | 'never';
};

/**
 * Playwright 全栈（provider=local → mock_llm）种子。
 *
 * provider=local 正好命中 Composer 前端空 Key 放行分支（`provider !== 'local'`
 * 为假 → 空 Key 放行、发送可用），无需改任何生产代码；后端走 XEYO_ALLOW_LOCAL_MODEL
 * 把请求转发到 baseUrl 指向的 mock_llm。
 */
export async function seedLocalTest(
	page: Page,
	opts: LocalSeedOptions,
): Promise<void> {
	await page.addInitScript(
		(o) => {
			window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
			window.localStorage.setItem(
				'xeyo-settings',
				JSON.stringify({
					provider: 'local',
					model: 'local',
					apiKey: '',
					baseUrl: o.baseUrl,
					thinking: 'disabled',
					reasoningEffort: '',
					permissionMode: o.permissionMode ?? 'always',
					outputCompact: false,
					codeCompact: false,
					hydrated: false,
				}),
			);
		},
		opts,
	);
}
