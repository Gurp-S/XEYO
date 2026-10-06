/**
 * 输入链边缘探针（真 Chromium + 真 FastAPI，provider=fake）。
 *
 * 逐条跑「用户会做、既有用例没走过」的输入交互；失败 = 待判缺陷。
 * 每条断言的期望值都取自家口径的最小共识：Esc 归属于最上层可关闭物、
 * 空闲修饰键等价普通发送、排队项可编辑/可取消、引导最终必须送达。
 */
import {test, expect, type Page} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';

const COMPOSER = '消息输入';
const STOP = '停止生成';
const QUEUE_DOCK = '[data-queue-dock]';
const GOAL_BAR = '[data-goal-bar]';
/** 长回复 = 忙窗口（桩每字符数毫秒），够 Playwright 完成后续动作。 */
const BUSY_PAD = 'x'.repeat(3500);

const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-input-'));

test.setTimeout(150_000);

type StoreView = {
	sid: string;
	inbox: Array<{state: string; text: string; message_id: string | null}>;
	messages: Array<{
		role: string;
		text: string;
		queueState: string | null;
		mediaRefs: number;
	}>;
	streaming: boolean;
	draining: boolean;
};

async function view(page: Page): Promise<StoreView> {
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
			sid,
			inbox: (
				((st.inboxBySession ?? {}) as Record<string, Array<Record<string, unknown>>>)[sid] ??
				[]
			).map(i => ({
				state: String(i.state ?? ''),
				text: String(i.text ?? ''),
				message_id: (i.message_id as string | null) ?? null,
			})),
			messages: (
				((st.messagesById ?? {}) as Record<string, Array<Record<string, unknown>>>)[sid] ??
				[]
			).map(m => ({
				role: String(m.role ?? ''),
				text: String(m.text ?? ''),
				queueState: (m.queueState as string | null) ?? null,
				mediaRefs: Array.isArray(m.mediaRefs) ? (m.mediaRefs as string[]).length : 0,
			})),
			streaming: Boolean(stream?.isLoading),
			draining: Boolean(stream?.draining),
		};
	});
}

async function waitForView(
	page: Page,
	predicate: (v: StoreView) => boolean,
	timeout = 30_000,
): Promise<StoreView> {
	const deadline = Date.now() + timeout;
	let last = await view(page);
	while (!predicate(last)) {
		if (Date.now() > deadline) {
			throw new Error(
				`[waitForView] 超时 ${timeout}ms；末态=${JSON.stringify(last)}`,
			);
		}
		await page.waitForTimeout(200);
		last = await view(page);
	}
	return last;
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

async function startBusyTurn(page: Page, text: string): Promise<void> {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
	await expect(page.getByRole('button', {name: STOP}).first()).toBeVisible({
		timeout: 20_000,
	});
}

async function openTurn(page: Page, text: string): Promise<void> {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
	await expect
		.poll(() => view(page).then(v => v.streaming), {timeout: 30_000})
		.toBe(true);
	// 等"整闲"而不是"没在流"：sessionStreamActive = isLoading||draining，
	// 只等 isLoading 会在收尾排水窗口里发下一条，把它误判成忙 ⇒ 走排队路径
	// （>2000 字的正文会被 inbox 上限 413 "无法排队"，而同一句话隔一秒即是直发）。
	await expect
		.poll(
			() => view(page).then(v => v.streaming === false && v.draining === false),
			{timeout: 60_000},
		)
		.toBe(true);
}

test.beforeEach(async ({page}) => {
	await seedFakeTestSettings(page);
	await bootChat(page);
	await openWorkspaceSession(page, workspaceDir);
});

test('空闲时 Ctrl+Enter 等同普通发送：无引导回执、无队列卡', async ({page}) => {
	await openTurn(page, 'ok: idle-first');
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('ok: idle-second');
	await composer.press('Control+Enter');
	const v = await waitForView(
		page,
		v => v.messages.some(m => m.role === 'assistant' && m.text.includes('idle-second')),
		30_000,
	);
	expect(v.inbox).toEqual([]);
	await expect(page.locator(QUEUE_DOCK)).toHaveCount(0);
});

test('空白输入 Enter：不发请求、草稿保留', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('   ');
	await composer.press('Enter');
	await page.waitForTimeout(1_200);
	expect(submits()).toEqual([]);
	expect(await composer.inputValue()).toBe('   ');
});

test('发送时网络中断：消息不无声消失（气泡或草稿必存其一），且必须出声', async ({page}) => {
	// 首次提交直接断网：fetch 抛异常 = 无法确认服务端是否受理。
	await page.route('**/v1/chat/completions', route => route.abort('failed'), {
		times: 1,
	});
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('NETFAIL-MARK');
	await composer.press('Enter');
	// 不许无声：横幅要说"未确认"（两种收尾分支的文案都落在这一族）。
	await expect(
		page.getByText(/提交状态未确认|无法确认服务端是否接收/).first(),
	).toBeVisible({timeout: 15_000});
	// 收尾有两条合法分支（started=false：气泡撤回、原文退回输入框；
	// started=true：气泡保留、原文在会话记录里）——探针只钉共同的硬不变量：
	// 「消息不许消失在气泡撤回与清空输入框之间」，两处都空才是真丢。
	await page.waitForTimeout(1_500);
	const v = await view(page);
	const draft = await composer.inputValue();
	expect(
		v.messages.some(m => m.text === 'NETFAIL-MARK') || draft === 'NETFAIL-MARK',
		`原文两处都不在：messages=${JSON.stringify(v.messages.map(m => m.text).slice(-3))} draft=${JSON.stringify(draft)}`,
	).toBe(true);
});

test('停回合后排队消息不丢：先 hold，下一次人类回合 settle 后补投', async ({page}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	const composer = page.getByLabel(COMPOSER);
	await composer.fill('HOLD-MARK');
	await composer.press('Enter');
	await waitForView(page, v => v.inbox.length === 1, 15_000);

	// Esc = 停当前回合：排队消息保留（「interrupt 只停当前回合，停靠消息保留」）。
	await page.keyboard.press('Escape');
	await expect
		.poll(() => view(page).then(v => v.streaming), {timeout: 30_000})
		.toBe(false);
	const held = await view(page);
	expect(held.inbox.length).toBe(1);
	expect(held.inbox[0]?.text).toBe('HOLD-MARK');
	expect(
		held.messages.some(m => m.role === 'assistant' && m.text.includes('HOLD-MARK')),
	).toBe(false);

	// 下一条人类消息 settle 后，hold 的排队消息补投（不许停留在队列里无声消失）。
	await composer.click();
	await composer.fill('ok: after-stop');
	await composer.press('Enter');
	await waitForView(
		page,
		v =>
			v.inbox.length === 0 &&
			v.messages.some(m => m.role === 'assistant' && m.text.includes('HOLD-MARK')),
		90_000,
	);
});

test('流式中队列编辑框按 Esc：只退出编辑，不打断回合', async ({page}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	const composer = page.getByLabel(COMPOSER);
	await composer.fill('ESC-EDIT-MARK');
	await composer.press('Enter');
	await waitForView(page, v => v.inbox.length === 1, 15_000);

	const card = page.locator('.xy-queue-card').filter({hasText: 'ESC-EDIT-MARK'});
	await card.locator('button[title="编辑消息"]').click();
	const editor = page.getByLabel('编辑排队消息');
	await expect(editor).toBeVisible({timeout: 5_000});
	await editor.press('Escape');

	// 期望：编辑退场；回合仍在流式（Esc 属于最上层可关闭物）。
	await expect(editor).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByRole('button', {name: STOP}).first()).toBeVisible({
		timeout: 5_000,
	});
	expect((await view(page)).streaming).toBe(true);
});

test('流式中 goal 编辑框按 Esc：只退出编辑，不打断回合', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('/goal esc 探针目标');
	await composer.press('Enter');
	await expect(page.locator(GOAL_BAR)).toBeVisible({timeout: 10_000});

	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	await page.locator(GOAL_BAR).getByRole('button', {name: '编辑目标'}).click();
	const editor = page.getByLabel('目标内容');
	await expect(editor).toBeVisible({timeout: 5_000});
	await editor.press('Escape');

	await expect(editor).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByRole('button', {name: STOP}).first()).toBeVisible({
		timeout: 5_000,
	});
	expect((await view(page)).streaming).toBe(true);
});

test('排队项可编辑、可取消：投递的是编辑后文本，取消的不出现', async ({page}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	const composer = page.getByLabel(COMPOSER);
	await composer.fill('QUEUE-ORIG');
	await composer.press('Enter');
	await composer.fill('QUEUE-CANCELLED');
	await composer.press('Enter');
	await waitForView(page, v => v.inbox.length === 2, 15_000);

	// 多条 = 计数头默认折叠（DSH QueueDock 口径）：先展开才有点击面。
	const head = page.locator('.xy-queue-head');
	await expect(head).toBeVisible({timeout: 5_000});
	if ((await head.getAttribute('aria-expanded')) === 'false') {
		await head.click();
	}

	const card = page.locator('.xy-queue-card').filter({hasText: 'QUEUE-ORIG'});
	await card.locator('button[title="编辑消息"]').click();
	const editor = page.getByLabel('编辑排队消息');
	await editor.fill('QUEUE-EDITED');
	await editor.press('Enter');
	await expect(
		page.locator('.xy-queue-card').filter({hasText: 'QUEUE-EDITED'}),
	).toBeVisible({timeout: 5_000});

	const cancelCard = page.locator('.xy-queue-card').filter({hasText: 'QUEUE-CANCELLED'});
	await cancelCard.locator('button[title="取消排队"]').click();
	await waitForView(page, v => v.inbox.length === 1, 10_000);

	const delivered = await waitForView(
		page,
		v =>
			v.inbox.length === 0 &&
			v.messages.some(
				m => m.role === 'assistant' && m.text.includes('QUEUE-EDITED'),
			),
		60_000,
	);
	expect(delivered.messages.some(m => m.text.includes('QUEUE-CANCELLED'))).toBe(false);
	// 编辑后的文本必须同步到用户气泡（否则气泡与投递内容两套文本）。
	expect(
		delivered.messages.some(m => m.role === 'user' && m.text === 'QUEUE-EDITED'),
	).toBe(true);
});

test('忙时 Ctrl+Enter 引导：回合结束兜底送达，模型真的见到它', async ({page}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	const composer = page.getByLabel(COMPOSER);
	await composer.fill('STEER-DELIVER-MARK');
	await composer.press('Control+Enter');
	await expect(page.getByText(/已受理：最早在下个边界投递/).first()).toBeVisible({
		timeout: 15_000,
	});
	const v = await waitForView(
		page,
		v =>
			v.messages.some(
				m => m.role === 'assistant' && m.text.includes('STEER-DELIVER-MARK'),
			),
		90_000,
	);
	expect(v.messages.some(m => m.role === 'user' && m.text === 'STEER-DELIVER-MARK')).toBe(
		true,
	);
	// 送达轮随后收尾，卡与投递态清空（marker 在流式中就会进文本，不能只钉它出现）。
	await expect
		.poll(() => view(page).then(x => x.streaming), {timeout: 60_000})
		.toBe(false);
	await expect
		.poll(() => view(page).then(x => x.inbox.length), {timeout: 30_000})
		.toBe(0);
});

