// probe-palette.mjs — 定位 Ctrl+K 白屏根因的一次性探针
import {chromium} from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const logs = [];
page.on('console', m => logs.push(`[${m.type()}] ${m.text()}`));
page.on('pageerror', e => logs.push(`[pageerror] ${e}`));
page.on('requestfailed', r => logs.push(`[reqfail] ${r.url()} ${r.failure()?.errorText}`));
page.on('response', r => { if (r.status() >= 400) logs.push(`[http ${r.status()}] ${r.url()}`); });

await page.goto('http://127.0.0.1:5175/', {waitUntil: 'networkidle'}).catch(() => {});
await page.waitForTimeout(1200);
console.log('--- before Ctrl+K: root children =',
	await page.evaluate(() => document.getElementById('root')?.children.length ?? 'no-root'));

await page.keyboard.press('Control+k');
await page.waitForTimeout(900);
const state = await page.evaluate(() => ({
	rootChildren: document.getElementById('root')?.children.length ?? -1,
	rootHtmlLen: (document.getElementById('root')?.innerHTML ?? '').length,
	bodyChildren: Array.from(document.body.children).map(c => `${c.tagName}.${(c.className || '').toString().slice(0, 40)}`),
	bodyHtmlHead: document.body.innerHTML.slice(0, 500),
}));
console.log('--- after Ctrl+K:', JSON.stringify(state, null, 2));
await page.screenshot({path: 'ui-audit-report/full/probe-palette.png'});
console.log('--- logs:');
for (const l of logs) console.log(' ', l.slice(0, 200));
await browser.close();
