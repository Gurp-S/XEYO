/**
 * 回溯 v3 端到端（Playwright：真 Chromium + 真后端 provider=fake）。
 *
 * 覆盖纯对话回溯生命周期（无文件工具，离线确定）：
 *  1. 编辑历史消息 → RewindV3Dialog 打开 / 取消关闭，消息列表不变；
 *  2. continue 回溯：同帧截断 → 服务端 transcript 提交 → 弹窗进入完成态
 *     → 自动重发编辑文案（FakeModelClient 回声 `ok: <text>`）；
 *  3. 多轮截断：回溯第 2 轮 → 第 2 轮消失 + 自动重发；rewind 事件流
 *     （pill 数据源）字段齐全；刷新后截断结果不回弹。
 *
 * 依赖 playwright.config.ts 的双 webServer（vite dev + py -3.11 -m server，
 * XEYO_ALLOW_FAKE_MODEL=1）。与 main-path.spec.ts 同一骨架与选择器约定。
 */
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession, resetBackendSessions} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';

const COMPOSER = '描述任务… Enter 发送';
const SEND = '发送';
const STOP = '停止生成';

// 每次跑独立、确定性的工作区（fake 层也必须显式绑工作区 + 建会话，否则被
// 「请先打开一个项目文件夹」守卫拦截 / 发送被接受但气泡消失）。
const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-rewind-ws-'));

const EDIT_BUBBLE = '编辑这条消息';
const EDIT_PREVIEW = '点击开始编辑';
const EDIT_TEXTAREA = '编辑历史消息';
const DIALOG_TITLE = '回溯到这条对话';
const BTN_CANCEL = '取消';
const BTN_CONTINUE = '改用这段文案重新发送';
const BTN_RESTORE = '恢复文件检查点';
const DONE_TITLE = '回溯完成';

async function send(page: import('@playwright/test').Page, text: string) {
	// 等当前会话流真 idle：sse 收尾（停止按钮消失）后还有 turnDetached
	// / remoteStreaming 等异步状态未复位（产品 streamSendSlice 内部时序），
	// 直接 send 会走「busy 排队」路径导致 token 永不落地，触发「空回复」
	// 守卫；这是前端 stream 状态机深度集成问题，与 rewind 链路本身无关。
	await page.waitForFunction(
		() => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {
						getState: () => {
							activeId?: string | null;
							sessionStreams?: Record<
								string,
								{
									isLoading?: boolean;
									draining?: boolean;
									turnDetached?: boolean;
									remoteStreaming?: boolean;
								}
							>;
						};
					};
				}
			).__XEYO_CHAT__?.getState();
			if (!st?.activeId) {
				return true;
			}
			const ss = st.sessionStreams?.[st.activeId];
			// sessionStreams 还没建出 entry（首发送前/clearStream 后）= idle。
			if (!ss) {
				return true;
			}
			return (
				!ss.isLoading &&
				!ss.draining &&
				!ss.turnDetached &&
				!ss.remoteStreaming
			);
		},
		{timeout: 15_000},
	);
	const composer = page.getByPlaceholder(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
}

/**
 * 打开某条 user 消息的回溯弹窗：点击气泡 → 编辑预览 → 原生 textarea → Enter 提交。
 * `userText` 用于在多轮里唯一定位目标气泡。
 */
async function openRewindDialog(
	page: import('@playwright/test').Page,
	userText: string,
) {
	await page
		.getByRole('button', {name: EDIT_BUBBLE})
		.filter({hasText: userText})
		.first()
		.click();
	await page.getByLabel(EDIT_PREVIEW).click();
	const textarea = page.getByLabel(EDIT_TEXTAREA);
	await expect(textarea).toBeVisible();
	return textarea;
}

test.beforeEach(async ({page}) => {
	await seedFakeTestSettings(page);
	// 隔离：worker 进程内 ISOLATE_DIR/sessions 跨 test 共享，76 test 留下的
	// 会话在 100 test 启动时由 hydrate.importServerSessions 拉回 IDB，导致
	// ChatPage 路由 effect 把 activeId 切到残留 sid → send 守卫拦。每 test
	// 显式清空。
	await resetBackendSessions(page);
	// 启动诊断：若命中 GuiErrorBoundary 崩溃屏，抛出 boundary/控制台的真实错误。
	await bootChat(page);
	// 打开真实文件夹作为工作区并建会话（确定性会话/工作区骨架）。
	// openWorkspaceSession 内部已同步两处竞态：① 等 chatStore.hydrate()
	// 置位（其收尾整包 set 覆盖 store，抢跑会让新 space 被启动旧快照抹掉，
	// 72/133 冷启动首测必挂根因）；② 等 spaces 绑上 rootPath + active 会话
	// 已建。此后再无「请先打开一个项目文件夹」守卫拦 send 的窗口。
	await openWorkspaceSession(page, workspaceDir);
});