// 1x1 透明 PNG——上传链路要的是真文件，不能拿伪造字节。
const PNG_1X1 = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
	'base64',
);

function writePixel(dir: string, name = 'pixel.png'): string {
	const p = path.join(dir, name);
	fs.writeFileSync(p, PNG_1X1);
	return p;
}

test('忙时带图排队：队列卡出缩略图，投递后图片随消息保留', async ({page}) => {
	const imgPath = writePixel(workspaceDir);
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	await page.locator('.xy-composer-surface input[type=file]').setInputFiles(imgPath);
	await expect(page.getByRole('button', {name: /移除 pixel\.png/})).toBeVisible({
		timeout: 10_000,
	});
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('IMG-QUEUE-MARK');
	await composer.press('Enter');

	// 202 排队且 media_refs 真回传：卡上应渲染缩略图。
	await waitForView(page, v => v.inbox.length === 1, 15_000);
	await expect(page.locator('.xy-queue-thumb').first()).toBeVisible({timeout: 10_000});

	// settle 投递：图片不许在投递（服务端权威行替换本地气泡）时消失。
	const delivered = await waitForView(
		page,
		v =>
			v.inbox.length === 0 &&
			v.messages.some(
				m => m.role === 'assistant' && m.text.includes('IMG-QUEUE-MARK'),
			),
		60_000,
	);
	expect(
		delivered.messages.some(m => m.role === 'user' && m.mediaRefs > 0),
	).toBe(true);
});

test('图片上传失败：消息不发、草稿与附件保留、出声', async ({page}) => {
	const imgPath = writePixel(workspaceDir, 'pixel-fail.png');
	const submits = watchSubmits(page);
	await page.route('**/v1/media/upload', route => route.abort('failed'), {times: 1});
	await page.locator('.xy-composer-surface input[type=file]').setInputFiles(imgPath);
	await expect(page.getByRole('button', {name: /移除 pixel-fail\.png/})).toBeVisible({
		timeout: 10_000,
	});
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('UPLOADFAIL-MARK');
	await composer.press('Enter');
	await page.waitForTimeout(2_000);

	// 不静默丢：消息没进模型（无 /v1/chat 提交）、草稿与附件都在，用户可重试。
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
	expect((await view(page)).messages.some(m => m.text.includes('UPLOADFAIL-MARK'))).toBe(
		false,
	);
	expect(await composer.inputValue()).toBe('UPLOADFAIL-MARK');
	await expect(page.getByRole('button', {name: /移除 pixel-fail\.png/})).toBeVisible();
});

test('斜杠弹层：技能异步到达时，Enter 不许选中用户没看过的行', async ({page}) => {
	// 植入一个会命中 "/go" 的技能（技能组渲染在命令组之前）。
	// 技能清单受 enabled_extensions 门控（默认关）——工作区级设置开启即可，不动后端 env。
	const skillDir = path.join(workspaceDir, '.xeyo', 'skills', 'go-probe');
	fs.mkdirSync(skillDir, {recursive: true});
	fs.writeFileSync(
		path.join(skillDir, 'SKILL.md'),
		'---\nuser_invocable: true\n---\n\n# go-probe\n\nPopup ordering probe.\n',
	);
	fs.writeFileSync(
		path.join(workspaceDir, '.xeyo', 'settings.json'),
		JSON.stringify({enabled_extensions: true}, null, 2) + '\n',
	);
	// 技能清单由首个 "/" 触发异步拉取：放慢它，让"命令已显示、技能还在路上"的窗口可复现。
	await page.route('**/v1/skills**', async route => {
		await new Promise(resolve => setTimeout(resolve, 1_200));
		await route.continue();
	});
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.pressSequentially('/go');
	// 窗口期：只有命令组，"/goal" 高亮在首行。
	const selected = page.locator('[aria-selected="true"]').first();
	await expect(selected).toContainText('goal', {timeout: 5_000});
	// 技能到达：列表会在顶部前插 go-probe 行（先自证增长确实发生）。
	await expect(page.getByText(/go-probe/).first()).toBeVisible({timeout: 8_000});
	// 硬不变量：Enter 选中的必须是用户刚看到的 "/goal"，不许被新到技能顶走。
	await composer.press('Enter');
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toContain('/goal');
});

/** store 桥：按会话 id 切会话（与侧栏点击同一条 selectSession 通路）+ 同步 SPA 路由。
 *  只调 selectSession 不换路由时，ChatPage 的路由对齐 effect 会把 activeId 倒回旧会话。 */
async function selectSessionById(page: Page, sid: string): Promise<void> {
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

test('会话切换：各自草稿不丢不串（切走再切回）', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('DRAFT-A');
	const bridge = () =>
		page.evaluate(() => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
				}
			).__XEYO_CHAT__!.getState() as unknown as {activeId: string};
			return st.activeId;
		});
	const sidA = await bridge();
	const sidB = await page.evaluate(async () => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			sessions: Array<{id: string; spaceId?: string}>;
			activeId: string;
			createSession: (spaceId?: string) => Promise<string>;
		};
		const spaceId = st.sessions.find(s => s.id === st.activeId)?.spaceId;
		return await st.createSession(spaceId);
	});

	await selectSessionById(page, sidB);
	await expect.poll(bridge, {timeout: 5_000}).toBe(sidB);
	// 全新会话不许把 A 的草稿带过来。
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('');
	await composer.click();
	await composer.fill('DRAFT-B');

	await selectSessionById(page, sidA);
	await expect.poll(bridge, {timeout: 5_000}).toBe(sidA);
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('DRAFT-A');

	// 再切回 B：B 的草稿也还在（双向都不丢）。
	await selectSessionById(page, sidB);
	await expect.poll(bridge, {timeout: 5_000}).toBe(sidB);
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('DRAFT-B');
});

/** 在 composer 里执行一个无参斜杠命令：首枪弹层选中回填，第二枪执行。 */
async function runBareSlash(page: Page, name: string): Promise<void> {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.pressSequentially(name);
	await composer.press('Enter');
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe(`${name} `);
	await composer.press('Enter');
}

test('/retry：没有可重试的消息时出声，不发请求', async ({page}) => {
	const submits = watchSubmits(page);
	await runBareSlash(page, '/retry');
	await expect(page.getByText('还没有可重试的消息').first()).toBeVisible({timeout: 5_000});
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
});

test('/retry：重发上一条用户消息（气泡与回复各再来一条）', async ({page}) => {
	await openTurn(page, 'ok: retry-me');
	await runBareSlash(page, '/retry');
	const v = await waitForView(
		page,
		v =>
			v.messages.filter(m => m.role === 'assistant' && m.text.includes('retry-me'))
				.length >= 2,
		60_000,
	);
	expect(
		v.messages.filter(m => m.role === 'user' && m.text === 'ok: retry-me').length,
	).toBe(2);
});

test('/retry：忙时被挡要说原因，草稿保留', async ({page}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.pressSequentially('/retry');
	await composer.press('Enter');
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('/retry ');
	await composer.press('Enter');
	await expect(page.getByText(/\/retry 暂不可执行/).first()).toBeVisible({timeout: 5_000});
	// 被拒的命令不执行、原文保留在输入框（用户可停回合后再来）。
	expect(await composer.inputValue()).toBe('/retry ');
});

test('命令面板：Ctrl+K 开、Esc 关、搜索不逃逸成发送', async ({page}) => {
	const submits = watchSubmits(page);
	await page.keyboard.press('Control+k');
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByPlaceholder(/搜索工作区/).fill('goal');
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(submits()).toEqual([]);
});

test('命令面板：键盘选中一条会话结果，真切过去并关面板', async ({page}) => {
	await openTurn(page, 'ok: palette-target');
	const targetSid = (await view(page)).sid;
	// 切到新会话，保证「选中 target」是一次真实切换。
	await page.getByRole('button', {name: '新对话'}).first().click();
	await expect.poll(() => view(page).then(v => v.sid), {timeout: 8_000}).not.toBe(targetSid);

	await page.keyboard.press('Control+k');
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByPlaceholder(/搜索工作区/).fill('palette-target');
	const option = dialog.getByRole('option').filter({hasText: 'palette-target'}).first();
	await expect(option).toBeVisible({timeout: 8_000});
	await page.keyboard.press('Enter');
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	await expect.poll(() => view(page).then(v => v.sid), {timeout: 8_000}).toBe(targetSid);
});

test('命令面板：文件结果键盘打开到预览（此前零覆盖）', async ({page}) => {
	fs.writeFileSync(path.join(workspaceDir, 'palette-open.txt'), 'PALETTE-OPEN\n');
	await page.keyboard.press('Control+k');
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByPlaceholder(/搜索工作区/).fill('palette-open');
	const option = dialog.getByRole('option').filter({hasText: 'palette-open.txt'}).first();
	await expect(option).toBeVisible({timeout: 10_000});
	await page.keyboard.press('Enter');
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	// 打开到文件预览（内容逐字可见），不是只把面板关了。
	await expect(page.locator('.xy-file-preview-pane')).toContainText('PALETTE-OPEN', {
		timeout: 10_000,
	});
});

test('拖放文件进输入面：走同一条附件链（chip 出现）', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	const dt = await page.evaluateHandle(() => new DataTransfer());
	await page.evaluate((handle: DataTransfer) => {
		const file = new File(
			[new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
			'dropped.png',
			{type: 'image/png'},
		);
		handle.items.add(file);
	}, dt);
	await page.dispatchEvent('.xy-composer-surface', 'drop', {
		dataTransfer: dt as unknown as never,
	});
	await expect(page.getByRole('button', {name: /移除 dropped\.png/})).toBeVisible({
		timeout: 10_000,
	});
});

test('开关命令即时反馈：/mode 与 /approval 的界面状态与真实生效值一致', async ({
	page,
}) => {
	const composer = page.getByLabel(COMPOSER);
	// /mode plan：回执出声 + Plan chip 立即挂出（读权威状态，不读回执旗标）。
	await composer.click();
	await composer.fill('/mode plan');
	await composer.press('Enter');
	await expect(page.getByText('mode → plan').first()).toBeVisible({timeout: 5_000});
	await expect(page.getByRole('button', {name: '退出 Plan 模式'})).toBeVisible({
		timeout: 5_000,
	});
	// chip 的退出按钮把模式拉回 agent：chip 消失。
	await page.getByRole('button', {name: '退出 Plan 模式'}).click();
	await expect(page.getByRole('button', {name: '退出 Plan 模式'})).toHaveCount(0, {
		timeout: 5_000,
	});
	// /approval never：审批按钮切到"完全访问权限"档
	//（按钮可访问名是 aria-label「审批模式」，档位文字在内部）。
	await composer.click();
	await composer.fill('/approval never');
	await composer.press('Enter');
	await expect(page.getByRole('button', {name: '审批模式'})).toContainText('完全访问权限', {
		timeout: 5_000,
	});
	// 复位 risk（避免本用例改变后续意图；每个 e2e 测试本是新上下文，纯卫生）。
	await composer.fill('/approval risk');
	await composer.press('Enter');
	await expect(page.getByRole('button', {name: '审批模式'})).toContainText('帮我批准', {
		timeout: 5_000,
	});
});

