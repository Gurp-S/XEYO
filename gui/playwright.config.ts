import {defineConfig, devices} from '@playwright/test';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// package.json 为 "type": "module"（ESM），ES 作用域没有 __dirname，需手工派生。
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Playwright 全栈测试（真浏览器 + 真后端）。
 *
 * 目标：把 jsdom「部件集成」（mainPaths.workflow）的 send / stop 主路径
 * 升级为真实 Chromium + 真实 FastAPI 后端的端到端样板；保持离线、确定性，
 * 无需真实 API Key（用后端受门禁的 provider=fake，见 XEYO_ALLOW_FAKE_MODEL=1）。
 *
 * 必须跑 `vite dev`（DEV=true 才能满足前端 localTestGate 的 fake/local 放行）；
 * 不能用 `vite build`+`preview`。后端 SessionPool 单 worker → 串行、单 worker。
 */

// 后端固定端口 + 前后端共享同一端口文件（vite proxy 依端口文件动态跟随）。
const BACKEND_PORT = Number(process.env.XEYO_E2E_PORT || '8177');
const PORT_FILE = path.join(
	os.tmpdir(),
	`xeyo-e2e-port-${process.pid}.json`,
);
const ISOLATE_DIR = path.join(os.tmpdir(), `xeyo-e2e-${process.pid}`);
// 后端可写的临时工作区（SessionPool 需要 cwd；避免污染 repo / 用户现场）。
const WS_DIR = path.join(ISOLATE_DIR, 'ws');

const backendEnv = {
	XEYO_HTTP_PORT: String(BACKEND_PORT),
	XEYO_PORT_FILE: PORT_FILE,
	// 让 HTTP chat 路由放行 provider=fake（默认关，生产不可达）。
	XEYO_ALLOW_FAKE_MODEL: '1',
	// 对话型 e2e 确定性：关闭自动建 goal（否则 GoalDock 常驻、二次发送被拒）。
	XEYO_GOAL_AUTO_CREATE: '0',
	// 注：原 XEYO_PEER_PRESENCE_OFF（T_now「其他会话活动」块逃生门）已于
	// 2026-09-15 随该块收窄删除——常驻 beacon 移除后，块只在真有跨会话事件
	// 通知时注入（单会话 e2e 恒为空），不再需要逃生门。
	// 与 pytest conftest 同等隔离：单测级 env，避免本机真实数据污染。
	XEYO_C2_GATE: '0',
	XEYO_TOOL_AGING: '0',
	XEYO_SESSIONS_DIR: path.join(ISOLATE_DIR, 'sessions'),
	XEYO_USAGE_DIR: path.join(ISOLATE_DIR, 'usage'),
	XEYO_HOME: ISOLATE_DIR,
	// 后端工作区（boot_ui_cwd 回落）；无文件工具时仅作占位。
	XEYO_UI_CWD: WS_DIR,
};

const frontendEnv = {
	// 让 vite backendFollowProxy 读到后端实际监听端口。
	XEYO_PORT_FILE: PORT_FILE,
};

export default defineConfig({
	testDir: './e2e',
	// B 层全栈（local→mock_llm）用 playwright.fullstack.config.ts 单独跑，勿混入 fake 后端；
	// 回溯专项（文件检查点 Restore/Undo）用 playwright.fullstack-rewind.config.ts 单独跑；
	// 扩展中心（专用 seed + 独立端口）用 playwright.extensions.config.ts 单独跑；
	// UI 几何/交互审计（纯前端、无后端、独立 vite 端口与 480s 超时）用
	// playwright.ui-audit.config.ts / playwright.ui-audit-full.config.ts 单独跑，
	// 混入 default 会被 60s 超时与多余后端误伤（曾整批误报 5 failed）。
	testIgnore: [
		'**/fullstack.spec.ts',
		'**/rewind-fullstack.spec.ts',
		'**/extensions.spec.ts',
		'**/ui-audit.spec.ts',
		'**/ui-audit-full.spec.ts',
		'**/ui-audit-probe.spec.ts',
	],
	fullyParallel: false,
	// SessionPool 单 worker + 会话内存态：必须单工作进程串行。
	workers: 1,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? 'github' : 'list',
	timeout: 60_000,
	use: {
		baseURL: `http://127.0.0.1:5173`,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
	},
	projects: [
		{
			name: 'chromium',
			use: {...devices['Desktop Chrome']},
		},
	],
	webServer: [
		{
			command: 'py -3.11 -m server',
			cwd: path.resolve(__dirname, '..', 'python'),
			env: backendEnv,
			url: `http://127.0.0.1:${BACKEND_PORT}/health`,
			reuseExistingServer: process.env.XEYO_E2E_REUSE === '1',
			timeout: 120_000,
		},
		{
			command: 'npx vite --port 5173 --strictPort --host 127.0.0.1',
			cwd: __dirname,
			env: frontendEnv,
			url: 'http://127.0.0.1:5173',
			reuseExistingServer: process.env.XEYO_E2E_REUSE === '1',
			timeout: 120_000,
		},
	],
});
