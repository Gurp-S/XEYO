import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1200);
await page.keyboard.press('Control+k');
await page.waitForTimeout(400);
await page.keyboard.insertText('设置');
await page.waitForTimeout(400);
await page.keyboard.press('Enter');
const samples = [];
for (const delay of [80, 200, 350, 600]) {
	await page.waitForTimeout(delay === 80 ? 80 : delay - (samples.length ? [80,200,350][samples.length-1] : 0));
	const s = await page.evaluate(() => {
		const secs = Array.from(document.querySelectorAll('section'));
		const visible0 = [];
		for (const s of secs) {
			const r = s.getBoundingClientRect();
			const st = getComputedStyle(s);
			if (st.display !== 'none' && st.visibility !== 'hidden' && (r.width < 2 || r.height < 2) && (s.textContent || '').length > 8) {
				visible0.push(s.className.slice(0, 40) + ' w=' + Math.round(r.width));
			}
		}
		return {t: Date.now() % 100000, zeroVisible: visible0.slice(0, 3)};
	});
	samples.push(s);
}
console.log(JSON.stringify(samples, null, 1));
await browser.close();