test('审批模式弹层：外点与 Esc 都能关；流式中 Esc 关菜单、不许把回合停掉', async ({page}) => {
	const trigger = page.getByRole('button', {name: '审批模式', exact: true});
	const menu = page.getByRole('menu');

	// 外点关闭：菜单上翻会盖住输入框中段（Playwright actionability 会拒点被盖元素），
	// 用聊天区左上角发真实坐标 mousedown——它不在菜单/按钮的包含范围内。
	await trigger.click();
	await expect(menu).toBeVisible({timeout: 5_000});
	await page.mouse.click(320, 240);
	await expect(menu).toHaveCount(0, {timeout: 5_000});

	// 空闲 Esc 关闭。
	await trigger.click();
	await expect(menu).toBeVisible({timeout: 5_000});
	await page.keyboard.press('Escape');
	await expect(menu).toHaveCount(0, {timeout: 5_000});

	// 流式中：Esc 归属最上层（菜单），回合必须继续。
	await startBusyTurn(page, `ok: ${BUSY_PAD}`);
	await trigger.click();
	await expect(menu).toBeVisible({timeout: 5_000});
	await page.keyboard.press('Escape');
	await expect(menu).toHaveCount(0, {timeout: 5_000});
	expect((await view(page)).streaming).toBe(true);

	// 收尾：停回合并等整闲，别把忙窗口留给下一个用例。
	await page.getByRole('button', {name: STOP}).first().click();
	await expect
		.poll(() => view(page).then(v => v.streaming === false && v.draining === false), {
			timeout: 60_000,
		})
		.toBe(true);
});

test('消息编辑的键盘与右键入口：与点气泡同一编辑器、Esc 同退场', async ({page}) => {
	await openTurn(page, 'ok: entry-consistency');
	const bubble = page
		.getByRole('button', {name: '编辑这条消息'})
		.filter({hasText: 'entry-consistency'})
		.first();
	const editor = page.getByLabel('编辑历史消息');
	// 键盘入口：聚焦气泡 → Enter 进编辑（与点击同一条 onEdit）。
	await bubble.focus();
	await page.keyboard.press('Enter');
	await expect(editor).toBeVisible({timeout: 5_000});
	await expect(editor).toHaveValue('ok: entry-consistency');
	await editor.press('Escape');
	await expect(editor).toHaveCount(0, {timeout: 5_000});
	// 右键入口：菜单 → 编辑消息 → 同一编辑器。
	await bubble.click({button: 'right'});
	const menu = page.getByRole('menu');
	await expect(menu).toBeVisible({timeout: 5_000});
	await menu.getByRole('menuitem', {name: '编辑消息'}).click();
	await expect(editor).toBeVisible({timeout: 5_000});
	await expect(editor).toHaveValue('ok: entry-consistency');
	await editor.press('Escape');
	await expect(editor).toHaveCount(0, {timeout: 5_000});
});

test('/run：裸命令被参数守卫拦下；带参原样进模型', async ({page}) => {
	const submits = watchSubmits(page);
	await runBareSlash(page, '/run');
	// 必填参数未填：不执行也不发送，草稿留在框里（Composer 级守卫，先于斜杠网关）。
	await page.waitForTimeout(800);
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
	const composer = page.getByLabel(COMPOSER);
	expect(await composer.inputValue()).toBe('/run ');
	expect((await view(page)).messages.length).toBe(0);
	// 带参：原样发送（不被斜杠网关吞掉，正文一字不改）。
	await composer.fill('/run ok: run-me');
	await composer.press('Enter');
	const v = await waitForView(
		page,
		v =>
			v.messages.some(
				m => m.role === 'assistant' && m.text.includes('run-me'),
			),
		30_000,
	);
	expect(v.messages.some(m => m.role === 'user' && m.text === '/run ok: run-me')).toBe(
		true,
	);
});

test('粘贴多行文本：原样进输入框，不误发', async ({page}) => {
	const submits = watchSubmits(page);
	await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
	await page.evaluate(() => navigator.clipboard.writeText('PASTE-L1\nPASTE-L2'));
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await page.keyboard.press('Control+v');
	await expect
		.poll(() => composer.inputValue(), {timeout: 5_000})
		.toBe('PASTE-L1\nPASTE-L2');
	expect(submits()).toEqual([]);
});

test('@ 文件引用：键盘选中把 @路径 插入输入框，且随正文进发送链', async ({page}) => {
	fs.writeFileSync(path.join(workspaceDir, 'alpha-ref.txt'), 'x');
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.pressSequentially('@alpha');
	await expect(page.getByText(/alpha-ref\.txt/).first()).toBeVisible({timeout: 8_000});
	await composer.press('Enter');
	// 词元整体被替换成 `@相对路径 `，不留残字。
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('@alpha-ref.txt ');
	// 发送链：引用保留在用户消息正文里（模型可见面），并跑出一轮回复。
	await composer.press('Enter');
	const v = await waitForView(
		page,
		v =>
			v.messages.some(
				m => m.role === 'user' && m.text.includes('@alpha-ref.txt'),
			),
		30_000,
	);
	await waitForView(page, v => v.messages.some(m => m.role === 'assistant'), 30_000);
	expect(v.messages.some(m => m.role === 'user' && m.text === '@alpha-ref.txt')).toBe(
		true,
	);
});

test('文件预览选区（代码文件）：工具条 Add to Chat 与 Ctrl+L 都把片段加进输入框', async ({page}) => {
	fs.writeFileSync(
		path.join(workspaceDir, 'sel-probe.txt'),
		'SEL-ALPHA-line\nSEL-BETA-line\nSEL-GAMMA-line\n',
	);
	// 工作区（右栏）可能默认收起：展开后再刷新目录，让新文件进列表。
	const expand = page.getByRole('button', {name: '展开工作区'});
	if ((await expand.count()) > 0) {
		await expand.click();
	}
	await page.getByRole('button', {name: '刷新目录'}).click();
	const row = page.getByRole('button', {name: /sel-probe\.txt/});
	await expect(row).toBeVisible({timeout: 10_000});
	await row.click();

	// 非 markdown 文本 → 代码高亮视图（CodeBlock file），此前无选择根：
	// 选中文本不出工具条、Ctrl+L 无反应（'code' 变体整支不可达）。
	await expect(page.locator('.xy-code-file').first()).toContainText('SEL-ALPHA-line', {
		timeout: 10_000,
	});

	// 用真实 DOM 选区 + 冒泡 mouseup 驱动 refreshPick（与人工划选同一条监听链）。
	const selectLine = (rootSel: string, mark: string) =>
		page.evaluate(
			([sel, token]) => {
				const root = document.querySelector(sel);
				if (!root) {
					throw new Error(`selection root missing: ${sel}`);
				}
				const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
				let node: Text | null = null;
				while ((node = walker.nextNode() as Text | null)) {
					if (node.textContent?.includes(token)) {
						break;
					}
				}
				if (!node) {
					throw new Error(`text node missing: ${token}`);
				}
				const start = node.textContent!.indexOf(token);
				const range = document.createRange();
				range.setStart(node, start);
				range.setEnd(node, start + token.length);
				const domSel = window.getSelection()!;
				domSel.removeAllRanges();
				domSel.addRange(range);
				// 派发到元素（真实鼠标事件的 target 恒为元素；文本节点会让
				// md 分支的 e.target.closest 抛 TypeError——探针自伤，非产品缺陷）。
				(node.parentElement ?? node).dispatchEvent(
					new MouseEvent('mouseup', {bubbles: true, button: 0}),
				);
			},
			[rootSel, mark] as const,
		);

	await selectLine('.xy-code-file', 'SEL-ALPHA-line');
	const toolbar = page.getByRole('toolbar', {name: '代码选区工具'});
	await expect(toolbar).toBeVisible({timeout: 5_000});
	await toolbar.getByRole('button', {name: /Add to Chat/}).click();
	await expect(page.getByRole('button', {name: '移除 sel-probe.txt'})).toHaveCount(1, {
		timeout: 5_000,
	});

	// Ctrl+L（modLabel 提示的快捷键）：重选另一行，直接追加片段（不点按钮）。
	await selectLine('.xy-code-file', 'SEL-BETA-line');
	await expect(toolbar).toBeVisible({timeout: 5_000});
	await page.evaluate(() => {
		window.dispatchEvent(
			new KeyboardEvent('keydown', {key: 'l', ctrlKey: true, bubbles: true}),
		);
	});
	await expect(page.getByRole('button', {name: '移除 sel-probe.txt'})).toHaveCount(2, {
		timeout: 5_000,
	});

	// 回归护栏：md 预览工具条（此前的唯一可达路径）经同一次改动后仍能插入。
	fs.writeFileSync(path.join(workspaceDir, 'sel-probe.md'), '# md\n\nMD-SEL-line\n');
	await page.getByRole('tab', {name: '文件'}).click();
	await page.getByRole('button', {name: '刷新目录'}).click();
	await page.getByRole('button', {name: /sel-probe\.md/}).click();
	await expect(page.getByText('MD-SEL-line').first()).toBeVisible({timeout: 10_000});
	// 格式按钮相位（此前零覆盖）：选中 → 加粗 → md 编辑器里出现 <strong>。
	await selectLine('.xy-md-doc', 'MD-SEL-line');
	const fmtToolbar = page.getByRole('toolbar', {name: 'Markdown 选区工具'});
	await expect(fmtToolbar).toBeVisible({timeout: 5_000});
	await fmtToolbar.getByRole('button', {name: '加粗'}).click();
	await expect(
		page
			.locator('.xy-md-editable strong')
			.filter({hasText: 'MD-SEL-line'})
			.first(),
	).toBeVisible({timeout: 5_000});
	// 问主对话相位（重选——格式应用后选区被清）。
	await selectLine('.xy-md-doc', 'MD-SEL-line');
	const mdToolbar = page.getByRole('toolbar', {name: 'Markdown 选区工具'});
	await expect(mdToolbar).toBeVisible({timeout: 5_000});
	await mdToolbar.getByRole('button', {name: '问主对话'}).click();
	await expect(page.getByRole('button', {name: '移除 sel-probe.md'})).toHaveCount(1, {
		timeout: 5_000,
	});
});

