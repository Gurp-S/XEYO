// probe-jsonerr.mjs — 抓 bench 页 JSON SyntaxError 的完整堆栈
import {chromium} from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 1280, height: 800}});
const errs = [];
page.on('pageerror', e => {
	errs.push({msg: String(e), stack: e.stack || '(no stack)'});
});
await page.goto('http://127.0.0.1:5175/bench/chat?rounds=12');
await page.waitForFunction(() => {
	const w = window;
	return !!w.__XY_REPLAY__;
});
await page.waitForTimeout(2500);
console.log('errors:', errs.length);
for (const e of errs.slice(0, 4)) {
	console.log('---', e.msg);
	console.log(e.stack.split('\n').slice(0, 8).join('\n'));
}
await browser.close();
