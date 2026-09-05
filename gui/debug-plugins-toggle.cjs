/* 侧栏收起状态下:经 Manage 跳转进插件界面后的返回路径复现(用户真实路径)。 */
const {chromium} = require('playwright');

(async () => {
	const browser = await chromium.launch();
	const page = await browser.newPage({viewport: {width: 1280, height: 800}});
	await page.goto('http://localhost:5199/');
	await page.waitForLoadState('networkidle');

	// 折叠侧栏(对齐用户截图状态)
	await page.getByRole('button', {name: '折叠侧栏'}).click();
	await page.waitForTimeout(500);

	// 用户真实路径:+ 菜单 → MCP → Manage 跳转
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	await page.getByRole('menuitem', {name: 'MCP'}).click();
	await page.waitForTimeout(500);
	await page.getByRole('button', {name: /Manage/}).click();
	await page.waitForTimeout(800);
	const panelOpen = await page.locator('[data-testid=extensions-panel]').count();
	await page.screenshot({path: 'ui-audit-report/debug-6-plugins-nosb.png'});

	// 路径A:Esc 关闭
	await page.keyboard.press('Escape');
	await page.waitForTimeout(800);
	const afterEsc = await page.locator('[data-testid=extensions-panel]').count();
	const chatBackA = await page.locator('button[aria-label="打开操作菜单"]').count();
	await page.screenshot({path: 'ui-audit-report/debug-7-after-esc.png'});

	// 路径B:再进 → 展开侧栏 → 点 插件/MCP
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	await page.getByRole('menuitem', {name: 'MCP'}).click();
	await page.waitForTimeout(400);
	await page.getByRole('button', {name: /Manage/}).click();
	await page.waitForTimeout(600);
	await page.getByRole('button', {name: '展开侧栏'}).click();
	await page.waitForTimeout(600);
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await page.waitForTimeout(1000);
	const afterSidebar = await page.locator('[data-testid=extensions-panel]').count();
	const chatBackB = await page.locator('button[aria-label="打开操作菜单"]').count();
	await page.screenshot({path: 'ui-audit-report/debug-8-recovered.png'});

	console.log(JSON.stringify({panelOpen, afterEsc, chatBackA, afterSidebar, chatBackB}, null, 2));
	await browser.close();
})().catch(e => {
	console.error('FATAL', e);
	process.exit(1);
});