test('源码编辑：失败出声不损坏原文、切文件草稿不丢；带直写旗标时真落盘', async ({page}) => {
	const filePath = path.join(workspaceDir, 'sel-edit.txt');
	const original = 'EDIT-LINE-ONE\nEDIT-LINE-TWO\n';
	fs.writeFileSync(filePath, original);
	fs.writeFileSync(path.join(workspaceDir, 'sel-edit2.txt'), 'OTHER-FILE\n');

	const expand = page.getByRole('button', {name: '展开工作区'});
	if ((await expand.count()) > 0) {
		await expand.click();
	}
	await page.getByRole('button', {name: '刷新目录'}).click();
	await page.getByRole('button', {name: /sel-edit\.txt/}).click();

	const pane = page.locator('.xy-file-preview-pane');
	await pane.getByRole('button', {name: '编辑', exact: true}).click();
	const area = page.getByLabel('sel-edit.txt 源码');
	await expect(area).toBeVisible({timeout: 10_000});
	await expect(area).toHaveValue(original);

	// 直写旗标决定本环境是「失败路径」（默认关：出声+不落盘+脏标记保留）
	// 还是「成功路径」（XEYO_WORKSPACE_FS_WRITABLE=1：自动保存真落盘）。
	const writable = process.env.XEYO_WORKSPACE_FS_WRITABLE === '1';
	const edited = `${original}EDIT-MARK\n`;
	await area.fill(edited);

	if (writable) {
		await expect
			.poll(() => fs.readFileSync(filePath, 'utf8'), {timeout: 8_000})
			.toBe(edited);
		await expect(pane.getByText('已保存', {exact: true})).toBeVisible({timeout: 5_000});
	} else {
		// 防抖自动保存在 ~700ms 后尝试 → 后端拒绝 → 出声（含设置指引）。
		await expect(
			page.getByText(/XEYO_WORKSPACE_FS_WRITABLE/).first(),
		).toBeVisible({timeout: 8_000});
		await page.waitForTimeout(1_200);
		expect(fs.readFileSync(filePath, 'utf8')).toBe(original);
		await expect(pane.getByText('未保存', {exact: true})).toBeVisible({timeout: 5_000});
	}

	// 切走再切回：草稿原样恢复（失败=unsavedDrafts 回读；成功=盘上即新文）。
	await page.getByRole('tab', {name: '文件'}).click();
	await page.getByRole('button', {name: '刷新目录'}).click();
	await page.getByRole('button', {name: 'sel-edit2.txt', exact: true}).click();
	await expect(page.locator('.xy-code-file').first()).toContainText('OTHER-FILE', {
		timeout: 10_000,
	});
	await page.getByRole('tab', {name: '文件'}).click();
	await page.getByRole('button', {name: 'sel-edit.txt', exact: true}).click();
	await pane.getByRole('button', {name: '编辑', exact: true}).click();
	await expect(page.getByLabel('sel-edit.txt 源码')).toHaveValue(edited, {
		timeout: 10_000,
	});
	// 任何路径都不许静默改写原文。
	expect(fs.readFileSync(filePath, 'utf8')).toBe(writable ? edited : original);
});

test('diff 视图选区：代码工具条同样可达（Add to Chat 带出改动片段）', async ({page}) => {
	// 真 git 仓（e2e 常规工作区不是仓，diff 链从未被覆盖过）。
	const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-diff-'));
	const git = (...args: string[]) =>
		execFileSync('git', args, {cwd: repo, stdio: 'pipe'});
	git('init', '-q');
	git('config', 'user.email', 'e2e@test');
	git('config', 'user.name', 'e2e');
	fs.writeFileSync(path.join(repo, 'diff-probe.txt'), 'DIFF-ALPHA\nDIFF-BETA\n');
	git('add', '-A');
	git('commit', '-qm', 'init');
	fs.writeFileSync(path.join(repo, 'diff-probe.txt'), 'DIFF-ALPHA\nDIFF-BETA-CHANGED\n');

	await openWorkspaceSession(page, repo);
	const expand = page.getByRole('button', {name: '展开工作区'});
	if ((await expand.count()) > 0) {
		await expand.click();
	}
	await page.getByRole('button', {name: '刷新目录'}).click();
	await page.getByRole('button', {name: 'diff-probe.txt', exact: true}).click();
	// 文件有未提交改动 ⇒ 头部出现「显示改动」切换。
	await expect(page.getByRole('button', {name: '显示改动'})).toBeVisible({
		timeout: 10_000,
	});
	await page.getByRole('button', {name: '显示改动'}).click();
	await expect(page.getByText('DIFF-BETA-CHANGED').first()).toBeVisible({
		timeout: 10_000,
	});

	// 在 diff 里划选加行文本 → 代码变体工具条（#22 放开的 diff 分支）。
	await page.evaluate(() => {
		const pane = document.querySelector('.xy-file-preview-pane');
		if (!pane) {
			throw new Error('preview pane missing');
		}
		const walker = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT);
		let node: Text | null = null;
		while ((node = walker.nextNode() as Text | null)) {
			if (node.textContent?.includes('DIFF-BETA-CHANGED')) {
				break;
			}
		}
		if (!node) {
			throw new Error('diff text node missing');
		}
		const token = 'DIFF-BETA-CHANGED';
		const start = node.textContent!.indexOf(token);
		const range = document.createRange();
		range.setStart(node, start);
		range.setEnd(node, start + token.length);
		const sel = window.getSelection()!;
		sel.removeAllRanges();
		sel.addRange(range);
		(node.parentElement ?? node).dispatchEvent(
			new MouseEvent('mouseup', {bubbles: true, button: 0}),
		);
	});
	const toolbar = page.getByRole('toolbar', {name: '代码选区工具'});
	await expect(toolbar).toBeVisible({timeout: 5_000});
	await toolbar.getByRole('button', {name: /Add to Chat/}).click();
	await expect(
		page.getByRole('button', {name: '移除 diff-probe.txt'}),
	).toHaveCount(1, {timeout: 5_000});
});

test('流式中刷新：重挂后不许出现"UI 假空闲"（后端还在跑、界面说闲）', async ({page}) => {
	await startBusyTurn(page, `ok: ${BUSY_PAD}`);
	const sid = (await view(page)).sid;

	await page.reload();
	await expect(page.getByLabel(COMPOSER)).toBeVisible({timeout: 20_000});
	// 等桥就绪 + 重挂/恢复链（reattachActiveStreams + recoverStuckStream）跑完的安全窗。
	await expect
		.poll(() => page.evaluate(() => Boolean(window.__XEYO_CHAT__)), {timeout: 10_000})
		.toBe(true);
	await page.waitForTimeout(8_000);

	const v = await view(page);
	if (!v.streaming) {
		// UI 说空闲 ⇒ 后端必须也已收尾；否则用户下一条会莫名撞 session_busy/排队。
		const task = await page.request.get(
			`/v1/sessions/${encodeURIComponent(sid)}/task`,
		);
		const body = (await task.json()) as {busy?: boolean};
		expect(body.busy).toBe(false);
	} else {
		// 已重挂：停止键必须真的能停（收尾到整闲），不许是装饰。
		await page.getByRole('button', {name: STOP}).first().click();
		await expect
			.poll(() => view(page).then(x => x.streaming === false && x.draining === false), {
				timeout: 60_000,
			})
			.toBe(true);
	}
});

test('停回合（按钮）后排队项自动补投：不许滞留，也不需要手动恢复', async ({page}) => {
	await startBusyTurn(page, `ok: ${BUSY_PAD}`);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('RESUME-MARK');
	await composer.press('Enter');
	await expect(page.locator(QUEUE_DOCK)).toBeVisible({timeout: 15_000});

	// 按钮停回合：不同于 ESC 的即时 hold 断言——这里烧到整闲后放任数秒，
	// 排队项必须已经自动补投（ECHO 出现、inbox 清空），不许滞留等用户手动。
	await page.getByRole('button', {name: STOP}).first().click();
	await expect
		.poll(() => view(page).then(v => v.streaming === false && v.draining === false), {
			timeout: 60_000,
		})
		.toBe(true);
	const v = await waitForView(
		page,
		v =>
			v.inbox.length === 0 &&
			v.messages.some(m => m.role === 'assistant' && m.text.includes('RESUME-MARK')),
		60_000,
	);
	expect(
		v.messages.some(
			m => m.role === 'user' && m.text === 'RESUME-MARK' && m.queueState == null,
		),
	).toBe(true);
});

test('手动「继续投递」：autorun=false 的滞留项可恢复（此前零覆盖）', async ({page}) => {
	// 触发面=服务端故障恢复态（autorun=false 滞留），真实链路难造：用 route 造快照、
	// 放行 resume POST 为 200，锁「入口出现 → 真发 POST → 释放后不留幽灵排队」。
	const sid = await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {activeId: string};
		return st.activeId;
	});
	let resumed = false;
	let phase: 'queued' | 'stuck' = 'queued';
	await page.route(
		url => url.pathname.endsWith('/inbox') && !url.pathname.includes('/resume'),
		async route => {
			if (route.request().method() !== 'GET') {
				await route.continue();
				return;
			}
			const item =
				phase === 'queued'
					? {
							queue_id: 'q-manual-1',
							text: 'MANUAL-RESUME-MARK',
							message_id: null,
							media_refs: [],
							queued_at: Date.now() / 1000,
							attempts: 0,
							state: 'queued',
							delivery_id: null,
						}
					: {
							queue_id: 'q-stuck-1',
							text: 'STUCK-MARK',
							message_id: null,
							media_refs: [],
							queued_at: Date.now() / 1000,
							attempts: 3,
							state: 'stuck',
							delivery_id: null,
						};
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					autorun: false,
					items: resumed ? [] : [item],
				}),
			});
		},
	);
	let resumeHits = 0;
	const resumeUrls: string[] = [];
	await page.route(
		url => url.pathname.includes('/inbox/') && url.pathname.endsWith('/resume'),
		async route => {
			resumeHits += 1;
			resumeUrls.push(route.request().url());
			resumed = true;
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: '{"ok":true}',
			});
		},
	);
	// 用真实快照入口注入滞留态（与轮询同一条 refreshInbox 通路）。
	await page.evaluate(async (id: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {
					getState: () => {refreshInbox: (sid: string) => Promise<boolean>};
				};
			}
		).__XEYO_CHAT__!.getState();
		await st.refreshInbox(id);
	}, sid);

	const resume = page.getByRole('button', {name: '继续投递'});
	await expect(resume).toBeVisible({timeout: 8_000});
	await resume.click();
	await expect.poll(() => resumeHits, {timeout: 8_000}).toBe(1);
	expect(resumeUrls[0]).toContain('/inbox/resume');
	await expect(page.locator(QUEUE_DOCK)).toHaveCount(0, {timeout: 10_000});

	// 相位二：stuck 单项 → 行内「重新投递」（per-item resume，queue_id 路径）。
	phase = 'stuck';
	resumed = false;
	await page.evaluate(async (id: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {
					getState: () => {refreshInbox: (sid: string) => Promise<boolean>};
				};
			}
		).__XEYO_CHAT__!.getState();
		await st.refreshInbox(id);
	}, sid);
	const retry = page.getByRole('button', {name: '重新投递'});
	await expect(retry).toBeVisible({timeout: 8_000});
	await retry.click();
	await expect.poll(() => resumeHits, {timeout: 8_000}).toBe(2);
	expect(resumeUrls[1]).toContain('/inbox/q-stuck-1/resume');
	await expect(page.locator(QUEUE_DOCK)).toHaveCount(0, {timeout: 10_000});
});

