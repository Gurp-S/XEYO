/**
 * 命令行斜杠交互 E2E：真 Chromium + 真 FastAPI（provider=fake）。
 *
 * jsdom 量不到的三件事在这里钉住：
 *  1. 弹层开着时 Enter 属于弹层（首行恒高亮，DSH `popup.ts` 的 `active: 0` 口径）；
 *     只打了**必填参数**的命令名（`/goal`）时，第二枪 Enter 也不执行、不发送，
 *     草稿留在框里，灰字提示 `[data-ghost]` 继续提示该填什么；
 *  2. 带参命令确实执行（正对照，防守卫把 Enter 全吞掉）；
 *  3. **可选参数**的命令（`/usage`）回填后再按一次 Enter 照旧执行——守卫不能过拦。
 *
 * 断言走网络请求与真实 DOM（`[data-goal-bar]`、`[data-ghost]`）：用户看到的就是
 * 这个界面本身，store 投影不算证据。
 */
import {test, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';

const COMPOSER = '消息输入';
const GHOST = '[data-ghost]';
const GOAL_BAR = '[data-goal-bar]';
const SHOT_DIR = path.join(os.tmpdir(), 'xeyo-e2e-slash-shots');

// vite 冷启动首测会吃掉 60s 默认预算（首屏依赖预构建）。
test.setTimeout(150_000);

const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-slash-ws-'));

/**
 * 记录页面打给后端的**提交类**请求。
 * 只算这三条：/v1/slash（命令执行）、/v1/chat（普通发送）、goal 写（PATCH）。
 * 必须排除 /v1/workspace——工作区面板自己会 POST 它，把它算进来会让
 * "什么都没发生"的断言恒红。GET（goal 3s 轮询）同样排除。
 */
function watchSubmits(page: Page): () => string[] {
	const hits: string[] = [];
	page.on('request', req => {
		const method = req.method();
		if (method !== 'POST' && method !== 'PATCH') {
			return;
		}
		const p = new URL(req.url()).pathname;
		if (p === '/v1/slash' || p === '/v1/chat/completions' || /\/goal$/.test(p)) {
			hits.push(`${method} ${p}`);
		}
	});
	return () => hits.slice();
}

async function shoot(page: Page, name: string): Promise<void> {
	fs.mkdirSync(SHOT_DIR, {recursive: true});
	await page.screenshot({path: path.join(SHOT_DIR, `${name}.png`), fullPage: false});
}

/** 会话是否仍在流式（store 里该会话的 isLoading）。 */
async function isStreaming(page: Page): Promise<boolean> {
	return page.evaluate(() => {
		const st = (
			window as unknown as {__XEYO_CHAT__?: {getState: () => Record<string, unknown>}}
		).__XEYO_CHAT__!.getState();
		const sid = (st.activeId as string) ?? '';
		const stream = (
			(st.sessionStreams ?? {}) as Record<string, Record<string, unknown>>
		)[sid];
		return Boolean(stream?.isLoading);
	});
}

/**
 * 让会话在**服务端**真实存在：发一条普通消息并等它答完。
 * 新会话的 id 只在本地，服务端要到首个 chat 请求才钉住工作区——
 * 这一步不是等 UI，而是等"会话已知"这个前提。
 */
async function openTurn(page: Page, text: string): Promise<void> {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
	await expect
		.poll(() => isStreaming(page), {timeout: 30_000})
		.toBe(true);
	await expect
		.poll(() => isStreaming(page), {timeout: 60_000})
		.toBe(false);
}

test.beforeEach(async ({page}) => {
	await seedFakeTestSettings(page);
	await bootChat(page);
	await openWorkspaceSession(page, workspaceDir);
});

test('裸 /goal：Enter 先选中回填命令名，补参数前第二枪也不会执行', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('/goal');
	await expect(page.locator(GHOST)).toHaveText('请输入目标，智能体将持续执行');

	// 第一枪：弹层首行恒高亮（DSH 口径）→ Enter 属于弹层，回填 `/goal `。
	await composer.press('Enter');
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('/goal ');

	// 第二枪：只打了命令名 → 参数守卫拦下，不发请求，灰字继续提示。
	await composer.press('Enter');
	await page.waitForTimeout(1_500);
	expect(submits()).toEqual([]);
	expect(await composer.inputValue()).toBe('/goal ');
	await expect(page.locator(GOAL_BAR)).toHaveCount(0);
	await expect(page.locator(GHOST)).toBeVisible();
	await shoot(page, 'bare-goal-enter');
});

