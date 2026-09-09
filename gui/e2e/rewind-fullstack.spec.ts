/**
 * B 层全栈 · 回溯专项（Playwright：真 Chromium + 真后端 local→mock_llm + Vite）。
 *
 * 运行：gui 目录下
 *   npm run test:e2e:rewind
 *   （= npx --no-install playwright test -c playwright.fullstack-rewind.config.ts）
 *
 * 覆盖文件级回溯链路（mock_llm 脚本化 Write 工具，见
 * scripts/smoke_p0p1/e2e_responses/t_rewind_write.json）：
 *
 *   发消息 → Write 新建 note.txt（审批面板放行）→ turn 结束
 *   → 发送时冻结的 checkpoint 可查（弹窗 Restore 变为可用）
 *   → 编辑该消息打开回溯弹窗 → 「恢复文件检查点」
 *   → agent 新建的 note.txt 被回溯删除（工作区回到检查点状态）
 *   → 「撤销回溯」→ note.txt 按 pre_rewind_index 写回，内容一致。
 *
 * 修复前该链路必挂：engine 冻结 checkpoint 时传了不存在的 workspace_root
 * 参数（TypeError 被 except 吞掉）→ checkpoints.jsonl 永远为空 →
 * Restore 恒禁用、弹窗永远「此条没有文件检查点」。
 */
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedLocalTest} from './helpers/seed';
import {WS_DIR} from '../playwright.fullstack-rewind.config';

// 对应 playwright.fullstack-rewind.config.ts 的默认 mock 端口。
// 读 XEYO_E2E_MOCK_PORT 让用户在 Windows 排除端口区间（8430-8529 含 8491），
// 需用 9491+ 等空闲端口启动时不被写死。
const MOCK_BASE = `http://127.0.0.1:${process.env.XEYO_E2E_MOCK_PORT || '8491'}/v1`;
const COMPOSER = '描述任务… Enter 发送';

const EDIT_BUBBLE = '编辑这条消息';
const EDIT_PREVIEW = '点击开始编辑';
const EDIT_TEXTAREA = '编辑历史消息';
const BTN_RESTORE = '恢复文件检查点';
const BTN_UNDO = '撤销回溯';
const DONE_TITLE = '回溯完成';

// 用后端启动时设的 XEYO_UI_CWD 作工作区根（session pool 的 cwd 来源），
// 让 Write 工具解析相对路径 file_path="note.txt" 时落到同一处，便于
// restore/undo 断言文件存在与否。无法 fallback 到 OS tmpdir（那样就脱钩了）。
// 直接 import config 的 WS_DIR 常量（spec 进程读不到 webServer 子进程 env）。
const workspaceDir = WS_DIR;
const notePath = path.join(workspaceDir, 'note.txt');
const NOTE_CONTENT = 'hello rewind\n';

test.beforeEach(async ({page}) => {
	await seedLocalTest(page, {baseUrl: MOCK_BASE, permissionMode: 'always'});
	// 启动诊断：若命中 GuiErrorBoundary 崩溃屏，抛出 boundary/控制台的真实错误。
	await bootChat(page);
	// 打开真实文件夹作为工作区并建会话（同 fullstack.spec.ts 的骨架）。
	await openWorkspaceSession(page, workspaceDir);
});

async function send(page: import('@playwright/test').Page, text: string) {
	const composer = page.getByPlaceholder(COMPOSER);
	await composer.click();
	await composer.fill(text);
	await composer.press('Enter');
}

/**
 * 找到 transcript 含指定 user 文本的会话 id，并返回该 user 消息的 transcript id。
 *
 * 复用后端时会话列表可能残留历史会话（含相同文本的多条 / 停在
 * transcript_committed 或无 checkpoint 的旧态），因此按 updatedAt 取**最新**
 * 匹配会话，避免旧会话污染检查点断言。
 */