test('队列项「立即插入」：POST steer 后项转入投递中、按钮退场（DSH QueueAction:steer 对齐）', async ({page}) => {
	// 真实链路难造（需要回合正忙且有排队项），用 route 造快照 + 放行 steer POST，
	// 锁「入口出现 → 真发 POST → 释放后按钮退场（state 转 delivering）」。
	const sid = await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {activeId: string};
		return st.activeId;
	});
	let steered = false;
	const item = (state: 'queued' | 'delivering') => ({
		queue_id: 'q-steer-1',
		text: 'STEER-MARK',
		message_id: 'm-steer-1',
		media_refs: [],
		queued_at: Date.now() / 1000,
		attempts: 0,
		state,
		delivery_id: state === 'delivering' ? 'm-steer-1' : null,
	});
	await page.route(
		url => url.pathname.endsWith('/inbox') && !url.pathname.includes('/steer'),
		async route => {
			if (route.request().method() !== 'GET') {
				await route.continue();
				return;
			}
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					autorun: true,
					items: [item(steered ? 'delivering' : 'queued')],
				}),
			});
		},
	);
	const steerUrls: string[] = [];
	await page.route(
		url => url.pathname.includes('/inbox/') && url.pathname.endsWith('/steer'),
		async route => {
			expect(route.request().method()).toBe('POST');
			steerUrls.push(route.request().url());
			steered = true;
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: '{"ok":true}',
			});
		},
	);
	await page.evaluate(async (id: string) => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {
					getState: () => {refreshInbox: (sid: string) => Promise<boolean>};
				};
			}
		).__XEYO_CHAT__!.getState();
		await st.refreshInbox(id);
	}, sid);

	const steer = page.getByRole('button', {name: '立即插入'});
	await expect(steer).toBeVisible({timeout: 8_000});
	await steer.click();
	await expect.poll(() => steerUrls.length, {timeout: 8_000}).toBe(1);
	expect(steerUrls[0]).toContain('/inbox/q-steer-1/steer');
	// 释放后刷新快照为 delivering：入口退场（不再可再次插入），文案与文本仍在。
	await expect(page.getByRole('button', {name: '立即插入'})).toHaveCount(0, {
		timeout: 10_000,
	});
	await expect(page.getByText('STEER-MARK')).toBeVisible();
});

test('权限弹窗作答矩阵：允许 / 三选提醒 / Esc 拒绝，回执体逐相位对上', async ({page}) => {
	// 默认套件此前只有跑不了的 fullstack 档覆盖审批面板；这里用 route mock 回执，
	// 锁三条作答路径的 POST 体（request_id/approved/outcome 逐字段）。
	const sid = await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {activeId: string};
		return st.activeId;
	});
	const bodies: Array<Record<string, unknown>> = [];
	let failNext = false;
	await page.route('**/v1/permission/resolve', async route => {
		bodies.push(route.request().postDataJSON() as Record<string, unknown>);
		if (failNext) {
			failNext = false;
			await route.fulfill({
				status: 500,
				contentType: 'application/json',
				body: '{"ok":false,"reason":"boom","message":"boom"}',
			});
			return;
		}
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: '{"ok":true}',
		});
	});
	const inject = (info: Record<string, unknown>) =>
		page.evaluate(
			payload => {
				const st = (
					window as unknown as {
						__XEYO_CHAT__?: {
							getState: () => {
								setPendingPermission: (v: unknown) => void;
							};
						};
					}
				).__XEYO_CHAT__!.getState();
				st.setPendingPermission(payload);
			},
			{...info, sessionId: sid},
		);
	const dialog = page.getByRole('alertdialog');

	// 相位 A：普通确认 → 允许（无 outcome 字段）。
	await inject({
		requestId: 'perm-a',
		toolName: 'Write',
		prompt: '写入 /tmp/x',
		reason: '',
		intent: 'confirm',
		expiresAt: null,
	});
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByRole('button', {name: '允许'}).click();
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(bodies[0]).toEqual({
		request_id: 'perm-a',
		approved: true,
		actor: 'desktop',
		remember: false,
	});

	// 相位 B：三选冲突 → 提醒（approved:false + outcome:'remind'）。
	await inject({
		requestId: 'perm-b',
		toolName: 'Bash',
		prompt: '冲突命令',
		reason: '',
		intent: 'choice',
		choices: ['deny', 'remind', 'allow'],
		expiresAt: null,
	});
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByRole('button', {name: '提醒'}).click();
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(bodies[1]).toEqual({
		request_id: 'perm-b',
		approved: false,
		actor: 'desktop',
		remember: false,
		outcome: 'remind',
	});

	// 相位 C：Esc = 取消（deny 语义）。
	await inject({
		requestId: 'perm-c',
		toolName: 'Write',
		prompt: '写入 /tmp/y',
		reason: '',
		intent: 'confirm',
		expiresAt: null,
	});
	await expect(dialog).toBeVisible({timeout: 5_000});
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(bodies[2]).toEqual({
		request_id: 'perm-c',
		approved: false,
		actor: 'desktop',
		remember: false,
		outcome: 'deny',
	});

	// 相位 D：回执失败（500）→ 面板必须留着供重试（先发送再清状态）；再点成功才退场。
	failNext = true;
	await inject({
		requestId: 'perm-d',
		toolName: 'Write',
		prompt: '写入 /tmp/z',
		reason: '',
		intent: 'confirm',
		expiresAt: null,
	});
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByRole('button', {name: '允许'}).click();
	await expect(dialog).toBeVisible({timeout: 5_000});
	await expect(page.getByText(/boom|重试|失败/).first()).toBeVisible({timeout: 5_000});
	await dialog.getByRole('button', {name: '允许'}).click();
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(bodies[3]?.request_id).toBe('perm-d');
	expect(bodies[4]?.request_id).toBe('perm-d');
});

test('计划确认面板：允许执行 / 拒绝，回执体与 URL 逐相位对上', async ({page}) => {
	// 默认套件此前对 PlanDialog 零直接覆盖（同样只有 fullstack 档）。
	const sid = await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {activeId: string};
		return st.activeId;
	});
	const hits: Array<{url: string; body: Record<string, unknown>}> = [];
	await page.route('**/v1/plan/*/approve', async route => {
		hits.push({
			url: route.request().url(),
			body: route.request().postDataJSON() as Record<string, unknown>,
		});
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: '{"ok":true}',
		});
	});
	const inject = (requestId: string, plan: string) =>
		page.evaluate(
			payload => {
				const st = (
					window as unknown as {
						__XEYO_CHAT__?: {
							getState: () => {setPendingPlan: (v: unknown) => void};
						};
					}
				).__XEYO_CHAT__!.getState();
				st.setPendingPlan(payload);
			},
			{requestId, plan, sessionId: sid, turnId: requestId, expiresAt: null},
		);
	const dialog = page.getByRole('alertdialog', {name: 'Plan 确认'});

	await inject('plan-a', 'PLAN-TEXT-MARK');
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByText('PLAN-TEXT-MARK').waitFor({state: 'visible', timeout: 5_000});
	await dialog.getByRole('button', {name: '允许执行'}).click();
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(hits[0]?.url).toContain('/v1/plan/plan-a/approve');
	expect(hits[0]?.body).toEqual({approved: true, actor: 'desktop'});

	await inject('plan-b', 'PLAN-REJECT-MARK');
	await expect(dialog).toBeVisible({timeout: 5_000});
	await dialog.getByRole('button', {name: '拒绝'}).click();
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	expect(hits[1]?.url).toContain('/v1/plan/plan-b/approve');
	expect(hits[1]?.body).toEqual({approved: false, actor: 'desktop'});
});

test('斜杠/@ 弹层：Esc 只关弹层——草稿一字不动、不发送', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);

	// 斜杠形态。（注意：全局 `[aria-selected]` 还会命中工作区导航的选中 tab，
	// 计数断言必须限定在输入弹层的 listbox 内。）
	const popupSel = () => page.locator('[role="listbox"] [aria-selected="true"]');
	await composer.click();
	await composer.pressSequentially('/goa');
	await expect(popupSel().first()).toContainText('goal', {timeout: 5_000});
	await composer.press('Escape');
	await expect(popupSel()).toHaveCount(0, {timeout: 5_000});
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('/goa');

	// @ 形态（种一个能命中的文件；无候选时弹层按设计不出现）。
	fs.writeFileSync(path.join(workspaceDir, 'at-probe.txt'), 'x');
	await composer.fill('');
	await composer.pressSequentially('@at');
	await expect(popupSel().first()).toBeVisible({timeout: 8_000});
	await composer.press('Escape');
	await expect(popupSel()).toHaveCount(0, {timeout: 5_000});
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('@at');

	// 关弹层不许顺带把草稿发出去。
	await page.waitForTimeout(600);
	expect(submits().filter(h => h.includes('/v1/chat'))).toEqual([]);
});

test('终端面板：命令真执行到回显，↑ 历史可召回（此前零 e2e）', async ({page}) => {
	await page.getByRole('button', {name: '应用菜单'}).click();
	await page.getByRole('menuitem', {name: '终端'}).click();
	const input = page.getByLabel('终端命令');
	await expect(input).toBeVisible({timeout: 10_000});

	await input.click();
	await input.fill('echo TERM-MARK');
	await input.press('Enter');
	// 回显行（PS 提示行含同串，取 exact 的输出行）。
	await expect(page.getByText('TERM-MARK', {exact: true}).first()).toBeVisible({
		timeout: 20_000,
	});
	await expect(page.getByText(/退出码 0/).first()).toBeVisible({timeout: 10_000});

	// ↑ 历史召回（面板自己的一行输入史）。
	await input.click();
	await input.press('ArrowUp');
	await expect.poll(() => input.inputValue(), {timeout: 5_000}).toBe('echo TERM-MARK');
});

test('浏览器预览地址栏：输入 URL 回车真挂 iframe（此前零 e2e）', async ({page}) => {
	await page.getByRole('button', {name: '应用菜单'}).click();
	await page.getByRole('menuitem', {name: '浏览器预览'}).click();
	const bar = page.getByLabel('预览地址');
	await expect(bar).toBeVisible({timeout: 10_000});

	// 用前端同源 /health（vite 代理到后端，返回 JSON、可被 frame）。
	const url = `${new URL(page.url()).origin}/health`;
	await bar.click();
	await bar.fill(url);
	await bar.press('Enter');

	const frame = page.locator('iframe').first();
	await expect(frame).toBeVisible({timeout: 10_000});
	await expect.poll(() => frame.getAttribute('src'), {timeout: 5_000}).toBe(url);
	// 有 url 后外部打开入口可用。
	await expect(page.getByRole('button', {name: '在系统浏览器打开'})).toBeEnabled({
		timeout: 5_000,
	});
});

