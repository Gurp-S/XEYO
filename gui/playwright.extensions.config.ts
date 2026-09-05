import {defineConfig, devices} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// 扩展中心(插件 / MCP / Skill)GUI 冒烟:真后端(隔离 XEYO_HOME)+ Vite dev。
// 不拉 mock_llm——扩展中心不依赖 chat provider。
// 用法:npx playwright test -c playwright.extensions.config.ts

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '..');

const BACKEND_PORT = Number(process.env.XEYO_E2E_BACKEND_PORT || '8181');
const VITE_PORT = Number(process.env.XEYO_E2E_VITE_PORT || '5177');

const ISOLATE_DIR = path.join(os.tmpdir(), `xeyo-ext-smoke-${process.pid}`);
const PORT_FILE = path.join(ISOLATE_DIR, 'backend_port.json');
const WS_DIR = path.join(ISOLATE_DIR, 'ws');

// 预置 home 级扩展配置:显式停用若干技能,让「技能」tab 有真实行可渲染
// (显式停用条目会以「配置」来源出现在列表,见 PluginsPanel SkillRow)。
// 注意:XEYO_HOME 覆盖时后端把它直接当 home root —— settings 落在
// $XEYO_HOME/settings.json(不带 .xeyo 段),见 memory/instruction.py::xeyo_home。
try {
	fs.mkdirSync(ISOLATE_DIR, {recursive: true});
	fs.writeFileSync(
		path.join(ISOLATE_DIR, 'settings.json'),
		JSON.stringify({
			enabled_extensions: false,
			skills: {
				'pdf-kit': {enabled: false},
				'doc-tools': {enabled: false},
				'web-scraper': {enabled: false},
			},
		}),
		'utf-8',
	);
} catch {
	// 预置失败不阻塞冒烟(技能 tab 退化为空态分支)
}

const backendEnv = {
	XEYO_HTTP_PORT: String(BACKEND_PORT),
	XEYO_PORT_FILE: PORT_FILE,
	XEYO_TOOL_AGING: '0',
	XEYO_SESSIONS_DIR: path.join(ISOLATE_DIR, 'sessions'),
	XEYO_USAGE_DIR: path.join(ISOLATE_DIR, 'usage'),
	XEYO_HOME: ISOLATE_DIR,
	XEYO_SPILL_DIR: path.join(ISOLATE_DIR, 'spill'),
	XEYO_UI_CWD: WS_DIR,
};

export default defineConfig({
	testDir: './e2e',
	testMatch: '**/extensions.spec.ts',
	fullyParallel: false,
	workers: 1,
	retries: 0,
	reporter: 'list',
	timeout: 60_000,
	use: {
		baseURL: `http://127.0.0.1:${VITE_PORT}`,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
	},
	projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
	webServer: [
		{
			command: 'py -3.11 -m server',
			cwd: path.resolve(__dirname, '..', 'python'),
			env: backendEnv,
			url: `http://127.0.0.1:${BACKEND_PORT}/health`,
			timeout: 120_000,
		},
		{
			command: `npx vite --port ${VITE_PORT} --strictPort --host 127.0.0.1`,
			cwd: __dirname,
			env: {XEYO_PORT_FILE: PORT_FILE},
			url: `http://127.0.0.1:${VITE_PORT}`,
			timeout: 120_000,
		},
	],
});
