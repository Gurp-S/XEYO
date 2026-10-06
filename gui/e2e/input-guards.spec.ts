/**
 * 输入守卫探针（真 Chromium + 真 FastAPI，provider=fake）。
 *
 * 本档**不随 beforeEach 自动开工作区**——「未开文件夹」本身就是被测场景；
 * 归档与 side 会话两条各自现建现用同一批夹具。
 */
import {test, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';

const COMPOSER = '消息输入';
const STOP = '停止生成';
const QUEUE_DOCK = '[data-queue-dock]';
const BUSY_PAD = 'x'.repeat(3500);
const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-guards-'));

test.setTimeout(150_000);

async function bridgeSelectAndRoute(page: Page, sid: string): Promise<void> {
	await page.evaluate(async (target: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			selectSession: (id: string) => Promise<unknown>;
		};
		await st.selectSession(target);
		window.history.pushState({}, '', `/c/${encodeURIComponent(target)}`);
		window.dispatchEvent(new PopStateEvent('popstate'));
	}, sid);
}

/**
 * 打开一个刚归档的会话（等只读状态条出现）。
 *
 * 归档后 ChatPage 的交接**非确定**：有时立刻改选别处、有时不动、有时晚一步才
 * 改选（晚的那次会把重开顶掉）。探针不押时序：重开 + 短轮询循环，每轮都
 * 重新声明目标，直到状态条出现。
 */
async function openArchivedSession(page: Page, sid: string): Promise<void> {
	const bar = page.getByText('此对话已归档，恢复后才能发送或编辑。');
	let visible = false;
	for (let attempt = 0; attempt < 3 && !visible; attempt++) {
		await bridgeSelectAndRoute(page, sid);
		visible = await bar
			.waitFor({state: 'visible', timeout: 4_000})
			.then(() => true)
			.catch(() => false);
		if (!visible) {
			await page.waitForTimeout(400);
		}
	}
	// 诊断：失败前把现场钉下来（sid 是否还在 store、archived 标记、路由）。
	console.log(
		'[archived-diag]',
		JSON.stringify(
			await page.evaluate((target: string) => {
				const st = (
					window as unknown as {
						__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
					}
				).__XEYO_CHAT__!.getState() as unknown as {
					activeId: string | null;
					sessions: Array<{id: string; archived?: boolean}>;
				};
				const s = st.sessions.find(x => x.id === target);
				return {
					inStore: Boolean(s),
					archived: s?.archived ?? null,
					activeId: st.activeId,
					path: window.location.pathname,
					sessionCount: st.sessions.length,
				};
			}, sid),
		),
	);
	await expect(bar).toBeVisible({timeout: 4_000});
}

function watchSubmits(page: Page): () => string[] {
	const hits: string[] = [];
	page.on('request', req => {
		const method = req.method();
		if (method !== 'POST' && method !== 'PATCH' && method !== 'DELETE') return;
		const p = new URL(req.url()).pathname;
		if (p === '/v1/slash' || p === '/v1/chat/completions' || p.includes('/inbox')) {
			hits.push(`${method} ${p}`);
		}
	});
	return () => hits.slice();
}

async function view(page: Page): Promise<{
	messages: Array<{role: string; text: string}>;
	streaming: boolean;
	activeId: string;
}> {
	return page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState();
		const sid = (st.activeId as string) ?? '';
		const stream = ((st.sessionStreams ?? {}) as Record<string, Record<string, unknown>>)[
			sid
		];
		return {
			activeId: sid,
			streaming: Boolean(stream?.isLoading),
			messages: (
				((st.messagesById ?? {}) as Record<string, Array<Record<string, unknown>>>)[sid] ??
				[]
			).map(m => ({role: String(m.role ?? ''), text: String(m.text ?? '')})),
		};
	});
}

test.beforeEach(async ({page}) => {
	await seedFakeTestSettings(page);
	await bootChat(page);
});

