/**
 * playwright.ui-audit-full.config.ts — GUI 全量视觉审计配置。
 *
 * 与 playwright.ui-audit.config.ts 同构：只起 vite dev（不起后端），独立端口 5175。
 * 只匹配 ui-audit-full.spec.ts。
 * 用法：`npm run test:e2e:ui-audit-full`（在 gui/ 下）。
 */
import {defineConfig, devices} from '@playwright/test';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const VITE_PORT = Number(process.env.XEYO_UI_AUDIT_FULL_PORT || '5175');

const frontendEnv = {
	XEYO_PORT_FILE: '',
};

export default defineConfig({
	testDir: './e2e',
	outputDir: './test-results-regression',
	testMatch: '**/ui-audit-*.spec.ts',
	fullyParallel: false,
	workers: 1,
	retries: 0,
	reporter: 'list',
	timeout: 480_000,
	use: {
		baseURL: `http://127.0.0.1:${VITE_PORT}`,
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
	},
	projects: [
		{
			name: 'chromium',
			use: {...devices['Desktop Chrome']},
		},
	],
	webServer: {
		command: `npx vite --port ${VITE_PORT} --strictPort --host 127.0.0.1`,
		cwd: __dirname,
		env: frontendEnv,
		url: `http://127.0.0.1:${VITE_PORT}`,
		reuseExistingServer: process.env.XEYO_UI_AUDIT_REUSE === '1',
		timeout: 120_000,
	},
});
