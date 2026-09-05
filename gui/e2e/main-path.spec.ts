/**
 * 主路径部件集成 → Playwright 全栈（真浏览器 + 真后端）样板。
 *
 * 覆盖 jsdom `src/paths/mainPaths.workflow.test.tsx` 的 send / stop 主路径：
 * 真实 Chromium + 真实 FastAPI，后端 provider=fake（FakeModelClient，受
 * XEYO_ALLOW_FAKE_MODEL=1 门禁），无需真实 API Key、离线确定。
 *
 * 说明：
 * - 依赖 `vite dev`（DEV=true 才放行前端 localTestGate 的 fake provider）。
 * - `echo:` 工具流程为工具链样板；若 EchoTool 在 risk 权限下 ASK，首个
 *   运行会弹出权限确认——届时按「权限」场景走（Phase 2）。
 * - 权限 / reattach / 回溯 v3 需额外确定性钩子（见 README），此处先落地
 *   send / stop 作为可复用的骨架。
 */
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';

const COMPOSER = '描述任务… Enter 发送';
const SEND = '发送';
const STOP = '停止生成';

// 每次跑独立、确定性的工作区（fake 层也必须显式绑工作区 + 建会话，否则被
// 「请先打开一个项目文件夹」守卫拦截 / 发送被接受但气泡消失）。
const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-mainpath-ws-'));

test.beforeEach(async ({page}) => {
	await seedFakeTestSettings(page);
	// 启动诊断：若命中 GuiErrorBoundary 崩溃屏，抛出 boundary/控制台的真实错误。
	await bootChat(page);
	// 打开真实文件夹作为工作区并建会话（确定性会话/工作区骨架）。
	await openWorkspaceSession(page, workspaceDir);
});

test('send: 用户气泡上屏 → 助理流式落定 ok: <text>', async ({page}) => {
	const composer = page.getByPlaceholder(COMPOSER);
	await composer.click();
	await composer.fill('hello');
	await composer.press('Enter');

	// 用户气泡（exact 匹配，避免命中助理 "ok: hello" 的子串）。
	await expect(page.getByText('hello', {exact: true})).toBeVisible();
	// 助理最终文本（FakeModelClient 规则 3：`ok: <user>`，逐字符流式）。
	await expect(page.getByText(/ok: hello/)).toBeVisible({timeout: 20_000});
	// 回到非流式：发送按钮复原、无停止按钮。
	await expect(page.getByRole('button', {name: STOP})).toHaveCount(0);
	await expect(page.getByRole('button', {name: SEND}).first()).toBeVisible();
});

test('stop: 停止按钮中断流 → UI 回非加载态', async ({page}) => {
	const longText = 'stop me ' + 'x'.repeat(200);
	const composer = page.getByPlaceholder(COMPOSER);
	await composer.click();
	await composer.fill(longText);
	await composer.press('Enter');

	// 流式期间出现「停止生成」。
	await expect(page.getByRole('button', {name: STOP}).first()).toBeVisible();
	// 点停止。
	await page.getByRole('button', {name: STOP}).first().click();
	// 停止后：停止按钮消失、发送按钮复原。
	await expect(page.getByRole('button', {name: STOP})).toHaveCount(0);
	await expect(page.getByRole('button', {name: SEND}).first()).toBeVisible();
});

test.skip('tool echo: echo 工具链 → echoed: <text>（Phase 2 钩子占位）', async ({page}) => {
	// 依赖 EchoTool 非 ASK 门禁；若现 ASK 弹窗，按「权限」场景改断言。
	const composer = page.getByPlaceholder(COMPOSER);
	await composer.click();
	await composer.fill('echo: world');
	await composer.press('Enter');
	await expect(page.getByText(/echoed: world/)).toBeVisible({timeout: 20_000});
});