test('图片 chip 点开原图查看器：Esc 关闭（此前零 e2e）', async ({page}) => {
	const pngPath = writePixel(workspaceDir, 'img-probe.png');
	const composer = page.getByLabel(COMPOSER);
	await page.locator('.xy-composer-surface input[type=file]').setInputFiles(pngPath);
	const view = page.getByRole('button', {name: /查看原图：img-probe\.png/});
	await expect(view).toBeVisible({timeout: 15_000});

	await view.click();
	const dialog = page.getByRole('dialog', {name: /原图预览：img-probe\.png/});
	await expect(dialog).toBeVisible({timeout: 5_000});
	await expect(dialog.getByRole('button', {name: '放大图片'})).toBeVisible();

	// Esc（escStack 层）关查看器；输入面不受影响。
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0, {timeout: 5_000});
	await expect(composer).toBeVisible();
});

test('沉浸待办：只读镜像模型快照，无编辑入口（F6 统一只读；口径更新）', async ({page}) => {
	await page.getByRole('button', {name: '应用菜单'}).click();
	await page.getByRole('menuitem', {name: '沉浸模式'}).click();
	const panel = page.getByLabel('沉浸模式侧板');
	await expect(panel).toBeVisible({timeout: 8_000});

	// 只读契约①：新增输入已删（旧口径「回车添加并清空」随 F6 统一只读写坏）。
	await expect(page.getByPlaceholder('添加今日待办…')).toHaveCount(0);

	// 注入模型快照（等价于 TodoWrite 事件落库后的镜像态；写入键与生产一致）。
	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {
					getState: () => {
						activeId: string | null;
						sessionTodosById?: Record<string, unknown>;
					};
					setState: (p: {sessionTodosById: Record<string, unknown>}) => void;
				};
			}
		).__XEYO_CHAT__!;
		const {activeId, sessionTodosById} = st.getState();
		if (!activeId) throw new Error('no active session');
		st.setState({
			sessionTodosById: {
				...(sessionTodosById ?? {}),
				[activeId]: {
					id: 'e2e-todo-readonly',
					running: false,
					todos: [
						{content: 'MODEL-TODO-A', status: 'completed', activeForm: ''},
						{content: 'MODEL-TODO-B', status: 'pending', activeForm: ''},
					],
				},
			},
		});
	});
	await expect(panel.getByText('MODEL-TODO-A')).toBeVisible({timeout: 5_000});
	await expect(panel.getByText('MODEL-TODO-B')).toBeVisible();
	await expect(panel.getByText('1/2')).toBeVisible();

	// 只读契约②：行不可交互——点击不改状态（旧实现点击勾选 ⇒ 计数跳到 2/2）。
	await expect(panel.locator('button', {hasText: 'MODEL-TODO-B'})).toHaveCount(0);
	await panel.getByText('MODEL-TODO-B').click();
	await expect(panel.getByText('1/2')).toBeVisible({timeout: 3_000});
});

test('双枪 Enter：同一草稿连按两次只发一条', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('DOUBLE-ENTER-MARK');
	await composer.press('Enter');
	await composer.press('Enter');
	await page.waitForTimeout(1_500);
	expect(submits().filter(hit => hit.includes('/v1/chat')).length).toBe(1);
	const v = await view(page);
	expect(v.messages.filter(m => m.text === 'DOUBLE-ENTER-MARK').length).toBe(1);
});

test('弹层 Tab 补全：选中当前高亮行并回填（不提交、不搬焦点）', async ({page}) => {
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	// "/goa" 只命中命令 /goal（技能 go-probe 不含 goa）⇒ 首行恒为 /goal。
	await composer.pressSequentially('/goa');
	await expect(page.locator('[aria-selected="true"]').first()).toContainText('goal');
	await composer.press('Tab');
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('/goal ');
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
});

test('文件附件上传中按 Enter：被挡要说原因，上传完成后可发且正文带上文件', async ({
	page,
}) => {
	const txtPath = path.join(workspaceDir, 'note-upload.txt');
	fs.writeFileSync(txtPath, 'UPLOAD-FILE-BODY\n');
	// 拖慢文件上传（非图片在挑选期就上传）：制造"上传中"窗口。
	await page.route('**/v1/files', async route => {
		await new Promise(resolve => setTimeout(resolve, 1_500));
		await route.continue();
	});
	const submits = watchSubmits(page);
	const composer = page.getByLabel(COMPOSER);
	await page.locator('.xy-composer-surface input[type=file]').setInputFiles(txtPath);
	// 上传在飞：立刻 Enter 必须被挡且说原因，不许静默丢。
	await composer.click();
	await composer.fill('FILE-UPLOAD-MARK');
	await composer.press('Enter');
	await expect(page.getByText('附件仍在上传，请完成后发送').first()).toBeVisible({
		timeout: 5_000,
	});
	expect(submits().filter(hit => hit.includes('/v1/chat'))).toEqual([]);
	// 上传落地（chip 出现）后再发：正文里带文件内容（buildPayload 的内联格式）。
	await expect(page.getByRole('button', {name: /移除 note-upload\.txt/})).toBeVisible({
		timeout: 15_000,
	});
	await composer.click();
	await composer.press('Enter');
	const v = await waitForView(
		page,
		v =>
			v.messages.some(
				m => m.role === 'assistant' && m.text.includes('UPLOAD-FILE-BODY'),
			),
		45_000,
	);
	expect(
		v.messages.some(m => m.role === 'user' && m.text.includes('UPLOAD-FILE-BODY')),
	).toBe(true);
	// 受理后草稿让位（清空），不残留已发文本。
	expect(await composer.inputValue()).toBe('');
});

test('新建会话/分叉后输入框自动就绪：不点也能直接打字', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	const focused = () =>
		page.evaluate(() => {
			const el = document.activeElement;
			return (
				el instanceof HTMLTextAreaElement &&
				el.getAttribute('aria-label') === '消息输入'
			);
		});
	// 顶栏「新对话」（真 UI）：焦点必须落在输入框。
	await page.getByRole('button', {name: '新对话'}).first().click();
	await expect.poll(focused, {timeout: 5_000}).toBe(true);
	// 焦点就绪与首键之间留一拍：点「新对话」到建的会话装载/封面退场是异步的，
	// 立刻 typing 偶发被吞首字符（全量序下实测 "F"→"OCUS-…"）。
	await page.waitForTimeout(200);
	await page.keyboard.type('FOCUS-AFTER-NEW');
	await expect
		.poll(() => composer.inputValue(), {timeout: 5_000})
		.toBe('FOCUS-AFTER-NEW');
	await composer.fill('');
	// 分叉：同样就绪（分叉=要接着聊）。
	await openTurn(page, 'ok: focus-fork');
	await page.locator('li').filter({hasText: 'focus-fork'}).first().hover();
	await page.getByRole('button', {name: '对话操作'}).first().click();
	await page.getByRole('menuitem', {name: '分叉对话'}).click();
	await expect.poll(focused, {timeout: 8_000}).toBe(true);
	await page.waitForTimeout(200);
	await page.keyboard.type('FOCUS-AFTER-FORK');
	await expect
		.poll(() => composer.inputValue(), {timeout: 5_000})
		.toBe('FOCUS-AFTER-FORK');
});

test('编辑消息：Esc 取消编辑，消息与列表不变、无请求', async ({page}) => {
	await openTurn(page, 'ok: edit-me');
	const submits = watchSubmits(page);
	await page
		.getByRole('button', {name: '编辑这条消息'})
		.filter({hasText: 'ok: edit-me'})
		.first()
		.click();
	const editor = page.getByLabel('编辑历史消息');
	await expect(editor).toBeVisible({timeout: 5_000});
	await editor.fill('EDITED-TEXT-SHOULD-NOT-COMMIT');
	await editor.press('Escape');
	await expect(editor).toHaveCount(0, {timeout: 5_000});
	// 取消=什么都没发生：原文在、改文不在、回溯弹窗不开、无提交类请求。
	await expect(page.getByText('ok: edit-me').first()).toBeVisible();
	await expect(page.getByText('EDITED-TEXT-SHOULD-NOT-COMMIT')).toHaveCount(0);
	await expect(page.locator('dialog.xy-rewind-dialog')).toHaveCount(0);
	expect(submits()).toEqual([]);
});

test('编辑消息：提交打开回溯弹窗（跳过 preview），取消弹窗后消息不变', async ({
	page,
}) => {
	await openTurn(page, 'ok: preview-me');
	await page
		.getByRole('button', {name: '编辑这条消息'})
		.filter({hasText: 'ok: preview-me'})
		.first()
		.click();
	const editor = page.getByLabel('编辑历史消息');
	await expect(editor).toBeVisible({timeout: 5_000});
	await editor.fill('PREVIEW-EDITED');
	await editor.press('Enter');
	const dialog = page.locator('dialog.xy-rewind-dialog');
	await expect(dialog).toBeVisible({timeout: 10_000});
	// 编辑器就位后应已退场（编辑态不悬留）。
	await expect(editor).toHaveCount(0);
	// 弹窗取消=不截断：原对话两条都在。
	await dialog.getByRole('button', {name: '取消'}).click();
	await expect(dialog).toHaveCount(0);
	await expect(page.getByText('ok: preview-me').first()).toBeVisible();
	await expect(page.getByText(/ok: ok: preview-me/).first()).toBeVisible();
});

test('流式中消息不可编辑：入口退场（不许开出打不了字的死框），收尾后回来', async ({
	page,
}) => {
	await openTurn(page, 'ok: before-busy');
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	// 流式中：编辑入口必须退场（开出来的框是 disabled 的，等于死框）。
	await expect(page.getByRole('button', {name: '编辑这条消息'})).toHaveCount(0);
	await expect
		.poll(
			() => view(page).then(v => v.streaming === false && v.draining === false),
			{timeout: 60_000},
		)
		.toBe(true);
	await expect(page.getByRole('button', {name: '编辑这条消息'}).first()).toBeVisible({
		timeout: 10_000,
	});
});

test('「+」快捷菜单：Esc 关不丢草稿、选中项即生效并关单', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('KEEP-DRAFT');
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	const menu = page.getByRole('menu');
	await expect(menu).toBeVisible({timeout: 5_000});
	// Esc 关闭（escStack 顶层）；草稿一个字不动。
	await page.keyboard.press('Escape');
	await expect(menu).toHaveCount(0, {timeout: 5_000});
	expect(await composer.inputValue()).toBe('KEEP-DRAFT');
	// 再开 → 选 Multi-Agent：菜单关、chip 出现；chip 退出后消失。
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	await expect(menu).toBeVisible({timeout: 5_000});
	await menu.getByRole('menuitemradio', {name: /Multi-Agent/}).click();
	await expect(menu).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByRole('button', {name: '退出 Multi-Agent'})).toBeVisible({
		timeout: 5_000,
	});
	await page.getByRole('button', {name: '退出 Multi-Agent'}).click();
	await expect(page.getByRole('button', {name: '退出 Multi-Agent'})).toHaveCount(0, {
		timeout: 5_000,
	});
	// Files 入口：真的打开系统文件选择器（多选）。
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	const [chooser] = await Promise.all([
		page.waitForEvent('filechooser'),
		menu.getByRole('menuitem', {name: /Files/}).click(),
	]);
	expect(chooser.isMultiple()).toBe(true);
	// MCP 入口：面板开、关闭键关。
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	await menu.getByRole('menuitem', {name: /MCP/}).click();
	await expect(page.getByLabel('关闭 MCP 面板')).toBeVisible({timeout: 5_000});
	await page.getByLabel('关闭 MCP 面板').click();
	await expect(page.getByLabel('关闭 MCP 面板')).toHaveCount(0, {timeout: 5_000});
	// 全程没有把草稿当消息发出去。
	expect((await view(page)).messages.some(m => m.text === 'KEEP-DRAFT')).toBe(false);
});