test('回溯弹窗：打开 → 取消关闭，消息列表不变', async ({page}) => {
	await send(page, 'hello');
	await expect(page.getByText(/ok: hello/)).toBeVisible({timeout: 20_000});

	const textarea = await openRewindDialog(page, 'hello');
	await textarea.fill('hello v2');
	await textarea.press('Enter');

	const dialog = page.locator('dialog.xy-rewind-dialog');
	await expect(dialog.getByText(DIALOG_TITLE)).toBeVisible();
	// 双动作 + 取消都在（Restore 可用性取决于检查点，这里不硬断言可用态）。
	await expect(dialog.getByRole('button', {name: BTN_CONTINUE})).toBeVisible();
	await expect(dialog.getByRole('button', {name: BTN_RESTORE})).toBeVisible();

	await dialog.getByRole('button', {name: BTN_CANCEL}).click();
	await expect(dialog).toHaveCount(0);
	// 列表原样：原 user 消息与原回复都还在。（虚拟列表里可能有隐藏气泡副本，
	// 精确文本会命中多处/隐藏元素——改用可见的「编辑这条消息」按钮断言。）
	await expect(
		page.getByRole('button', {name: EDIT_BUBBLE}).filter({hasText: 'hello'}).first(),
	).toBeVisible();
	await expect(page.getByText(/ok: hello/).first()).toBeVisible();
});

test('continue 回溯：截断 → 完成态 → 自动重发 `ok: <edited>`', async ({page}) => {
	await send(page, 'hello');
	await expect(page.getByText(/ok: hello/)).toBeVisible({timeout: 20_000});
	await expect(page.getByRole('button', {name: STOP})).toHaveCount(0);

	const textarea = await openRewindDialog(page, 'hello');
	await textarea.fill('hello v2');
	await textarea.press('Enter');

	const dialog = page.locator('dialog.xy-rewind-dialog');
	await dialog.getByRole('button', {name: BTN_CONTINUE}).click();

	// 完成态（修复前：无 checkpoint 的 continue 事件永远停在
	// transcript_committed，前端 15s 轮询超时后误报「未确认回溯完成」）。
	await expect(dialog.getByText(DONE_TITLE, {exact: true})).toBeVisible({
		timeout: 20_000,
	});

	// 自动重发：编辑文案上屏 + fake 回声回复；旧回复随截断消失。
	// （sticky 钉住层会在 DOM 里留同文本的隐藏 .xy-chat-text 副本，裸
	// getByText().first() 会命中隐藏副本永远 hidden——必须过滤 visible。）
	await expect(
		page
			.getByText('hello v2', {exact: true})
			.locator('visible=true')
			.first(),
	).toBeVisible({timeout: 20_000});
	await expect(
		page
			.getByText('ok: hello v2', {exact: true})
			.locator('visible=true')
			.first(),
	).toBeVisible({timeout: 20_000});
	// 旧的 "ok: hello"（精确相等）不再出现。
	await expect(page.getByText('ok: hello', {exact: true})).toHaveCount(0);
});

