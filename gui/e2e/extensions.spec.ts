import {test, expect} from '@playwright/test';

/**
 * extensions.spec.ts — 扩展中心(插件 / MCP / Skill)功能冒烟。
 *
 * 真后端(隔离 XEYO_HOME)+ Vite dev。覆盖:
 *   1. 侧边栏入口打开扩展中心;页头标题切「扩展中心」;
 *   2. 三 tab(插件 / MCP / 技能)与计数徽标渲染;
 *   3. 扩展层总开关已从 GUI 移除(回归);
 *   4. MCP tab 切换 + 搜索过滤(含无匹配空态);
 *   5. 技能 tab 渲染;
 *   6. 页面视图互斥:扩展 → 用量 → 扩展,不叠层不卡死;
 *   7. 页头「返回对话」切回聊天界面;
 *   8. 输入框 + 菜单 → MCP 面板 → Manage 跳转扩展中心(回归)。
 * 断言一律收窄在 [data-testid=extensions-panel] 内,避免页面其他区域
 * (如文件树「加载失败」)的同形文案造成误伤。
 * 运行:npx playwright test -c playwright.extensions.config.ts
 */
test('扩展中心:打开 → 三 tab → MCP 搜索 → 技能 → 互斥 → 返回对话 → Manage 跳转', async ({
	page,
}) => {
	await page.goto('/');

	// 1. 侧边栏入口打开面板;页头标题随视图切换;会话操作按钮让位
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	const panel = page.getByTestId('extensions-panel');
	await expect(
		page.locator('header').getByText('扩展中心', {exact: true}),
	).toBeVisible();
	await expect(page.locator('button[aria-label="新对话"]')).toHaveCount(0);

	// 2. 三 tab 可见,计数徽标为数字(文本形如「插件3」「MCP0」)
	const tablist = panel.getByRole('tablist', {name: '扩展类型'});
	for (const label of ['插件', 'MCP', '技能']) {
		const tab = tablist.getByRole('tab', {name: new RegExp(`^${label}`)});
		await expect(tab).toBeVisible();
		await expect(tab).toHaveText(new RegExp(`^${label}\\s*\\d+$`));
	}

	// 3. 扩展层总开关已从 GUI 移除(2026-09-05):面板内不允许出现该 switch
	await expect(panel.getByRole('switch', {name: /扩展层/})).toHaveCount(0);

	// 4. MCP tab:切换 + 搜索无匹配空态 + 清空恢复
	await tablist.getByRole('tab', {name: /MCP/}).click();
	const search = panel.getByLabel('搜索MCP');
	await search.fill('___no_match___');
	await expect(panel.getByText('没有匹配的 MCP。')).toBeVisible();
	await panel.getByRole('button', {name: '清空搜索'}).click();
	await expect(panel.getByLabel('搜索MCP')).toHaveValue('');

	// 5. 技能 tab:预置了 3 个显式停用技能 → 行容器渲染
	await tablist.getByRole('tab', {name: /技能/}).click();
	await expect(panel.getByText(/加载失败：/)).toHaveCount(0);
	await expect(
		panel.locator('ul li').or(panel.getByText('未发现技能。')).first(),
	).toBeVisible();

	// 6. 页面视图互斥:开用量 → 扩展面板卸载;再开扩展 → 用量关闭。
	await page.getByRole('button', {name: '用量', exact: true}).click();
	await expect(panel).toHaveCount(0);
	await expect(page.locator('header').getByText('用量', {exact: true})).toBeVisible();
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await expect(page.getByTestId('extensions-panel')).toBeVisible();

	// 7. 侧边栏 toggle 关闭面板,切回聊天界面
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await expect(page.getByTestId('extensions-panel')).toHaveCount(0);
	await expect(page.locator('header').getByText('新对话')).toBeVisible();

	// 7b. 侧边栏 toggle 二次点击:再开 → 再关,回聊天界面(回归:2026-09-05 用户实测点不回)
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await expect(page.getByTestId('extensions-panel')).toBeVisible();
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await expect(page.getByTestId('extensions-panel')).toHaveCount(0);
	await expect(page.locator('header').getByText('新对话')).toBeVisible();

	// 8. 输入框 + 菜单 → MCP 面板 → Manage 跳转扩展中心 → 侧边栏切回
	await page.getByRole('button', {name: '打开操作菜单'}).click();
	await page.getByRole('menuitem', {name: 'MCP'}).click();
	const mcpSearch = page.getByLabel('搜索 MCP');
	await expect(mcpSearch).toBeVisible();
	await page.getByRole('button', {name: /Manage/}).click();
	await expect(page.getByTestId('extensions-panel')).toBeVisible();
	await expect(
		page.locator('header').getByText('扩展中心', {exact: true}),
	).toBeVisible();
	// 页面视图下「新对话」按钮从 DOM 移除、无「返回对话」按钮(2026-09-05 用户要求)
	// 注:用 CSS locator——侧栏展开时页头工具组带 aria-hidden,role 查询会漏计。
	await expect(page.locator('button[aria-label="新对话"]')).toHaveCount(0);
	await expect(page.getByRole('button', {name: '返回对话'})).toHaveCount(0);
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await expect(page.getByTestId('extensions-panel')).toHaveCount(0);
	await expect(page.locator('button[aria-label="新对话"]')).toHaveCount(1);

	// 9. 留档截图:重开面板,切到技能 tab(有行数据,验收工具栏/行容器/居中布局)
	await page.getByRole('button', {name: '插件 / MCP'}).click();
	await page.getByTestId('extensions-panel').getByRole('tab', {name: /技能/}).click();
	await page.waitForTimeout(400); // stagger 入场 + 过渡余量
	await page.screenshot({
		path: 'ui-audit-report/extensions-panel.png',
		fullPage: false,
	});
});