test('侧栏重命名：Esc 不改名、组词 Enter 不提交半截、Enter 提交新名', async ({page}) => {
	// 三点按钮是 group-hover 显隐（invisible+pointer-events:none）⇒ 先 hover 会话行；
	// 注意「新对话」文本有两处（顶栏 Ctrl+N 与会话行），必须悬停会话行 li。
	const openSessionMenu = async () => {
		await page.locator('li').filter({hasText: '新对话'}).first().hover();
		await page.getByRole('button', {name: '对话操作'}).first().click();
	};
	await openSessionMenu();
	await page.getByRole('menuitem', {name: '重命名对话'}).click();
	const input = page.locator('dialog input.xy-id-input');
	await expect(input).toBeVisible({timeout: 5_000});
	await input.fill('ESC-SHOULD-NOT-SAVE');
	await page.keyboard.press('Escape');
	await expect(page.locator('dialog')).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByText('ESC-SHOULD-NOT-SAVE')).toHaveCount(0);

	// 组词中的 Enter 属于输入法：不提交、不关弹窗（promptDialog isImeComposing 契约）。
	await openSessionMenu();
	await page.getByRole('menuitem', {name: '重命名对话'}).click();
	const inputIme = page.locator('dialog input.xy-id-input');
	await expect(inputIme).toBeVisible({timeout: 5_000});
	await inputIme.fill('IME-HALF');
	await inputIme.dispatchEvent('keydown', {
		key: 'Enter',
		isComposing: true,
		bubbles: true,
		cancelable: true,
	});
	await expect(page.locator('dialog')).toHaveCount(1, {timeout: 2_000});
	await expect(inputIme).toHaveValue('IME-HALF');
	await page.keyboard.press('Escape');
	await expect(page.locator('dialog')).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByText('IME-HALF')).toHaveCount(0);

	await openSessionMenu();
	await page.getByRole('menuitem', {name: '重命名对话'}).click();
	const input2 = page.locator('dialog input.xy-id-input');
	await expect(input2).toBeVisible({timeout: 5_000});
	await input2.fill('RENAMED-BY-PROBE');
	await input2.press('Enter');
	await expect(page.locator('dialog')).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByText('RENAMED-BY-PROBE').first()).toBeVisible({timeout: 8_000});
});

test('分叉会话：新会话接管输入面、历史回填、草稿不串', async ({page}) => {
	await openTurn(page, 'ok: fork-me');
	const originalSid = (await view(page)).sid;
	// 回合结束后会话标题已被服务端改成首条用户消息 ⇒ 按真标题悬停会话行。
	await page.locator('li').filter({hasText: 'fork-me'}).first().hover();
	await page.getByRole('button', {name: '对话操作'}).first().click();
	await page.getByRole('menuitem', {name: '分叉对话'}).click();
	await expect.poll(() => view(page).then(v => v.sid), {timeout: 10_000}).not.toBe(
		originalSid,
	);
	// 分叉带历史（服务端回填）；输入框为空白且可用。
	const forked = await waitForView(
		page,
		v => v.messages.some(m => m.text.includes('fork-me')),
		20_000,
	);
	expect(forked.sid).not.toBe(originalSid);
	const composer = page.getByLabel(COMPOSER);
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('');
	await composer.fill('FORK-DRAFT');
	expect(await composer.inputValue()).toBe('FORK-DRAFT');
	// 切回原会话：分叉的草稿不许串过来。
	await selectSessionById(page, originalSid);
	await expect.poll(() => view(page).then(v => v.sid), {timeout: 8_000}).toBe(originalSid);
	await expect.poll(() => composer.inputValue(), {timeout: 5_000}).toBe('');
});

test('长文本输入：展开钮出现、展开/收起往返、长文照常发送', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	const expandBtn = page.getByRole('button', {name: '展开输入框'});
	const collapseBtn = page.getByRole('button', {name: '收起输入框'});
	const longText = Array.from({length: 14}, (_, i) => `第 ${i + 1} 行`).join('\n');

	await composer.click();
	await composer.fill(longText);
	// 内容超过 maxPx(120px) ⇒ capped：展开按钮出现、高度封顶。
	await expect(expandBtn).toBeVisible({timeout: 5_000});
	const cappedH = await composer.evaluate(el => (el as HTMLTextAreaElement).clientHeight);
	expect(cappedH).toBeLessThanOrEqual(125);

	await expandBtn.click();
	await expect(collapseBtn).toBeVisible({timeout: 5_000});
	// 展开高度带 transition-[height] 200ms：轮询等动画落定，别拿同帧读数当终值。
	await expect
		.poll(() => composer.evaluate(el => (el as HTMLTextAreaElement).clientHeight), {
			timeout: 3_000,
		})
		.toBeGreaterThanOrEqual(cappedH + 100);

	// Esc 收起（空闲态只有展开层）：高度回落、草稿原样。
	await page.keyboard.press('Escape');
	await expect(expandBtn).toBeVisible({timeout: 5_000});
	await expect
		.poll(() => composer.evaluate(el => (el as HTMLTextAreaElement).clientHeight))
		.toBeLessThanOrEqual(125);
	expect(await composer.inputValue()).toBe(longText);

	// 长文照常发送（2000 字上限只属于排队路径，直发不受影响）。
	await composer.press('Enter');
	await waitForView(
		page,
		viewState =>
			viewState.messages.some(m => m.role === 'user' && m.text === longText) &&
			viewState.messages.some(
				m => m.role === 'assistant' && m.text.includes('第 14 行'),
			),
		30_000,
	);
});

test('流式中长文本展开：Esc 先收起不打断回合，再 Esc 才停', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	const expandBtn = page.getByRole('button', {name: '展开输入框'});
	const collapseBtn = page.getByRole('button', {name: '收起输入框'});
	const longText = Array.from({length: 14}, (_, i) => `压住 ${i + 1}`).join('\n');

	await startBusyTurn(page, '长文展开档 ' + BUSY_PAD);
	expect((await view(page)).streaming).toBe(true);

	await composer.fill(longText);
	await expect(expandBtn).toBeVisible({timeout: 5_000});
	await expandBtn.click();
	await expect(collapseBtn).toBeVisible({timeout: 5_000});
	// escStack 层在 effect 里入栈：等一帧再按。
	await page.waitForTimeout(200);

	await page.keyboard.press('Escape');
	await expect(expandBtn).toBeVisible({timeout: 5_000}); // 收起层先消费
	expect((await view(page)).streaming).toBe(true); // 回合未被打断

	await page.keyboard.press('Escape');
	await expect
		.poll(() => view(page).then(v => v.streaming === false), {timeout: 30_000})
		.toBe(true);
});

test('草稿跨刷新存活：reload 后回到原会话，草稿原样恢复', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('RELOAD-KEEPS-DRAFT');
	// 持久化防抖 250ms：给 localStorage 落盘留足窗口。
	await page.waitForTimeout(400);
	// 刷新哨兵：只有真发生了导航，哨兵才会消失（防 reload 静默 no-op 的假绿）。
	await page.evaluate(() => {
		(window as unknown as {__reloadSentinel?: boolean}).__reloadSentinel = true;
	});

	await page.reload();
	await page.getByLabel(COMPOSER).waitFor({state: 'visible', timeout: 15_000});
	expect(
		await page.evaluate(
			() => (window as unknown as {__reloadSentinel?: boolean}).__reloadSentinel,
		),
	).toBeUndefined();
	// 真集成链：localStorage → 启动 → 路由恢复原会话 → 草稿回填输入框。
	await expect
		.poll(() => page.getByLabel(COMPOSER).inputValue(), {timeout: 10_000})
		.toBe('RELOAD-KEEPS-DRAFT');
});

test('助手提问面板：点选即提交；失败保留可重试、已别处答复按信息档收起', async ({page}) => {
	const sent: Array<{request_id: string; answer: string}> = [];
	let mode: 'ok' | 'fail' | 'already' = 'ok';
	await page.route('**/v1/ask/resolve', route => {
		const body = route.request().postDataJSON() as {
			request_id: string;
			answer: string;
		};
		sent.push({request_id: body.request_id, answer: body.answer});
		if (mode === 'fail') {
			return route.fulfill({
				status: 200,
				json: {ok: false, reason: 'engine_busy'},
			});
		}
		if (mode === 'already') {
			return route.fulfill({
				status: 200,
				json: {ok: false, reason: 'already_resolved'},
			});
		}
		return route.fulfill({status: 200, json: {ok: true}});
	});
	const inject = (requestId: string) =>
		page.evaluate(rid => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
				}
			).__XEYO_CHAT__!.getState() as unknown as {
				activeId: string;
				setPendingAsk: (v: unknown) => void;
			};
			st.setPendingAsk({
				requestId: rid,
				question: '选一个',
				options: ['选项甲', '选项乙'],
				questions: [],
				sessionId: st.activeId,
			});
		}, requestId);

	// ① 成功：点选项即提交并收起面板，提交体带对 id 与所选文本。
	await inject('ask-probe-1');
	await expect(page.getByText('助手提问')).toBeVisible({timeout: 5_000});
	await page.getByRole('button', {name: '选项甲'}).click();
	await expect(page.getByText('助手提问')).toHaveCount(0, {timeout: 5_000});
	expect(sent.at(-1)).toEqual({request_id: 'ask-probe-1', answer: '选项甲'});

	// ② 失败：面板与已选内容保留可重试；给出失败说法。
	mode = 'fail';
	await inject('ask-probe-2');
	await expect(page.getByText('助手提问')).toBeVisible({timeout: 5_000});
	await page.getByRole('button', {name: '选项甲'}).click();
	await expect.poll(() => sent.length, {timeout: 5_000}).toBe(2);
	await expect(page.getByText('助手提问')).toBeVisible({timeout: 5_000});
	await expect(page.getByText(/提交未生效/).first()).toBeVisible({timeout: 5_000});
	// 重试换一个选项：这次通了 ⇒ 面板收起，提交体是重试后的答案。
	mode = 'ok';
	await page.getByRole('button', {name: '选项乙'}).click();
	await expect(page.getByText('助手提问')).toHaveCount(0, {timeout: 5_000});
	expect(sent.at(-1)).toEqual({request_id: 'ask-probe-2', answer: '选项乙'});

	// ③ 已在别处答复（info 档）：不是失败，面板也应收起。
	mode = 'already';
	await inject('ask-probe-3');
	await expect(page.getByText('助手提问')).toBeVisible({timeout: 5_000});
	await page.getByRole('button', {name: '选项甲'}).click();
	await expect(page.getByText('助手提问')).toHaveCount(0, {timeout: 5_000});
});