async function findSessionAndMessageId(
	page: import('@playwright/test').Page,
	userText: string,
): Promise<{sid: string; mid: string} | null> {
	let hit: {sid: string; mid: string} | null = null;
	await expect
		.poll(
			async () => {
				try {
					const sessions = (await (
						await page.request.get('/v1/sessions')
					).json()) as {
						sessions?: Array<{id: string; updatedAt?: number}>;
					};
					let best: {
						sid: string;
						mid: string;
						updatedAt: number;
					} | null = null;
					for (const s of sessions.sessions ?? []) {
						const msgs = (await (
							await page.request.get(`/v1/sessions/${s.id}/messages`)
						).json()) as {
							messages?: Array<{id: string; role: string; text: string}>;
						};
						const row = (msgs.messages ?? []).find(
							m => m.role === 'user' && m.text === userText,
						);
						if (row?.id) {
							const updatedAt = s.updatedAt ?? 0;
							if (!best || updatedAt > best.updatedAt) {
								best = {sid: s.id, mid: row.id, updatedAt};
							}
						}
					}
					if (best) {
						hit = {sid: best.sid, mid: best.mid};
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
	return hit;
}

test('文件检查点回溯：Write 新建文件 → Restore 删除 → Undo 写回', async ({page}) => {
	await send(page, '创建文件');

	// 放行 T3 审批面板（permissionMode=always 路径下，UI 行为可能为 auto-allow
	// 也可能弹面板；二者都尝试，按出现顺序点击。若并行 GUI 在途改动导致面板
	// 文案变化，按钮名 "允许" 应仍稳定）。
	const panel = page.getByRole('alertdialog', {name: '请求批准'});
	try {
		await expect(panel).toBeVisible({timeout: 10_000});
		await panel.getByRole('button', {name: '允许'}).click();
	} catch {
		/* auto-allow 路径：直接走文件落盘断言。 */
	}

	// Write 真实落盘 + 助理回复收尾（最权威的"工具真的写了"信号）。
	await expect
		.poll(() => fs.existsSync(notePath), {timeout: 30_000})
		.toBeTruthy();
	await expect(page.getByText('文件已创建')).toBeVisible({timeout: 20_000});
	expect(fs.readFileSync(notePath, 'utf-8')).toBe(NOTE_CONTENT);

	// 等检查点就绪（修复前这里永远是 404/none）→ 拿 (sid, mid)。
	const hit = await findSessionAndMessageId(page, '创建文件');
	expect(hit, 'session + user message should be on the server').toBeTruthy();
	const {sid, mid} = hit!;
	await expect
		.poll(
			async () => {
				try {
					const cp = (await (
						await page.request.get(
							`/v1/sessions/${sid}/rewind/checkpoint/${mid}`,
						)
					).json()) as {checkpoint_id?: string | null};
					return Boolean(cp.checkpoint_id);
				} catch {
					return false;
				}
			},
			{timeout: 15_000},
		)
		.toBeTruthy();

	// 编辑该消息 → 回溯弹窗；检查点已冻结 → Restore 必须可用。
	await page
		.getByRole('button', {name: EDIT_BUBBLE})
		.filter({hasText: '创建文件'})
		.first()
		.click();
	await page.getByLabel(EDIT_PREVIEW).click();
	const textarea = page.getByLabel(EDIT_TEXTAREA);
	await expect(textarea).toBeVisible();
	await textarea.fill('创建文件 v2');
	await textarea.press('Enter');

	const dialog = page.locator('dialog.xy-rewind-dialog');
	await expect(dialog.getByText('回溯到这条对话')).toBeVisible();
	const restoreBtn = dialog.getByRole('button', {name: BTN_RESTORE});
	await expect(restoreBtn).toBeEnabled({timeout: 10_000});
	await restoreBtn.click();

	// Restore：transcript 不动、agent 新建文件按检查点删除 → 完成态。
	// exact 匹配：正文「回溯完成」标题之外，底部还有「撤销回溯完成」，substring 会命中 2 个元素。
	await expect(dialog.getByText(DONE_TITLE, {exact: true})).toBeVisible({
		timeout: 20_000,
	});
	await expect(dialog.getByText(/已移除 1 个新建文件|已是检查点状态/)).toBeVisible();
	await expect
		.poll(() => fs.existsSync(notePath), {timeout: 20_000})
		.toBeFalsy();

	// Undo：按 pre_rewind_index 把被删文件写回，内容一致。
	const undoBtn = dialog.getByRole('button', {name: BTN_UNDO});
	await expect(undoBtn).toBeVisible();
	await undoBtn.click();
	await expect
		.poll(() => fs.existsSync(notePath), {timeout: 20_000})
		.toBeTruthy();
	expect(fs.readFileSync(notePath, 'utf-8')).toBe(NOTE_CONTENT);
});
