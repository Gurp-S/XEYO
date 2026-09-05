import {defineConfig, devices} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// Debug：复现「退出历史气泡编辑态闪一下」。独立端口（后端 8190 / vite 5190），
// provider=fake（XEYO_ALLOW_FAKE_MODEL=1），不干扰并行会话的 5173/8177。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '..', '..');

const BACKEND_PORT = Number(process.env.XEYO_E2E_DEBUG_BACKEND_PORT || '8190');
const VITE_PORT = Number(process.env.XEYO_E2E_DEBUG_VITE_PORT || '5190');

const ISOLATE_DIR = path.join(os.tmpdir(), `xeyo-debug-editflick-${process.pid}`);
const PORT_FILE = path.join(ISOLATE_DIR, 'backend_port.json');
const WS_DIR = path.join(ISOLATE_DIR, 'ws');
const RESULT_DIR = path.join(ISOLATE_DIR, 'results');
fs.mkdirSync(ISOLATE_DIR, {recursive: true});
fs.mkdirSync(WS_DIR, {recursive: true});
fs.mkdirSync(RESULT_DIR, {recursive: true});

const backendEnv = {
	XEYO_HTTP_PORT: String(BACKEND_PORT),
	XEYO_PORT_FILE: PORT_FILE,
	XEYO_ALLOW_FAKE_MODEL: '1',
	XEYO_GOAL_AUTO_CREATE: '0',
	XEYO_C2_GATE: '0',
	XEYO_TOOL_AGING: '0',
	XEYO_SESSIONS_DIR: path.join(ISOLATE_DIR, 'sessions'),
	XEYO_USAGE_DIR: path.join(ISOLATE_DIR, 'usage'),
	XEYO_HOME: ISOLATE_DIR,
	XEYO_UI_CWD: WS_DIR,
};

export default defineConfig({
	testDir: __dirname,
	testMatch: '**/editflick.spec.ts',
	outputDir: RESULT_DIR,
	fullyParallel: false,
	workers: 1,
	retries: 0,
	reporter: 'list',
	timeout: 90_000,
	use: {
		baseURL: `http://127.0.0.1:${VITE_PORT}`,
		trace: 'on-first-retry',
		screenshot: 'on',
		video: 'on',
		viewport: {width: 1280, height: 800},
	},
	projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
	webServer: [
		{
			command: 'py -3.11 -m server',
			cwd: path.join(REPO, 'python'),
			env: backendEnv,
			url: `http://127.0.0.1:${BACKEND_PORT}/health`,
			timeout: 120_000,
		},
		{
			command: `npx vite --port ${VITE_PORT} --strictPort --host 127.0.0.1`,
			cwd: path.resolve(REPO, 'gui'),
			env: {XEYO_PORT_FILE: PORT_FILE},
			url: `http://127.0.0.1:${VITE_PORT}`,
			timeout: 120_000,
		},
	],
});
