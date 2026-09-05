import {defineConfig, devices} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// package.json 为 "type": "module"（ESM），ES 作用域没有 __dirname，需手工派生。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '..');

// B 层全栈 · 回溯专项：真 Chromium + 真后端（local → mock_llm）+ Vite dev。
//
// 与 playwright.fullstack.config.ts 的区别：mock 场景换成 Write 工具
// （e2e_responses/t_rewind_write.json），驱动「文件检查点冻结 → Restore
// 恢复工作区 → Undo 写回」的完整文件级回溯链路。端口独立，可与 fullstack
// 配置并存复跑（webServer reuseExistingServer 仅本地默认放行）。

const MOCK_PORT = Number(process.env.XEYO_E2E_MOCK_PORT || '8491');
const BACKEND_PORT = Number(process.env.XEYO_E2E_BACKEND_PORT || '8187');
const VITE_PORT = Number(process.env.XEYO_E2E_VITE_PORT || '5177');
const MOCK_RESPONSES =
	process.env.XEYO_E2E_RESPONSES ||
	path.join(REPO, 'scripts', 'smoke_p0p1', 'e2e_responses', 't_rewind_write.json');

const ISOLATE_DIR = path.join(os.tmpdir(), `xeyo-fullstack-rewind-${process.pid}`);
const PORT_FILE = path.join(ISOLATE_DIR, 'backend_port.json');
const WS_DIR = path.join(ISOLATE_DIR, 'ws');
// 诊断：mock_llm 收到的每个主轮请求（角色序列 + 命中分支）。固定路径便于复跑后对照。
const REQUESTS_LOG = path.join(os.tmpdir(), 'xeyo-fullstack-rewind-requests.jsonl');
fs.rmSync(REQUESTS_LOG, {force: true});

const backendEnv = {
	XEYO_HTTP_PORT: String(BACKEND_PORT),
	XEYO_PORT_FILE: PORT_FILE,
	XEYO_ALLOW_LOCAL_MODEL: '1',
	XEYO_REWIND_ENABLED: '1',
	XEYO_C2_GATE: '0',
	XEYO_TOOL_AGING: '0',
	XEYO_SESSIONS_DIR: path.join(ISOLATE_DIR, 'sessions'),
	XEYO_USAGE_DIR: path.join(ISOLATE_DIR, 'usage'),
	XEYO_HOME: ISOLATE_DIR,
	XEYO_SPILL_DIR: path.join(ISOLATE_DIR, 'spill'),
	XEYO_UI_CWD: WS_DIR,
};

const mockEnv = {
	PYTHONIOENCODING: 'utf-8',
};

const frontendEnv = {
	XEYO_PORT_FILE: PORT_FILE,
};

export default defineConfig({
	testDir: './e2e',
	testMatch: '**/rewind-fullstack.spec.ts',
	fullyParallel: false,
	workers: 1,
	forbidOnly: !!process.env.CI,
	retries: 0,
	reporter: process.env.CI ? 'github' : 'list',
	timeout: 90_000,
	use: {
		baseURL: `http://127.0.0.1:${VITE_PORT}`,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
	},
	projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
	webServer: [
		{
			command: `py -3.11 scripts/smoke_p0p1/mock_runner.py --port ${MOCK_PORT} --responses "${MOCK_RESPONSES}" --requests "${REQUESTS_LOG}"`,
			cwd: REPO,
			env: mockEnv,
			url: `http://127.0.0.1:${MOCK_PORT}/health`,
			reuseExistingServer: process.env.XEYO_E2E_REUSE === '1',
			timeout: 120_000,
		},
		{
			command: 'py -3.11 -m server',
			cwd: path.resolve(__dirname, '..', 'python'),
			env: backendEnv,
			url: `http://127.0.0.1:${BACKEND_PORT}/health`,
			reuseExistingServer: process.env.XEYO_E2E_REUSE === '1',
			timeout: 120_000,
		},
		{
			command: `npx vite --port ${VITE_PORT} --strictPort --host 127.0.0.1`,
			cwd: __dirname,
			env: frontendEnv,
			url: `http://127.0.0.1:${VITE_PORT}`,
			reuseExistingServer: process.env.XEYO_E2E_REUSE === '1',
			timeout: 120_000,
		},
	],
});

export {MOCK_PORT, BACKEND_PORT, VITE_PORT};
