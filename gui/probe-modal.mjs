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
await page.waitForTimeout(900);
const out = await page.evaluate(() => {
	const secs = Array.from(document.querySelectorAll('section'));
	return secs.slice(0, 12).map(function (s) {
		const r = s.getBoundingClientRect();
		const st = getComputedStyle(s);
		return {
			cls: s.className.slice(0, 60),
			w: Math.round(r.width),
			h: Math.round(r.height),
			display: st.display,
			visibility: st.visibility,
			textHead: (s.textContent || '').slice(0, 14),
		};
	});
});
console.log(JSON.stringify(out, null, 1));
await browser.close();
