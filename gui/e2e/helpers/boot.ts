import {expect, type Page} from '@playwright/test';

const COMPOSER_PLACEHOLDER = '描述任务… Enter 发送';
const CRASH_MARK = '界面渲染出错';

/**
 * 启动 GUI 并等待聊天界面就绪；若命中 GuiErrorBoundary 崩溃屏
 * （「界面渲染出错」），把边界捕获的错误一并抛出，让 e2e 一次跑出
 * 可定位的根因，而不是笼统的「composer not found」：
 *
 * - 边界把 `error.message` 渲染在折叠的 `<details><pre>` 里 —— DOM 中
 *   始终存在，`textContent` 可直接读出（无需展开）；
 * - `componentDidCatch` 还会 `console.error('[XEYO GUI]', error, stack)`，
 *   另加 pageerror / console 监听兜底拿完整堆栈。
 */
export async function bootChat(page: Page, timeoutMs = 15_000): Promise<void> {
	const pageErrors: string[] = [];
	page.on('pageerror', err => {
		pageErrors.push(err?.stack || String(err));
	});
	const consoleErrors: string[] = [];
	page.on('console', msg => {
		if (msg.type() === 'error') {
			consoleErrors.push(msg.text());
		}
	});

	await page.goto('/');
	const composer = page.getByPlaceholder(COMPOSER_PLACEHOLDER);
	const crashed = page.getByText(CRASH_MARK);
	try {
		await expect
			.poll(
				async () =>
					(await composer.isVisible().catch(() => false)) ||
					(await crashed.isVisible().catch(() => false)),
				{timeout: timeoutMs},
			)
			.toBeTruthy();
	} catch {
		/* composer 与崩溃屏都没等到：交给末尾的 composer 断言给出常规失败 */
	}

	if (await crashed.isVisible().catch(() => false)) {
		const boundaryMessage =
			(await page
				.locator('details pre')
				.first()
				.textContent()
				.catch(() => null)) ?? '(边界未给出 message)';
		const lines = [
			'GUI 启动崩溃（GuiErrorBoundary）。',
			`[boundary.message] ${boundaryMessage.trim()}`,
		];
		if (pageErrors.length) {
			lines.push('[pageerror]', ...pageErrors.slice(0, 3));
		}
		const boundaryConsole = consoleErrors.filter(t =>
			t.includes('[XEYO GUI]'),
		);
		if (boundaryConsole.length) {
			lines.push('[console.error · boundary]', ...boundaryConsole.slice(0, 2));
		} else if (consoleErrors.length) {
			lines.push('[console.error]', ...consoleErrors.slice(0, 5));
		}
		throw new Error(lines.join('\n'));
	}

	await expect(composer).toBeVisible();
}

/**
 * 打开真实文件夹为工作区并新建会话（fullstack 骨架同款）。
 *
 * fake 层用例必须显式建会话：不绑 workspace 会被「请先打开一个项目文件夹」
 * 守卫拦截，而被启动期自动状态带偏时连「发送被接受但气泡消失」这种悬案都会出现。
 * `dir` 需真实存在（后端校验），用例侧用 fs.mkdtempSync 生成。
 */
export async function openWorkspaceSession(
	page: Page,
	dir: string,
): Promise<void> {
	await page.evaluate(p => {
		const st = (
			window as unknown as {
				__XEYO_CHAT__?: {
					getState: () => {
						openFolder: (r: string) => Promise<string | unknown>;
						createSession: () => Promise<string>;
					};
				};
			}
		).__XEYO_CHAT__!.getState();
		return (async () => {
			await st.openFolder(p);
			await st.createSession();
		})();
	}, dir);
}
