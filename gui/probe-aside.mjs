import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1440, height: 900}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1200);
const out = await page.evaluate(() => {
	const aside = document.querySelector('aside');
	if (!aside) return 'no aside';
	const st = getComputedStyle(aside);
	const wide = [];
	for (const el of aside.querySelectorAll('*')) {
		const r = el.getBoundingClientRect();
		if (r.width > aside.clientWidth + 1) {
			wide.push({
				tag: el.tagName,
				cls: (el.className || '').toString().slice(0, 60),
				w: Math.round(r.width),
				text: (el.textContent || '').slice(0, 24),
			});
		}
	}
	return {clientW: aside.clientWidth, scrollW: aside.scrollWidth, overflowX: st.overflowX, wide: wide.slice(0, 6)};
});
console.log(JSON.stringify(out, null, 1));
await browser.close();