test('未开工作区：发送被拦、明说原因、草稿保留', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	// 时间线取 raw activeId（null 与 '' 必须能分辨）+ 输入框值。
	const timeline: Array<Record<string, unknown>> = [];
	const snap = async (tag: string) => {
		timeline.push(
			await page.evaluate((t: string) => {
				const st = (
					window as unknown as {
						__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
					}
				).__XEYO_CHAT__!.getState();
				const el = document.querySelector('textarea[aria-label="消息输入"]') as
					| HTMLTextAreaElement
					| null;
				return {tag: t, activeId: String(st.activeId), value: el?.value ?? null,
					errorBanner: String(st.errorBanner ?? ''),
					spaces: ((st.spaces ?? []) as Array<Record<string, unknown>>).map(s => ({
						id: String(s.id),
						rootPath: String(s.rootPath ?? ''),
					})),
				};
			}, tag),
		);
	};
	await composer.click();
	await composer.fill('NO-WORKSPACE-MARK');
	await snap('typed');
	await composer.press('Enter');
	await snap('t0');
	await page.waitForTimeout(150);
	await snap('t150');
	await page.waitForTimeout(500);
	await snap('t650');
	await page.waitForTimeout(1500);
	await snap('t2150');
	console.log('[guard-diag]', JSON.stringify(timeline));
	console.log('[guard-submits]', JSON.stringify(submits()));
	await expect(
		page.getByText('请先打开一个项目文件夹，再发送消息。').first(),
	).toBeVisible({timeout: 8_000});
	await page.waitForTimeout(800);
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
	expect(await composer.inputValue()).toBe('NO-WORKSPACE-MARK');
});

test('归档会话：打开只读、发送被拦、草稿保留', async ({page}) => {
	const submits = watchSubmits(page);
	const sid = await page.evaluate(async () => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			createSession: (spaceId?: string) => Promise<string>;
		};
		return await st.createSession();
	});
	await page.evaluate(async (id: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			archiveSession: (id: string) => Promise<unknown>;
		};
		await st.archiveSession(id);
	}, sid);
	// archive 的异步尾巴会把视图交接走（ChatPage 见 active 变归档即改选别处，
	// 时序非确定）——用重试环重开到归档视图。
	await openArchivedSession(page, sid);
	await expect(
		page.getByText('此对话已归档，恢复后才能发送或编辑。'),
	).toBeVisible({timeout: 8_000});

	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('ARCHIVED-MARK');
	await composer.press('Enter');
	await expect(page.getByText('该对话已归档，请先恢复后发送').first()).toBeVisible({
		timeout: 5_000,
	});
	await page.waitForTimeout(500);
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
	expect(await composer.inputValue()).toBe('ARCHIVED-MARK');
});

