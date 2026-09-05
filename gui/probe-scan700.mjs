import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 700, height: 560}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1500);
const out = await page.evaluate(() => {
	const vw = window.innerWidth;
	const res = [];
	for (const el of document.querySelectorAll('*')) {
		const r = el.getBoundingClientRect();
		if (r.width === 0 || r.height === 0) continue;
		if (r.right > vw + 2) {
			res.push({
				tag: el.tagName,
				cls: (el.className || '').toString().slice(0, 60),
				right: Math.round(r.right),
				w: Math.round(r.width),
				x: Math.round(r.x),
			});
		}
	}
	return {vw, res: res.slice(0, 10)};
});
console.log(JSON.stringify(out, null, 2));
await browser.close();
