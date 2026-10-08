import {test, expect} from '@playwright/test';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

for (const action of ['edit', 'cancel'] as const) {
	test(`late queue ${action} receipt preserves the new backend branch in memory and IndexedDB`, async ({page}) => {
		test.setTimeout(180000); await seedFakeTestSettings(page); await bootChat(page);
		const sid = await openWorkspaceSession(page, fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-queue-mutation-')));
		const composer = page.getByLabel('消息输入');
		await composer.fill('MUTATION-FIRST-' + 'x'.repeat(6500)); await composer.press('Enter');
		await expect(page.getByRole('button', {name: '停止生成'}).first()).toBeVisible();
		await composer.fill('QUEUED-MUTATION'); await composer.press('Enter'); await expect(composer).toHaveValue('');
		await page.getByRole('button', {name: '停止生成'}).first().click();
		await expect.poll(async () => (await (await page.request.get(`/v1/sessions/${sid}/task`)).json()).busy).toBe(false);
		await page.evaluate(sid => (window as any).__XEYO_CHAT__.getState().refreshInbox(sid), sid);
		const item = (await (await page.request.get(`/v1/sessions/${sid}/inbox`)).json()).items[0];
		expect(item?.message_id).toBeTruthy();
		const fork = await page.request.post(`/v1/sessions/${sid}/fork`); expect(fork.ok()).toBe(true);
		const backendId = (await fork.json()).new_id;
		let release!: () => void; const gate = new Promise<void>(done => {release = done;}); let ready = false;
		await page.route(`**/v1/sessions/${sid}/inbox/${item.queue_id}`, async route => {
			const response = await route.fetch(); expect(response.ok()).toBe(true); ready = true;
			await gate; await route.fulfill({response});
		});
		const work = page.evaluate(({sid, qid, action}) => {
			const store = (window as any).__XEYO_CHAT__.getState();
			return action === 'edit' ? store.editInboxItem(sid, qid, 'EDIT-ACCEPTED-ON-OLD-BRANCH') : store.cancelInboxItem(sid, qid);
		}, {sid, qid: item.queue_id, action});
		try {
			await expect.poll(() => ready).toBe(true);
			await page.evaluate(async ({sid, backendId, messageId}) => {
				const store = (window as any).__XEYO_CHAT__; const state = store.getState();
				const branch = {branchId: 'mutation-fork', backendSessionId: backendId, parentBranchId: 'root', createdAt: Date.now(), forkMessageId: null, label: 'fork'};
				const history = {activeBranch: branch, archivedBranches: []};
				const messages = [{id: messageId, role: 'user', text: 'NEW-BRANCH-RETAINED', createdAt: Date.now(), localUndelivered: true}];
				store.setState({historyById: {...state.historyById, [sid]: history}, inboxBySession: {...state.inboxBySession, [sid]: []}, messagesById: {...state.messagesById, [sid]: messages}});
				const modulePath = '/src/lib/db.ts'; const db = await import(modulePath);
				await db.setKv(`chat:history:${sid}`, JSON.stringify(history)); await db.replaceMessages(sid, messages);
			}, {sid, backendId, messageId: item.message_id});
		} finally {release();}
		expect(await work).toBe(true);
		const result = await page.evaluate(async ({sid, messageId}) => {
			const modulePath = '/src/lib/db.ts'; const db = await import(modulePath);
			// Expire ownership during the real IDB read, before either mutation.
			let current = true; const get = IDBObjectStore.prototype.get;
			IDBObjectStore.prototype.get = function(key) {const request = get.call(this, key); if (this.name === 'messages' && key === messageId) request.addEventListener('success', () => {current = false;}); return request;};
			try {await db.updateMessageText(sid, messageId, 'STALE-WRITE', () => current); current = true; await db.deleteMessageForSession(sid, messageId, () => current); current = true; await db.patchMessages(sid, [{id: messageId, role: 'user', text: 'STALE-POLL', createdAt: 1}], () => current);}
			finally {IDBObjectStore.prototype.get = get;}
			return {memory: (window as any).__XEYO_CHAT__.getState().messagesById[sid], saved: await db.loadMessages(sid)};
		}, {sid, messageId: item.message_id});
		expect(result.memory[0]?.text).toBe('NEW-BRANCH-RETAINED'); expect(result.saved[0]?.text).toBe('NEW-BRANCH-RETAINED');
		const oldInbox = (await (await page.request.get(`/v1/sessions/${sid}/inbox`)).json()).items;
		if (action === 'edit') expect(oldInbox[0]?.text).toBe('EDIT-ACCEPTED-ON-OLD-BRANCH'); else expect(oldInbox).toEqual([]);
	});
}