test('归档后恢复：状态条消失、可以正常发送', async ({page}) => {
	const sid = await openWorkspaceSession(page, workspaceDir);
	await page.evaluate(async (id: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			archiveSession: (id: string) => Promise<unknown>;
		};
		await st.archiveSession(id);
	}, sid);
	// 前置自证（fresh 读、非冻结快照）：归档标记必须真落进 store；
	// 全量序下曾观察到此处之后标记丢失（archived:null、18 会话导入场景）——
	// 让失败停在这个可归因的点上，而不是条带 8s 超时。
	// 10-05 二次复现（全量门 1 次 + 单跑 1 次，均 archived:null；紧邻复跑不复现）：
	// 失败时 dump 全现场，下次归因先读 dump（登记 #5）。
	const readArchived = () =>
		page.evaluate((id: string) => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
				}
			).__XEYO_CHAT__!.getState() as unknown as {
				sessions: Array<{id: string; archived?: boolean; archivedAt?: number}>;
			};
			return st.sessions.find(x => x.id === id)?.archived ?? null;
		}, sid);
	try {
		await expect.poll(readArchived, {timeout: 5_000}).toBe(true);
	} catch (error) {
		console.log(
			'[archive-flag-diag]',
			JSON.stringify(
				await page.evaluate((id: string) => {
					const st = (
						window as unknown as {
							__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
						}
					).__XEYO_CHAT__!.getState() as unknown as {
						activeId: string | null;
						errorBanner?: string;
						sessions: Array<{
							id: string;
							archived?: boolean;
							archivedAt?: number;
						}>;
					};
					const s = st.sessions.find(x => x.id === id);
					return {
						entry: s
							? {archived: s.archived ?? null, archivedAt: s.archivedAt ?? null}
							: null,
						ids: st.sessions.map(x => x.id),
						activeId: st.activeId,
						errorBanner: String(st.errorBanner ?? ''),
					};
				}, sid),
			),
		);
		throw error;
	}
	// 等归档交接落定再重开（同「归档会话只读」案的顶掉竞态）——用重试环。
	await openArchivedSession(page, sid);

	await page.getByRole('button', {name: '恢复对话'}).click();
	await expect(page.getByText('此对话已归档，恢复后才能发送或编辑。')).toHaveCount(0, {
		timeout: 8_000,
	});

	// 恢复后发送链路必须真的通（请求发生 + 回合跑完 + 输入框清空）。
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('AFTER-RESTORE-MARK');
	await composer.press('Enter');
	await expect
		.poll(
			() => view(page).then(v => v.messages.some(m => m.role === 'assistant')),
			{timeout: 60_000},
		)
		.toBe(true);
	expect(await composer.inputValue()).toBe('');
});

test('side 会话忙时发送：409 回退（撤气泡、草稿回、无队列卡）', async ({page}) => {
	// 显式前置：side 发送要活跃工作区 cwd（后端 400 workspace cwd is required）。
	// 依赖"环境里恰好开着工作区"曾在全量序下假红（发送落到残留主会话 ⇒ 无工作区守卫）。
	await openWorkspaceSession(page, workspaceDir);
	const composer = page.getByLabel(COMPOSER);
	const sideId = await page.evaluate(async () => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			createSideSession: () => Promise<string>;
			renameSession: (id: string, title: string) => Promise<unknown>;
		};
		const id = await st.createSideSession();
		await st.renameSession(id, 'SIDE-PROBE');
		return id;
	});
	// 真侧栏点击（桥接直选会被路由/空间效应拉回默认空间 ⇒ 发送落到无工作区守卫）。
	await page.getByText('SIDE-PROBE').first().click();
	await expect.poll(() => view(page).then(v => v.activeId), {timeout: 8_000}).toBe(sideId);
	// 路由跟随：路由仍停在旧会话时，ChatPage 路由对齐效应会把 activeId 倒回
	// （点击后 poll 已过、发送前被拉回 ⇒ 假红）。同本档既有教训，显式钉住。
	await page.evaluate(async (id: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			selectSession: (sid: string) => Promise<unknown>;
		};
		await st.selectSession(id);
		window.history.pushState({}, '', `/c/${encodeURIComponent(id)}`);
		window.dispatchEvent(new PopStateEvent('popstate'));
	}, sideId);
	await page.waitForTimeout(300);
	expect((await view(page)).activeId).toBe(sideId);

	// 忙窗口
	await composer.click();
	await composer.fill(`ok: busy ${BUSY_PAD}`);
	await composer.press('Enter');
	await expect(page.getByRole('button', {name: STOP}).first()).toBeVisible({timeout: 20_000});

	// 忙时第二条：side 不排队 ⇒ 409 ⇒ 撤气泡、草稿退回、不许出排队卡。
	await composer.click();
	await composer.fill('SIDE-BUSY-MARK');
	await composer.press('Enter');
	await expect.poll(() => composer.inputValue(), {timeout: 15_000}).toBe('SIDE-BUSY-MARK');
	const v = await view(page);
	expect(v.messages.some(m => m.text === 'SIDE-BUSY-MARK')).toBe(false);
	await expect(page.locator(QUEUE_DOCK)).toHaveCount(0);
});

