import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1280, height: 800}});
await page.goto('http://127.0.0.1:5175/bench/chat?rounds=12');
await page.waitForFunction(() => !!window.__XY_REPLAY__);
await page.waitForTimeout(4000);
const out = await page.evaluate(() => {
	const codes = Array.from(document.querySelectorAll('pre code'));
	const withTokens = codes.filter(function (c) { return c.querySelector('.token'); });
	return {
		codeBlocks: codes.length,
		withTokens: withTokens.length,
		sample: (withTokens[0] || codes[0]) ? (withTokens[0] || codes[0]).innerHTML.slice(0, 120) : null,
	};
});
console.log(JSON.stringify(out, null, 2));
await browser.close();
