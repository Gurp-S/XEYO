import {test, expect} from '@playwright/test';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

test('recovery abandonment preserves a stale prompt on conflict and clears only its accepted turn', async ({page}) => {
	test.setTimeout(180000);
	await seedFakeTestSettings(page); await bootChat(page);
	const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-recovery-abandon-'));
	const anchor = await openWorkspaceSession(page, workspace);
	const composer = page.getByLabel('消息输入'); await composer.fill('RECOVERY-ISOLATION-ANCHOR'); await composer.press('Enter');
	await expect.poll(async () => (await (await page.request.get(`/v1/sessions/${anchor}/task`)).json()).status).toBe('succeeded');
	// Locate only this run's isolated data using its newly created unique turn.
	const directories = fs.readdirSync(os.tmpdir()).filter(name => /^xeyo-e2e-\d+$/.test(name))
		.map(name => path.join(os.tmpdir(), name, 'sessions'))
		.filter(directory => fs.existsSync(path.join(directory, `${anchor}.turn.json`)));
	expect(directories).toHaveLength(1);
	const sid = await openWorkspaceSession(page, workspace);
	const snapshotPath = path.join(directories[0]!, `${sid}.turn.json`);
	const recovery = {session_id: sid, turn_id: 'recovery-old', status: 'recovery_required', goal_text: 'RECOVERY-RETAIN-PROMPT', revision: 1, stop_reason: 'process_restart'};
	fs.writeFileSync(snapshotPath, JSON.stringify(recovery));
	await expect.poll(async () => page.evaluate(async sid => {
		const store = (window as any).__XEYO_CHAT__; await store.getState().reattachStream(sid);
		return store.getState().recoveryBySession[sid]?.turnId;
	}, sid)).toBe('recovery-old');
	await expect(page.getByText(/上次任务在重启前未完成.*RECOVERY-RETAIN-PROMPT/)).toBeVisible();
	fs.writeFileSync(snapshotPath, JSON.stringify({...recovery, turn_id: 'recovery-new', status: 'running'}));
	await page.getByRole('button', {name: '放弃', exact: true}).click();
	await expect(page.getByText('放弃恢复未被服务端确认，请重试', {exact: true})).toBeVisible();
	await expect(page.getByRole('button', {name: '放弃', exact: true})).toBeVisible();
	expect(JSON.parse(fs.readFileSync(snapshotPath, 'utf8')).status).toBe('running');
	fs.writeFileSync(snapshotPath, JSON.stringify(recovery));
	await page.getByRole('button', {name: '放弃', exact: true}).click();
	await expect(page.getByRole('button', {name: '放弃', exact: true})).toHaveCount(0);
	const task = await (await page.request.get(`/v1/sessions/${sid}/task`)).json();
	expect(task).toMatchObject({status: 'stopped', turn_id: 'recovery-old', stop_reason: 'user_abandon'});
});
