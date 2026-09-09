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
 * 清空后端 session store（ISOLATE_DIR/sessions 跨 test 共享，否则 76 test
 * 留下的会话会在 100 test 启动时通过 hydrate.importServerSessions 拉回
 * IDB，ChatPage 路由 effect 把 activeId 切到残留 sid 导致 send 守卫拦）。
 *
 * 完整两步：归档（解除 DELETE 409 archived_required）→ 硬删。
 * 不区分主/侧聊；侧聊 session_id 以 "side-" 开头走同一端点。
 */
export async function resetBackendSessions(
	page: Page,
	backendPort: number = Number(
		process.env.XEYO_E2E_BACKEND_PORT ?? process.env.XEYO_E2E_PORT ?? '8177',
	),
): Promise<void> {
	const base = `http://127.0.0.1:${backendPort}`;
	const res = await page.request.get(`${base}/v1/sessions`);
	const body = (await res.json()) as {sessions?: Array<{id: string}>};
	const list = body.sessions ?? [];
	for (const s of list) {
		try {
			await page.request.post(`${base}/v1/sessions/${s.id}/archive`);
		} catch {
			/* 归档失败继续尝试 delete（已归档/已删会 4xx） */
		}
		try {
			await page.request.delete(`${base}/v1/sessions/${s.id}`);
		} catch {
			/* 同上：容忍已删 */
		}
	}
}

/**
 * 打开真实文件夹为工作区并新建会话，返回新建的 sessionId。
 *
 * fake 层用例必须显式建会话：不绑 workspace 会被「请先打开一个项目文件夹」
 * 守卫拦截，而被启动期自动状态带偏时连「发送被接受但气泡消失」这种悬案都会出现。
 * `dir` 需真实存在（后端校验），用例侧用 fs.mkdtempSync 生成。
 *
 * 三道屏障覆盖 rewind.spec 72/133 冷启动首测必挂的根因：
 *  1. ChatPage effect 触发 hydrate() 不 await，其收尾是整包
 *     set({spaces, sessions, ...hydrated:true})。若 openFolder 抢跑，
 *     新建 state 会被旧快照覆盖 → send 守卫拦。等 `hydrated===true`。
 *  2. ChatPage 路由对齐 effect 会在 hydrated 后抢跑、可能把 activeId
 *     倒回任何残留的孤儿 session（防御式：即便 production 已修
 *     DEFAULT_SPACE_ID 跳过，e2e 也以 activeId===新建 sid 为权威信号）。
 *  3. 等 spaces 绑上 rootPath + activeSpaceId + 挂在它下的会话真存在
 *     —— 避免 createSession resolve 与 UI 渲染之间微小窗口让守卫拦首条 send。
 */
export async function openWorkspaceSession(
	page: Page,
	dir: string,
): Promise<string> {
	await page.waitForFunction(
		() => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {
						getState: () => {hydrated?: boolean};
					};
				}
			).__XEYO_CHAT__!.getState();
			return st.hydrated === true;
		},
		{timeout: 20_000},
	);
	const sid = (await page.evaluate(p => {
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
			return await st.createSession();
		})();
	}, dir)) as string;
	// 双层幂等校验（防 ChatPage 路由 effect 把 activeId 拉回任何残留 session）：
	// ① spaces 里有 rootPath 精确等于 dir 的空间、activeSpaceId 指向它；
	// ② activeId 已切到 createSession 返回的 dirSpace 会话（send 守卫读
	//    session.spaceId === spaces[].id，若 activeId 错位 send 必被拦）。
	try {
		await page.waitForFunction(
			({p, sid}) => {
				const st = (
					window as unknown as {
						__XEYO_CHAT__?: {
							getState: () => {
								spaces?: Array<{rootPath?: string}>;
								activeSpaceId?: string | null;
								sessions?: Array<{spaceId?: string}>;
								activeId?: string | null;
							};
						};
					}
				).__XEYO_CHAT__!.getState();
				return (
					!!st.spaces &&
					st.spaces.some(s => s.rootPath === p) &&
					!!st.activeSpaceId &&
					!!st.sessions &&
					st.sessions.some(s => s.spaceId === st.activeSpaceId) &&
					st.activeId === sid
				);
			},
			{p: dir, sid},
			{timeout: 15_000},
		);
	} catch (err) {
		// 诊断：失败时 dump store + 路由态，给 e2e 失败根因可定位的快照。
		const diag = await page.evaluate(() => {
			const st = (
				window as unknown as {
					__XEYO_CHAT__?: {getState: () => Record<string, unknown>};
				}
			).__XEYO_CHAT__?.getState();
			return {
				hydrated: st?.hydrated,
				activeId: st?.activeId,
				activeSpaceId: st?.activeSpaceId,
				spaces: (st?.spaces as Array<{id: string; rootPath: string}> | undefined)?.map(s => ({
					id: s.id,
					rootPath: s.rootPath,
				})),
				sessions: (st?.sessions as Array<{id: string; spaceId: string}> | undefined)?.map(s => ({
					id: s.id,
					spaceId: s.spaceId,
				})),
				url: window.location.pathname,
			};
		});
		throw new Error(
			`[openWorkspaceSession] 双层校验超时\n` +
				`  expected dir=${dir} sid=${sid}\n` +
				`  store=${JSON.stringify(diag, null, 2)}\n` +
				`  cause=${(err as Error).message}`,
		);
	}
	return sid;
}
