import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1200);
const out = await page.evaluate(() => {
	const aside = document.querySelector('aside');
	const aLeft = aside.getBoundingClientRect().left;
	const wide = [];
	for (const el of aside.querySelectorAll('*')) {
		const r = el.getBoundingClientRect();
		if (r.right > aLeft + aside.clientWidth + 1) {
			wide.push({
				tag: el.tagName,
				cls: (el.className || '').toString().slice(0, 70),
				rightRel: Math.round(r.right - aLeft),
				w: Math.round(r.width),
				cls_: getComputedStyle(el).position,
				text: (el.textContent || '').slice(0, 20),
			});
		}
	}
	return wide.slice(0, 8);
});
console.log(JSON.stringify(out, null, 1));
await browser.close();
