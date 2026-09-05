// probe-reload.mjs — 复现审计 B 的冷启动时序，观察 Ctrl+K 后 12s 内的恢复/重载信号
import {chromium} from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
const logs = [];
page.on('console', m => logs.push(`t=${Date.now() % 100000} [${m.type()}] ${m.text().slice(0, 160)}`));
page.on('pageerror', e => logs.push(`t=${Date.now() % 100000} [pageerror] ${String(e).slice(0, 160)}`));

// 完全复刻审计 B 时序：goto → 800ms → Ctrl+K → 400ms 后测
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(800);
await page.keyboard.press('Control+k');
await page.waitForTimeout(400);

const samples = [];
for (let i = 0; i < 12; i += 1) {
	const s = await page.evaluate(() => ({
		rootLen: (document.getElementById('root')?.innerHTML ?? '').length,
		paletteOpen: !!document.querySelector('body > div.fixed.inset-0.z-\\[9999\\]'),
	}));
	samples.push(`t+${i}s rootLen=${s.rootLen} palette=${s.paletteOpen}`);
	await page.waitForTimeout(1000);
}
console.log('--- 采样时间线:');
for (const s of samples) console.log(' ', s);
console.log('--- console 日志（近 30 条）:');
for (const l of logs.slice(-30)) console.log(' ', l);
await page.screenshot({path: 'ui-audit-report/full/probe-reload-final.png'});
await browser.close();
