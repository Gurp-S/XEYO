import {defineConfig, devices} from '@playwright/test';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// package.json 为 "type": "module"（ESM），ES 作用域没有 __dirname，需手工派生。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '..');

// B 层全栈：真 Chromium + 真后端（provider=local → mock_llm）+ Vite dev。
//
// 与 main-path 的区别：后端不是 provider=fake（FakeModelClient），而是
// XEYO_ALLOW_LOCAL_MODEL=1 + 把 GUI 的 provider 设为 local，后端把 /v1/chat
// 转发到 mock_llm（复用 scripts/smoke_p0p1/mock_llm.py，由 mock_runner 固定端口拉起）。
// 这样能驱动真实工具执行（Bash/Grep/Write）→ 前端工具卡 duration；permission_mode=always
// → 审批面板；XEYO_C2_GATE → compact 按钮显隐。不改任何生产代码。

// 端口通过 env 覆盖，便于按不同 mock 场景分别跑。
const MOCK_PORT = Number(process.env.XEYO_E2E_MOCK_PORT || '8490');
const BACKEND_PORT = Number(process.env.XEYO_E2E_BACKEND_PORT || '8179');
const VITE_PORT = Number(process.env.XEYO_E2E_VITE_PORT || '5175');
const MOCK_RESPONSES =
	process.env.XEYO_E2E_RESPONSES ||
	path.join(REPO, 'scripts', 'smoke_p0p1', 'e2e_responses', 't3_bash_ask.json');

const ISOLATE_DIR = path.join(os.tmpdir(), `xeyo-fullstack-${process.pid}`);
const PORT_FILE = path.join(ISOLATE_DIR, 'backend_port.json');
const WS_DIR = path.join(ISOLATE_DIR, 'ws');

const backendEnv = {
	XEYO_HTTP_PORT: String(BACKEND_PORT),
	XEYO_PORT_FILE: PORT_FILE,
	// local provider（指向 mock_llm）需显式开启。
	XEYO_ALLOW_LOCAL_MODEL: '1',
	// 让 compact 按钮按 gate 显隐：T38 需要 gate 开。
	XEYO_C2_GATE: '1',
	XEYO_TOOL_AGING: '0',
	XEYO_REWIND_ENABLED: '1',
	XEYO_SESSIONS_DIR: path.join(ISOLATE_DIR, 'sessions'),
	XEYO_USAGE_DIR: path.join(ISOLATE_DIR, 'usage'),
	XEYO_HOME: ISOLATE_DIR,
	XEYO_SPILL_DIR: path.join(ISOLATE_DIR, 'spill'),
	XEYO_UI_CWD: WS_DIR,
	// T29：允许后端在收到含哨兵 `__XEYO_DROP_STREAM__` 的消息时断流（测试钩子，
	// 仅此 e2e 后端设置）。生产路径不设此 env。
	XEYO_TEST_STREAM_DROP: '1',
};

const mockEnv = {
	// mock_runner 不读这些；仅透传即可。
	PYTHONIOENCODING: 'utf-8',
};

const frontendEnv = {
	// 让 vite backendFollowProxy 读到后端实际监听端口。
	XEYO_PORT_FILE: PORT_FILE,
};

export default defineConfig({
	testDir: './e2e',
	testMatch: '**/fullstack.spec.ts',
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
			command: `py -3.11 scripts/smoke_p0p1/mock_runner.py --port ${MOCK_PORT} --responses "${MOCK_RESPONSES}"`,
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