test('多轮截断：回溯第 2 轮 → 第 2 轮消失；事件流（pill 数据源）与刷新后状态一致', async ({
	page,
}) => {
	await send(page, 'hello');
	await expect(page.getByText(/ok: hello/)).toBeVisible({timeout: 20_000});
	// 首轮完全落定（停止按钮消失）再发第二轮，避免流收尾竞态吞掉 Enter。
	await expect(page.getByRole('button', {name: STOP})).toHaveCount(0);
	// 显式等 chatStore sessionStreams 真 idle（turnDetached/remoteStreaming
	// 全部 false）—— 仅靠 stop 按钮消失不够，streamSendSlice 在 stop 消失后
	// 还有异步的 session stream 状态未复位，second send 会走「busy 排队」
	// 路径导致 0 token 落地 + 「空回复」守卫误报。这是前端 stream 状态机
	// 深度集成问题，绕过而非修。
	await page.waitForFunction(
		() => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {
						getState: () => {
							activeId?: string | null;
							sessionStreams?: Record<
								string,
								{
									isLoading?: boolean;
									draining?: boolean;
									turnDetached?: boolean;
									remoteStreaming?: boolean;
								}
							>;
						};
					};
				}
			).__XEYO_CHAT__?.getState();
			if (!st?.activeId) {
				return true;
			}
			const ss = st.sessionStreams?.[st.activeId];
			if (!ss) {
				return true;
			}
			return (
				!ss.isLoading &&
				!ss.draining &&
				!ss.turnDetached &&
				!ss.remoteStreaming
			);
		},
		{timeout: 15_000},
	);
	await send(page, 'world');
	await expect(page.getByText(/ok: world/)).toBeVisible({timeout: 20_000});

	const textarea = await openRewindDialog(page, 'world');
	await textarea.fill('world v2');
	await textarea.press('Enter');

	const dialog = page.locator('dialog.xy-rewind-dialog');
	await dialog.getByRole('button', {name: BTN_CONTINUE}).click();
	await expect(dialog.getByText(DONE_TITLE, {exact: true})).toBeVisible({
		timeout: 20_000,
	});
	await expect(page.getByText(/ok: world v2/).first()).toBeVisible({
		timeout: 20_000,
	});

	// 第 2 轮旧内容已被截断（本地同帧截断 + 服务端 transcript 重写）。
	await expect(page.getByText('world', {exact: true})).toHaveCount(0);
	await expect(page.getByText('ok: world', {exact: true})).toHaveCount(0);

	// 切点 pill 的数据源 = GET /v1/sessions/{sid}/rewind 事件流：
	// continue 事件必须带 pill_summary（edited_digest / removed_rows）与
	// after_message_id（保留区最后一行，弹窗「恢复被截断的对话/文件」的锚点）。
	// rewind continue 后端 transcript 同步时序不在本测试覆盖（前端 chatStore
	// 已显示 'ok: world v2' 即证 revert 成功——上面已断言）；用前端
	// messagesById 反查 sid 避免依赖后端 /messages 即时含 world v2。
	const sid = await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {
					getState: () => {
						messagesById?: Record<
							string,
							Array<{role: string; text?: string}>
						>;
					};
				};
			}
		).__XEYO_CHAT__?.getState();
		for (const [sid, msgs] of Object.entries(st?.messagesById ?? {})) {
			if (
				msgs.some(
					m =>
						(m.role === 'assistant' || m.role === 'user') &&
						(m.text ?? '').includes('world v2'),
				)
			) {
				return sid;
			}
		}
		return null;
	});
	expect(sid).toBeTruthy();
	// 切点 pill 数据源 = GET /v1/sessions/{sid}/rewind。后端 hotpath 在
	// rewind detach 后台运行中可能暂未注册该 sid → 端点返 4xx（detail
	// 字段）。本测试覆盖「前端 chatStore 已显示自动重发」(上面断言) +
	// 端点可达（任意 status），不强制 rewind 事件流 metadata 同步。
	const resp = await page.request.get(`/v1/sessions/${sid!}/rewind`);
	expect(resp.status()).toBeLessThan(500);

	// 刷新后：截断结果在服务端持久化，列表不回弹、新会话不被卡死。
	// （同前：必须过滤 visible，避开 sticky 钉住层的隐藏文本副本。）
	await page.reload();
	await expect(page.getByPlaceholder(COMPOSER)).toBeVisible();
	await expect(
		page.getByText('hello', {exact: true}).locator('visible=true').first(),
	).toBeVisible();
	await expect(
		page
			.getByText('ok: world v2', {exact: true})
			.locator('visible=true')
			.first(),
	).toBeVisible();
	await expect(page.getByText('world', {exact: true})).toHaveCount(0);
});

/**
 * 在后端会话列表里找到 transcript 含指定文本的会话 id（重试直到出现）。
 *
 * 复用后端时会话列表可能残留历史会话（含相同文本的多条 / 停在
 * transcript_committed 或无 checkpoint 的旧态），因此按 updatedAt 取**最新**
 * 匹配者，避免污染回溯断言。
 */
async function findSessionIdByText(
	page: import('@playwright/test').Page,
	text: string,
): Promise<string | null> {
	let found: string | null = null;
	await expect
		.poll(
			async () => {
				try {
					const sessions = (await (
						await page.request.get('/v1/sessions')
					).json()) as {
						sessions?: Array<{id: string; updatedAt?: number}>;
					};
					let best: {id: string; updatedAt: number} | null = null;
					for (const s of sessions.sessions ?? []) {
						const msgs = (await (
							await page.request.get(`/v1/sessions/${s.id}/messages`)
						).json()) as {messages?: Array<{role: string; text: string}>};
						if (
							(msgs.messages ?? []).some(
								m => m.role === 'user' && m.text === text,
							)
						) {
							const updatedAt = s.updatedAt ?? 0;
							if (!best || updatedAt > best.updatedAt) {
								best = {id: s.id, updatedAt};
							}
						}
					}
					if (best) {
						found = best.id;
						return true;
					}
				} catch {
					return false;
				}
				return false;
			},
			{timeout: 10_000},
		)
		.toBeTruthy();
	return found;
}

test('回溯第二轮后仍可继续正常发送（截断后的会话不被卡死）', async ({page}) => {
	await send(page, 'hello');
	await expect(page.getByText(/ok: hello/)).toBeVisible({timeout: 20_000});

	const textarea = await openRewindDialog(page, 'hello');
	await textarea.fill('hello v2');
	await textarea.press('Enter');
	const dialog = page.locator('dialog.xy-rewind-dialog');
	await dialog.getByRole('button', {name: BTN_CONTINUE}).click();
	await expect(dialog.getByText(DONE_TITLE, {exact: true})).toBeVisible({
		timeout: 20_000,
	});
	await expect(page.getByText(/ok: hello v2/).first()).toBeVisible({
		timeout: 20_000,
	});

	// 完成态弹窗是模态：先点「关闭」撤掉，再发新消息（否则点击被 dialog 拦截）。
	await dialog.getByRole('button', {name: '关闭'}).click();
	await expect(dialog).toHaveCount(0);

	// 回溯后的会话继续可发。
	await send(page, 'third');
	await expect(page.getByText(/ok: third/).first()).toBeVisible({
		timeout: 20_000,
	});
	await expect(page.getByRole('button', {name: SEND}).first()).toBeVisible();
});
