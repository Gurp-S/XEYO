import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 700, height: 560}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1500);
const rows = await page.evaluate(() => {
	const row = document.querySelector('.xy-pane-row');
	if (!row) return 'no row';
	const kids = Array.from(row.children).map(function (c) {
		const r = c.getBoundingClientRect();
		const cls = (c.className || '').toString().split(' ').slice(0, 2).join('.');
		return c.tagName + '.' + cls + ': x=' + Math.round(r.x) + ' w=' + Math.round(r.width);
	});
	const main = document.querySelector('main');
	const p = main ? main.querySelector('p') : null;
	const pr = p ? p.getBoundingClientRect() : null;
	return {
		kids: kids,
		mainW: main ? Math.round(main.getBoundingClientRect().width) : -1,
		pW: pr ? Math.round(pr.width) : -1,
	};
});
console.log(JSON.stringify(rows, null, 2));
await browser.close();