test('助手提问向导：多题翻页/自由文本/跳过，答案 JSON 逐字段对上模型侧', async ({page}) => {
	const sent: Array<{request_id: string; answer: string}> = [];
	await page.route('**/v1/ask/resolve', route => {
		const body = route.request().postDataJSON() as {
			request_id: string;
			answer: string;
		};
		sent.push({request_id: body.request_id, answer: body.answer});
		return route.fulfill({status: 200, json: {ok: true}});
	});
	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			activeId: string;
			setPendingAsk: (v: unknown) => void;
		};
		st.setPendingAsk({
			requestId: 'ask-wizard-1',
			question: '',
			options: [],
			questions: [
				{
					id: 'q1',
					question: '先选还是先写？',
					options: [{label: '选项甲'}, {label: '选项乙'}],
					multiSelect: false,
				},
				{
					id: 'q2',
					question: '多选两格',
					options: [{label: '勾A'}, {label: '勾B'}],
					multiSelect: true,
				},
				{id: 'q3', question: '自由作答或跳过', options: []},
			],
			sessionId: st.activeId,
		});
	});
	await expect(page.getByText('助手提问')).toBeVisible({timeout: 5_000});

	// q1：单选填自由文本 = 以文本作答（dsh 口径），Enter 进下一题。
	await expect(page.getByText('1 / 3')).toBeVisible({timeout: 5_000});
	await page.locator('.xy-ask-custom-input').fill('手工答');
	await page.locator('.xy-ask-custom-input').press('Enter');
	await expect(page.getByText('2 / 3')).toBeVisible({timeout: 5_000});
	// q2：多选勾两项，点「下一题」提交按钮（注意分页器的同名 aria-label，用类名定位）。
	await page.getByRole('checkbox', {name: '勾A'}).click();
	await page.getByRole('checkbox', {name: '勾B'}).click();
	await page.locator('button.xy-ask-next').click();
	await expect(page.getByText('3 / 3')).toBeVisible({timeout: 5_000});
	// q3：末题跳过 ⇒ 整组提交。
	await page.getByRole('button', {name: '跳过'}).click();
	await expect(page.getByText('助手提问')).toHaveCount(0, {timeout: 5_000});

	expect(sent.length).toBe(1);
	expect(sent[0].request_id).toBe('ask-wizard-1');
	const parsed = JSON.parse(sent[0].answer) as {
		answers: Array<Record<string, unknown>>;
	};
	expect(parsed.answers).toEqual([
		{id: 'q1', selected: [], custom: '手工答'},
		{id: 'q2', selected: ['勾A', '勾B']},
		{id: 'q3', selected: []},
	]);
});

test('沉浸模式的真实入口：菜单项可用，且不该标着「Esc」假快捷键', async ({page}) => {
	// 旧探针走 store 直翻；这里走真入口（应用菜单）并锁住提示不说谎。
	await page.getByRole('button', {name: '应用菜单'}).click();
	const item = page.getByRole('menuitem', {name: /沉浸模式/});
	await expect(item).toBeVisible({timeout: 5_000});
	// 进入方向不存在任何键盘键（Esc 不会进入沉浸；Ctrl+B 只切沉浸内的侧板）——
	// 挂在菜单项上的 Esc 提示会把用户引到按了没反应。
	expect(await item.textContent()).not.toContain('Esc');
	await item.click();
	await expect(page.locator('.xy-immersive')).toBeVisible({timeout: 5_000});
	// 右板默认开着：Esc #1 关右板；Esc #2 退沉浸（既有逐层语义）。
	await page.keyboard.press('Escape');
	await expect(page.getByLabel('沉浸模式侧板')).toHaveCount(0, {timeout: 5_000});
	await page.keyboard.press('Escape');
	await expect(page.locator('.xy-immersive')).toHaveCount(0, {timeout: 5_000});
});

test('沉浸模式进出：静音期间续写的草稿必须回到输入框（双 Composer 同步）', async ({page}) => {
	const base = page.getByLabel(COMPOSER);
	await base.click();
	await base.fill('BASE-TEXT');
	await page.waitForTimeout(400);
	// 真入口是「应用菜单 → 沉浸」；此处直接翻转 store 字段（同一个 store，等价于入口效果）。
	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			setImmersive: (v: boolean) => void;
		};
		st.setImmersive(true);
	});
	// 沉浸层里的 Composer 是第二个实例：进场必须装载同一份共享草稿。
	const imm = page.locator('.xy-immersive textarea');
	await expect(imm).toBeVisible({timeout: 5_000});
	await expect.poll(() => imm.inputValue(), {timeout: 5_000}).toBe('BASE-TEXT');
	await imm.fill('IMM-TEXT');

	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			setImmersive: (v: boolean) => void;
		};
		st.setImmersive(false);
	});
	// 退出后基础输入框必须回到共享草稿的最新版；显示陈旧值 = 随后任一敲键都会把
	// 沉浸里续写的内容整段顶掉（静默丢字）。
	await expect
		.poll(() => page.getByLabel(COMPOSER).inputValue(), {timeout: 5_000})
		.toBe('IMM-TEXT');
});

test('沉浸模式里编辑消息：Esc 依层退出（编辑 → 面板 → 沉浸），一键只关一层', async ({page}) => {
	await openTurn(page, 'ok: imm-edit');
	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {
			setImmersive: (v: boolean) => void;
		};
		st.setImmersive(true);
	});
	const scope = page.locator('.xy-immersive');
	await expect(scope.getByText('imm-edit').first()).toBeVisible({timeout: 5_000});

	const bubble = scope
		.getByRole('button', {name: '编辑这条消息'})
		.filter({hasText: 'imm-edit'})
		.first();
	await bubble.click();
	const editor = scope.getByLabel('编辑历史消息');
	await expect(editor).toBeVisible({timeout: 5_000});

	// Esc #1：只退编辑；面板与沉浸层都不许被连带关掉（Esc 归属最上层可关闭物）。
	await page.keyboard.press('Escape');
	await expect(editor).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByLabel('沉浸模式侧板')).toBeVisible({timeout: 2_000});
	await expect(page.locator('.xy-immersive')).toHaveCount(1);

	// Esc #2：关面板；沉浸层仍在。（编辑层由 effect 清理弹出，给一帧落定——
	// 被动 effect 清理晚于 DOM 移除，落到同帧的第二次 Esc 会被残留层吃掉。）
	await page.waitForTimeout(300);
	await page.keyboard.press('Escape');
	await expect(page.getByLabel('沉浸模式侧板')).toHaveCount(0, {timeout: 5_000});
	await expect(page.locator('.xy-immersive')).toHaveCount(1);

	// Esc #3：退沉浸。
	await page.keyboard.press('Escape');
	await expect(page.locator('.xy-immersive')).toHaveCount(0, {timeout: 5_000});
});

test('流式中打开原生弹窗（重命名）：Esc 关弹窗，不许把回合停掉', async ({page}) => {
	await startBusyTurn(page, '压住 ' + BUSY_PAD);
	// 侧栏会话菜单 → 重命名对话（原生 dialog 弹窗）。
	// 忙回合后会话标题即该消息（不再是「新对话」），按前缀悬停会话行。
	await page.locator('li').filter({hasText: '压住'}).first().hover();
	await page.getByRole('button', {name: '对话操作'}).first().click();
	await page.getByRole('menuitem', {name: '重命名对话'}).click();
	await expect(page.locator('dialog input.xy-id-input')).toBeVisible({timeout: 5_000});

	await page.keyboard.press('Escape');
	// Esc 归最上层可关闭物：弹窗要关、回合照跑（composer-stop 层不许抢 Esc）。
	await expect(page.locator('dialog')).toHaveCount(0, {timeout: 5_000});
	expect((await view(page)).streaming).toBe(true);
});

test('流式中活动搜索弹层：Esc 只关弹层，不许把回合停掉', async ({page}) => {
	await startBusyTurn(page, '压住 ' + BUSY_PAD);
	await page.getByLabel('搜索并跳转活动记录').click();
	const picker = page.getByLabel('定位活动记录');
	await expect(picker).toBeVisible({timeout: 5_000});

	await page.keyboard.press('Escape');
	await expect(picker).toHaveCount(0, {timeout: 5_000});
	expect((await view(page)).streaming).toBe(true);
});

test('发送后 Ctrl+Z：已发送的正文不许复活（DSH 同规）', async ({page}) => {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	// 真实键入（不要用 fill：程序性赋值可能不进原生撤销栈，会测出假绿）。
	await composer.pressSequentially('UNDO-TEST-1234', {delay: 20});
	await composer.press('Enter');
	await waitForView(
		page,
		v => v.messages.some(m => m.role === 'user' && m.text === 'UNDO-TEST-1234'),
		30_000,
	);
	await waitForView(page, v => v.streaming === false && v.draining === false, 60_000);

	await composer.click();
	await page.keyboard.press('Control+z');
	await page.waitForTimeout(300);
	// 复活 = 一次误 Enter 就会把同一句话再发一遍（DSH 明确防这手）。
	expect(await composer.inputValue()).toBe('');
});

test('沉浸模式模型弹层：外点与 Esc 都能关，Esc 不许把侧板带走', async ({page}) => {
	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {setImmersive: (v: boolean) => void};
		st.setImmersive(true);
	});
	const scope = page.locator('.xy-immersive');
	const btn = scope.getByRole('button').filter({hasText: '✦'});
	const flyout = page.locator('#immersive-model-picker');
	await expect(btn).toBeVisible({timeout: 5_000});

	// 外点关闭：点输入区即关。
	await btn.click();
	await expect(flyout).toBeVisible({timeout: 5_000});
	await scope.locator('textarea').first().click();
	await expect(flyout).toHaveCount(0, {timeout: 5_000});

	// Esc 关闭：关的是弹层，侧板不许被带走。
	await btn.click();
	await expect(flyout).toBeVisible({timeout: 5_000});
	await page.keyboard.press('Escape');
	await expect(flyout).toHaveCount(0, {timeout: 5_000});
	await expect(page.getByLabel('沉浸模式侧板')).toBeVisible({timeout: 2_000});
});

test('沉浸侧板会话下拉：Esc 先关下拉，不关侧板', async ({page}) => {
	await page.evaluate(() => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
			}
		).__XEYO_CHAT__!.getState() as unknown as {setImmersive: (v: boolean) => void};
		st.setImmersive(true);
	});
	const panel = page.getByLabel('沉浸模式侧板');
	const titleBtn = panel.locator('button[aria-haspopup="menu"]').first();
	await titleBtn.click();
	const dropdown = panel.locator('.xy-menu-flyout');
	await expect(dropdown).toBeVisible({timeout: 5_000});

	await page.keyboard.press('Escape');
	await expect(dropdown).toHaveCount(0, {timeout: 5_000});
	// 判别点：侧板必须还在（当前反例：Esc 把整块侧板关掉、下拉随卸载消失）。
	await expect(panel).toBeVisible({timeout: 2_000});

	// 再按一次才退侧板。
	await page.keyboard.press('Escape');
	await expect(panel).toHaveCount(0, {timeout: 5_000});
});
