/**
 * 排队（inbox）与引导（steer）全栈 E2E：真 Chromium + 真 FastAPI（provider=fake）。
 *
 * 机制（源码为准）：
 * - 前端忙时判定：`stores/chat/streamSendSlice.ts`（sessionStreamActive /
 *   remoteStreaming / turnDetached）；忙时 POST 带 `queue_if_busy: true`，
 *   引导再带 `steer_if_busy: true`（`lib/api/chatStream.ts`）。
 * - 后端忙时出口：`server/routers/chat.py::_busy_or_queue` —— 引导 202
 *   {steered:true}（无 queue_id、不入 inbox），排队 202 {queued:true, queue_id, position}。
 * - 投递：`engine/t_now_inbox.py`（边界声道，默认开）+ `server/inbox_registry.py`
 *   的 `on_turn_settled`（settle 排水兜底）。
 *
 * 忙窗口制造：FakeModelClient 逐字符流式（`model/fake.py`），用长回复撑开窗口；
 * 断言一律读 store（`__XEYO_CHAT__`），不靠可见文本——虚拟列表存在隐藏副本。
 */
import {test, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';

const COMPOSER = '消息输入';
const STOP = '停止生成';
/** 长回复 = 忙窗口（桩每字符数毫秒），够 Playwright 完成后续动作。 */
const BUSY_PAD = 'x'.repeat(3500);

const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-e2e-queue-ws-'));

type StoreView = {
	sid: string;
	inbox: Array<{state: string; text: string; message_id: string | null}>;
	messages: Array<{role: string; text: string; queueState: string | null}>;
	streaming: boolean;
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
			})),
			streaming: Boolean(stream?.isLoading),
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

test.beforeEach(async ({page}) => {
	await seedFakeTestSettings(page);
	await bootChat(page);
	await openWorkspaceSession(page, workspaceDir);
});

/** 开一个忙碌回合，返回时第一轮仍在流式。 */
async function startBusyTurn(page: Page, text: string): Promise<void> {
	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
	await expect(page.getByRole('button', {name: STOP}).first()).toBeVisible({
		timeout: 20_000,
	});
}

test('排队：忙时 Enter → 202 进 inbox（气泡标排队 + 队列卡），回合结束后真投递', async ({
	page,
}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	const first = await view(page);
	expect(first.streaming).toBe(true);

	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('QUEUE-E2E-MARK');
	await composer.press('Enter');

	// 202 受理：inbox 有条目，气泡被标记为 queued。
	const queued = await waitForView(
		page,
		v => v.inbox.some(i => i.text === 'QUEUE-E2E-MARK' && i.state === 'queued'),
		15_000,
	);
	expect(
		queued.messages.some(m => m.text === 'QUEUE-E2E-MARK' && m.queueState === 'queued'),
	).toBe(true);
	// 队列卡与气泡标记在 UI 上真的渲染出来。
	await expect(page.locator('[data-queue-dock]')).toBeVisible({timeout: 5_000});
	expect(queued.inbox[0]?.message_id).toBeTruthy();

	// settle 排水：排队消息成为真实一轮，模型对它作答；卡与标记随后清空。
	const delivered = await waitForView(
		page,
		v =>
			v.inbox.length === 0 &&
			v.messages.some(
				m => m.role === 'assistant' && m.text.includes('QUEUE-E2E-MARK'),
			),
		45_000,
	);
	expect(
		delivered.messages.some(
			m => m.text === 'QUEUE-E2E-MARK' && m.queueState !== null,
		),
	).toBe(false);
});

test('引导：忙时 Ctrl+Enter → 202 边界回执，不建队列卡、气泡不标排队', async ({
	page,
}) => {
	await startBusyTurn(page, `ok: busy ${BUSY_PAD}`);
	expect((await view(page)).streaming).toBe(true);

	const composer = page.getByLabel(COMPOSER);
	await composer.click();
	await composer.fill('STEER-E2E-MARK');
	await composer.press('Control+Enter');

	await expect(page.getByText(/已受理：最早在下个边界投递/).first()).toBeVisible({
		timeout: 15_000,
	});
	const after = await view(page);
	// 引导不入 inbox：没有队列卡，也没有排队标记（乐观气泡即全部指示物）。
	expect(after.inbox).toEqual([]);
	expect(
		after.messages.some(m => m.text === 'STEER-E2E-MARK' && m.queueState !== null),
	).toBe(false);
	expect(after.messages.some(m => m.text === 'STEER-E2E-MARK')).toBe(true);
	await expect(page.locator('[data-queue-dock]')).toHaveCount(0);
});
