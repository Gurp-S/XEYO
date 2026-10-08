import {test, expect, type Page} from '@playwright/test';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

async function legacyHistory(page: Page) {
	await seedFakeTestSettings(page); await bootChat(page);
	const sid = await openWorkspaceSession(page, fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-history-recovery-')));
	const composer = page.getByLabel('消息输入'); await composer.fill('HISTORY-BASE'); await composer.press('Enter');
	await expect.poll(async () => (await (await page.request.get(`/v1/sessions/${sid}/task`)).json()).status).toBe('succeeded');
	await expect.poll(() => page.evaluate(() => {
		const s = (window as any).__XEYO_CHAT__.getState(); return Boolean(s.sessionStreams[s.activeId]?.draining || s.sessionStreams[s.activeId]?.isLoading);
	})).toBe(false);
	const server = (await (await page.request.get(`/v1/sessions/${sid}/messages`)).json()).messages;
	await page.evaluate(async ({sid, server}) => {
		const modulePath = '/src/lib/db.ts'; const db = await import(modulePath);
		const prose = server.find((row: any) => row.role === 'assistant');
		await db.replaceMessages(sid, [...server,
			{...prose, id: 'legacy-duplicate'}, {...prose, id: 'legacy-fragment', text: 'unsaved partial response'},
			{id: 'undelivered-input', role: 'user', text: 'RETAIN-UNDELIVERED-INPUT', createdAt: Date.now()}]);
	}, {sid, server});
	return {sid, server};
}

const state = (page: Page) => page.evaluate(() => {
	const s = (window as any).__XEYO_CHAT__.getState(); return s.messagesById[s.activeId] ?? [];
});

test('persisted pending inputs remain excluded from model history before inbox projection', async ({page}) => {
	test.setTimeout(180000);
	await seedFakeTestSettings(page); await bootChat(page);
	const sid = await openWorkspaceSession(page, fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-pending-history-')));
	const result = await page.evaluate(async sid => {
		const dbPath = '/src/lib/db.ts'; const apiPath = '/src/lib/toApiMessages.ts';
		const db = await import(dbPath); const {toApiMessages} = await import(apiPath);
		const sample = (id: string, queueState: string) => ({id, role: 'user', text: id, createdAt: Date.now(), queueState});
		await db.replaceMessages(sid, [sample('replacement', 'queued')]);
		await db.upsertMessages(sid, [sample('upsert', 'delivering')]);
		await db.patchMessages(sid, [sample('patch', 'syncing')]);
		const pending = await db.loadMessages(sid);
		await db.patchMessages(sid, [{id: 'patch', role: 'user', text: 'actually delivered', createdAt: Date.now()}]);
		return {pending, context: toApiMessages(pending), delivered: toApiMessages(await db.loadMessages(sid))};
	}, sid);
	expect(result.pending).toHaveLength(3);
	expect(result.pending.every((row: any) => row.localUndelivered && row.queueState === undefined)).toBe(true);
	expect(result.context).toEqual([]);
	expect(result.delivered.map((row: any) => row.id)).toEqual(['patch']);
});

test('complete settled history repairs legacy duplicates, backs up originals, and retains undelivered input', async ({page}) => {
	test.setTimeout(180000); const {sid, server} = await legacyHistory(page);
	await page.reload(); await page.waitForFunction(() => (window as any).__XEYO_CHAT__?.getState().hydrated);
	await expect.poll(async () => (await state(page)).filter((row: any) => !row.isThought && !row.localUndelivered && !row.uiOnly))
		.toEqual(server.filter((row: any) => !row.isThought && !row.uiOnly).map((row: any) => expect.objectContaining(row)));
	await expect(page.getByText('未送达 · 本地保留', {exact: true})).toBeVisible();
	await expect(page.getByText('RETAIN-UNDELIVERED-INPUT', {exact: true})).toBeVisible();
	const backup = await page.evaluate(async sid => {
		const modulePath = '/src/lib/db.ts'; const db = await import(modulePath);
		return JSON.parse(await db.getKv(`input-history-backup:${encodeURIComponent(sid)}:${encodeURIComponent(sid)}`));
	}, sid);
	expect(backup.messages.map((row: any) => row.id)).toContain('legacy-duplicate');
	expect(backup.persistedMessages.map((row: any) => row.id)).toContain('legacy-fragment');
	const after = await state(page);
	await page.reload(); await page.waitForFunction(() => (window as any).__XEYO_CHAT__?.getState().hydrated);
	await expect.poll(async () => (await state(page)).map((row: any) => row.id)).toEqual(after.map((row: any) => row.id));
	const out = path.resolve('..', 'docs', 'input-chain-audit-2026-10-07', 'fixed'); fs.mkdirSync(out, {recursive: true});
	fs.writeFileSync(path.join(out, 'legacy-history-recovery.json'), JSON.stringify({server, restored: after, backup}, null, 2));
	await page.evaluate(async sid => {
		const modulePath = '/src/lib/db.ts'; const db = await import(modulePath);
		const key = `input-history-backup:${encodeURIComponent(sid)}:${encodeURIComponent(sid)}`;
		await db.setKv('input-history-backup:other-session:other-backend', 'retained');
		await db.deleteSession(sid);
		if (await db.getKv(key) !== undefined) throw new Error('backup survived session deletion');
		if (await db.getKv('input-history-backup:other-session:other-backend') !== 'retained') throw new Error('unrelated backup deleted');
	}, sid);
});

test('backup write failure keeps original history and never partially replaces it', async ({page}) => {
	test.setTimeout(180000); const {sid} = await legacyHistory(page);
	await page.addInitScript(() => {
		const put = IDBObjectStore.prototype.put;
		IDBObjectStore.prototype.put = function(value, key) {
			if (this.name === 'kv' && typeof key === 'string' && key.startsWith('input-history-backup:')) {
				throw new DOMException('test backup quota', 'QuotaExceededError');
			}
			return put.call(this, value, key);
		};
	});
	await page.reload();
	await expect(page.getByText('历史备份未完成，已保留原本地历史', {exact: true})).toBeVisible();
	const original = await page.evaluate(async sid => {
		const modulePath = '/src/lib/db.ts'; const db = await import(modulePath);
		return {rows: await db.loadMessages(sid), backup: await db.getKv(`input-history-backup:${encodeURIComponent(sid)}:${encodeURIComponent(sid)}`)};
	}, sid);
	expect(original.rows.map((row: any) => row.id)).toContain('legacy-duplicate');
	expect(original.rows.map((row: any) => row.id)).toContain('legacy-fragment');
	expect(original.backup).toBeUndefined();
	expect((await state(page)).map((row: any) => row.id)).toContain('legacy-duplicate');
});
