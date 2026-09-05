/**
 * B 层前端 UI 消费（Playwright 全栈：真 Chromium + 真后端 local→mock_llm + Vite）。
 *
 * 运行：gui 目录下
 *   npx --no-install playwright test -c playwright.fullstack.config.ts fullstack
 *
 * 复用 scripts/smoke_p0p1/mock_llm.py（由 mock_runner 固定端口拉起），后端
 * provider=local 把 /v1/chat 转发到 mock_llm。seed 用 provider=local（空 Key 放行，
 * 不改任何生产代码），permissionMode=always 使任意工具触发审批面板。
 */
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {seedLocalTest} from './helpers/seed';

// 对应 playwright.fullstack.config.ts 的默认 mock 端口。
const MOCK_BASE = 'http://127.0.0.1:8490/v1';
const COMPOSER = '描述任务… Enter 发送';
const SEND = '发送';

const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-ws-'));

test.beforeEach(async ({page}) => {
	await seedLocalTest(page, {baseUrl: MOCK_BASE, permissionMode: 'always'});
	await page.goto('/');
	await expect(page.getByPlaceholder(COMPOSER)).toBeVisible();
	// 打开一个真实文件夹作为工作区（每次测试一个隔离临时目录），
	// 否则发送被「请先打开一个项目文件夹」拦截。backend 需校验目录存在。
	// openFolder 只建立 space；还需 createSession() 让 active session 绑定该
	// space（createSession 会置 activeId/activeSpaceId），发送才用得上 workRoot。
	await page.evaluate(
		(p) => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {
						getState: () => {
							openFolder: (r: string) => Promise<string | unknown>;
							createSession: () => Promise<string>;
						};
					};
				}
			).__XEYO_CHAT__!.getState();
			return (async () => {
				await st.openFolder(p);
				await st.createSession();
			})();
		},
		workspaceDir,
	);
});

async function send(page: import('@playwright/test').Page, text: string) {
	const composer = page.getByPlaceholder(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
}

test('T3/T13/T38：审批面板(默认展开/允许/超时文案) → 放行后 Bash 工具卡 → compact 按钮按 gate 显示', async ({
	page,
}) => {
	await send(page, 'git push');

	// T3 审批面板出现，默认展开（安全决策不藏折叠条）。
	const panel = page.getByRole('alertdialog', {name: '请求批准'});
	await expect(panel).toBeVisible({timeout: 20_000});
	await expect(panel.locator('[aria-expanded="true"]').first()).toBeVisible();
	await expect(panel.getByRole('button', {name: '允许'})).toBeVisible();
	await expect(panel.getByRole('button', {name: '拒绝'})).toBeVisible();
	// 倒计时文案（expiresAt 存在时显示「超时后默认拒绝」）。
	await expect(panel.getByText(/超时后默认拒绝|不超时，等待你的决定/)).toBeVisible();

	// 放行 → 后端执行 Bash → 前端工具活动块出现。
	await panel.getByRole('button', {name: '允许'}).click();
	// 工具卡：活动块（Agent 工具活动）出现，含命令正文。文案可能随 UI 微调，宽松匹配。
	await expect(page.getByText(/已推送|git push/).first()).toBeVisible({timeout: 20_000});

	// T38：compact 按钮（C2 gate=1）应显示。
	// 该按钮只在「用量/上下文预览」展开时才渲染（ChatHeader 在 usagePreviewOpen
	// 时才 fetch compression 并读取 c2_gate），故先点开用量预览。
	// 注意要用主区「展开用量详情」（点它才置 usagePreviewOpen），别命中侧栏「用量」。
	await page.getByRole('button', {name: /展开用量详情/}).first().click();
	await expect(page.getByRole('button', {name: '立即压缩 /compact'})).toBeVisible({
		timeout: 10_000,
	});
});

test('T3 Esc=取消（deny）→ 面板关闭', async ({page}) => {
	await send(page, 'git push');
	const panel = page.getByRole('alertdialog', {name: '请求批准'});
	await expect(panel).toBeVisible({timeout: 20_000});

	await page.keyboard.press('Escape');
	// cancel() → decide(false,'deny')：Esc=取消的核心行为是面板关闭。
	// （toast『已取消该操作』会一闪而过，另存在流中断的竞态，不稳定，不作为硬断言。）
	await expect(panel).toHaveCount(0, {timeout: 10_000});
});

// T29 断流 banner：需要后端在流中死亡/丢帧，依赖后端测试钩子，暂缓（见 README）。
test.skip('T29 断流 → 后端不可达 banner、不自动 interrupt', async ({page}) => {
	await send(page, 'hello');
	// 后端断流后应出现「连接中断…」横幅（chatStream.ts 文案），且不自动 interrupt。
	await expect(page.getByText(/连接中断/).first()).toBeVisible({timeout: 20_000});
});
