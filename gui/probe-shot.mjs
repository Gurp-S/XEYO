import {chromium} from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({viewport: {width: 700, height: 560}});
await page.goto('http://127.0.0.1:5175/');
await page.waitForTimeout(1500);
await page.screenshot({path: 'ui-audit-report/full/fix-700x560.png'});
await browser.close();
console.log('saved');
