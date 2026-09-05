import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('http://127.0.0.1:5175/bench/chat?rounds=12');
await page.waitForFunction(() => !!window.__XY_REPLAY__);
await page.waitForTimeout(1500);
const stats = await page.evaluate(() => {
	const codes = Array.from(document.querySelectorAll('pre code'));
	const withTokens = codes.filter(c => c.querySelector('.token')).length;
	return {codeBlocks: codes.length, withTokens};
});
console.log(JSON.stringify(stats));
await browser.close();