test('带参 /goal 按 Enter：真的执行并挂出目标条带（正对照）', async ({page}) => {
	const submits = watchSubmits(page);
	// 前提：会话已在服务端落地（见 openTurn 注释）。
	await openTurn(page, '先开场');
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('/goal 重构登录模块并跑通测试');
	await composer.press('Enter');

	await expect(page.locator(GOAL_BAR)).toBeVisible({timeout: 15_000});
	expect(submits().some(hit => hit === 'POST /v1/slash')).toBe(true);
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('');
	await shoot(page, 'goal-with-arg');
});

test('裸 /usage（参数可选）第二枪 Enter 照旧执行，守卫不过拦', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('/usage');
	// 第一枪归弹层（回填 `/usage `），第二枪才落到发送链路——与 /goal 同一节奏。
	await composer.press('Enter');
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('/usage ');
	await composer.press('Enter');

	await expect
		.poll(() => submits().includes('POST /v1/slash'), {timeout: 15_000})
		.toBe(true);
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('');
});

test('斜杠弹层高亮时 Enter 先“选中”：回填命令名而不是发送', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.pressSequentially('/goal');
	await composer.press('ArrowDown');
	await composer.press('Enter');
	await page.waitForTimeout(1_500);

	// 选中行 = 把命令回填成 `/goal `（带尾空格），Enter 没有透传成发送。
	expect(await composer.inputValue()).toBe('/goal ');
	expect(submits()).toEqual([]);
});

/**
 * 空对话（还没有任何轮次）的第一个动作就是 `/goal <文本>`：条带必须直接挂出。
 *
 * 原地登记过的缺陷（2026-10-04，已修）：POST /v1/slash 200「已创建目标」→ GUI
 * 回读 GET /v1/sessions/{sid}/goal **404 session not found** → 条带不挂出，
 * 只有一条「目标投影读不到」的错误 toast。根因在服务端读写口径不一致：写侧
 * /v1/slash 不设「会话已知」门，读侧 goals.py 的 `_require_known_session` 要
 * pool 或 transcript 证据，而全新会话（前端自造 id、首个 chat 请求还没发生）
 * 两边都不满足。修法=写侧成功后把「会话 → 工作区」登记进 pool（与首个 chat
 * 请求同一张表、同一 first-write-wins 语义），读侧的门不放松。
 */
test('新会话第一个动作就是 /goal：条带应当直接挂出', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('/goal 新会话目标');
	await composer.press('Enter');
	await expect(page.locator(GOAL_BAR)).toBeVisible({timeout: 10_000});
	// 挂出来的必须是这一条目标，而不是任何别的条带（投影内容也要对）。
	await expect(page.locator(GOAL_BAR)).toContainText('新会话目标');
});

/**
 * 空对话的条带动词面走通同一道读侧门（PATCH 与 GET 共用 `_require_known_session`）：
 * 暂停 → 恢复 → 编辑 → 清除，四步都以服务端回执为准（store 不算证据）。
 */
test('空对话 /goal 后条带动词面：暂停 → 恢复 → 编辑 → 清除', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('/goal 动词面目标');
	await composer.press('Enter');
	const bar = page.locator(GOAL_BAR);
	await expect(bar).toBeVisible({timeout: 10_000});
	await expect(bar).toContainText('进行中的目标');

	await bar.getByRole('button', {name: '暂停'}).click();
	await expect(bar).toContainText('已暂停的目标', {timeout: 10_000});

	await bar.getByRole('button', {name: '恢复'}).click();
	await expect(bar).toContainText('进行中的目标', {timeout: 10_000});

	await bar.getByRole('button', {name: '编辑目标'}).click();
	await page.getByLabel('目标内容').fill('改过的目标正文');
	await bar.getByRole('button', {name: '保存目标'}).click();
	await expect(bar).toContainText('改过的目标正文', {timeout: 10_000});

	await bar.getByRole('button', {name: '清除目标'}).click();
	await expect(bar).toHaveCount(0, {timeout: 10_000});
});
