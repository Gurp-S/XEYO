import {test, expect} from '@playwright/test';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-goal-regression-'));

test('goal survives reload, pause persists, and an obsolete editor cannot edit its replacement', async ({page}) => {
	await seedFakeTestSettings(page); await bootChat(page);
	const sid = await openWorkspaceSession(page, workspace);
	const url = `/v1/sessions/${sid}/goal`;
	await page.getByLabel('消息输入').fill('/goal persistent goal');
	await page.getByLabel('消息输入').press('Enter');
	await expect(page.locator('[data-goal-bar]')).toBeVisible();
	await page.reload();
	await expect(page.locator('[data-goal-bar]')).toBeVisible();
	await page.getByRole('button', {name: '暂停', exact: true}).click();
	await expect(page.locator('[data-goal-bar]')).toContainText('已暂停的目标');
	await page.reload();
	await expect(page.locator('[data-goal-bar]')).toContainText('已暂停的目标');
	const old = await (await page.request.get(url)).json();
	await page.getByRole('button', {name: '编辑目标', exact: true}).click();
	await page.getByPlaceholder('目标内容').fill('stale editor text');
	const replacement = await page.request.patch(url, {data: {action: 'new', text: 'replacement goal'}});
	expect(replacement.ok()).toBe(true);
	// The old editor may still be visible until the next poll. Both the UI and HTTP
	// identity guard must prevent that old intent from targeting the replacement.
	const stale = await page.request.patch(url, {data: {action: 'edit', goal_id: old.goal_id,
		revision: old.revision, text: 'stale editor text'}});
	expect(stale.status()).toBe(409);
	await expect(page.locator('[data-goal-bar]')).toContainText('replacement goal');
	await expect(page.getByPlaceholder('目标内容')).toHaveCount(0);
	expect((await (await page.request.get(url)).json()).text).toBe('replacement goal');
});
