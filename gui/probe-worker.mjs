import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('http://127.0.0.1:5175/');
const result = await page.evaluate(async () => {
	const url = new URL('src/lib/highlightWorker.ts', location.origin);
	const w = new Worker(url, {type: 'module'});
	return await new Promise(resolve => {
		const t = setTimeout(() => resolve('timeout'), 5000);
		w.onmessage = ev => {
			clearTimeout(t);
			resolve(JSON.stringify(ev.data).slice(0, 300));
		};
		w.onerror = e => {
			clearTimeout(t);
			resolve('worker-error: ' + (e.message || 'unknown'));
		};
		w.postMessage({id: 1, code: 'const x: number = 42;', lang: 'typescript'});
	});
});
console.log(result);
await browser.close();
