/**
 * ui-audit-probe.spec.ts — 白屏根因探针（诊断用，可随审计一起跑）。
 * 复现 Ctrl+K 打开命令面板后 #root 被清空的现象，dump DOM 与全部 console 消息。
 */
import {test} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_DIR = path.resolve(__dirname, '..', 'ui-audit-report', 'full');

test('探针：Ctrl+K 后 DOM/console 全量取证', async ({page}) => {
	fs.mkdirSync(REPORT_DIR, {recursive: true});
	const logs: string[] = [];
	page.on('console', m => logs.push(`[${m.type()}] ${m.text().slice(0, 300)}`));
	page.on('pageerror', e => logs.push(`[pageerror] ${String(e).slice(0, 300)}`));
	page.on('requestfailed', r => logs.push(`[reqfail] ${r.url()} ${r.failure()?.errorText ?? ''}`));
	page.on('response', r => {
		if (r.status() >= 400) logs.push(`[http ${r.status()}] ${r.url()}`);
	});

	await page.goto('/');
	await page.waitForTimeout(1200);
	const before = await page.evaluate(() => ({
		rootChildren: document.getElementById('root')?.children.length ?? -1,
		rootHtmlLen: (document.getElementById('root')?.innerHTML ?? '').length,
	}));

	await page.keyboard.press('Control+k');
	await page.waitForTimeout(900);
	const after = await page.evaluate(() => ({
		rootChildren: document.getElementById('root')?.children.length ?? -1,
		rootHtmlLen: (document.getElementById('root')?.innerHTML ?? '').length,
		bodyChildren: Array.from(document.body.children).map(
			c => `${c.tagName} id=${c.id} class=${String(c.className).slice(0, 60)}`),
		rootHtmlHead: (document.getElementById('root')?.innerHTML ?? '').slice(0, 800),
	}));
	await page.screenshot({path: path.join(REPORT_DIR, 'probe-palette.png')});

	fs.writeFileSync(
		path.join(REPORT_DIR, 'probe-palette.json'),
		JSON.stringify({before, after, logs}, null, 2), 'utf-8');
	// 取证型探针：不因现象本身失败。
});
