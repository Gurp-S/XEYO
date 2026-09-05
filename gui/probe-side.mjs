import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1280, height: 800}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1200);
const out = await page.evaluate(() => {
	const aside = document.querySelector('aside');
	if (!aside) return 'no aside';
	const wide = [];
	for (const el of aside.querySelectorAll('*')) {
		if (el.scrollWidth > aside.clientWidth + 1) {
			const r = el.getBoundingClientRect();
			wide.push({
				tag: el.tagName,
				cls: (el.className || '').toString().slice(0, 70),
				scrollW: el.scrollWidth,
				w: Math.round(r.width),
				text: (el.textContent || '').slice(0, 30),
			});
		}
	}
	return wide.slice(0, 8);
});
console.log(JSON.stringify(out, null, 2));
await browser.close();
