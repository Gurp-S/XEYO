/**
 * playwright.ui-audit.config.ts — 解法一 GUI 几何错位扫描专用配置。
 *
 * 与默认 playwright.config.ts 的区别：
 * - **只起 vite dev，不起后端**：扫描走 /bench/chat?rounds=N（离线合成转录，纯页面内
 *   自驱动，不访问模型服务/远程资源），无需 FastAPI。
 * - 路由 `/bench/chat` 只有 `import.meta.env.DEV` 才注册，因此必须 `vite dev`，不能用
 *   `vite build`+`preview`。
 * - 独立端口 5174，避免与默认 e2e（5173）/ 本地 dev 抢端口。
 *
 * 用法：`npm run test:e2e:ui-audit`（在 gui/ 下）。
 * 产物：`gui/ui-audit-report/`（summary.md + report-*.json + shot-*.png）。
 */
import {defineConfig, devices} from '@playwright/test';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const VITE_PORT = Number(process.env.XEYO_UI_AUDIT_PORT || '5174');

const frontendEnv = {
	// 让 vite backendFollowProxy 找到后端端口文件；审计面不依赖后端，
	// 但 env 缺失时 vite resolveBackendPort 会回落到 8000 并尝试连接，无碍扫描。
	XEYO_PORT_FILE: '',
};

export default defineConfig({
	testDir: './e2e',
	testMatch: '**/ui-audit.spec.ts',
	fullyParallel: false,
	workers: 1,
	forbidOnly: !!process.env.CI,
	retries: 0,
	reporter: 'list',
	timeout: 180_000,
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
