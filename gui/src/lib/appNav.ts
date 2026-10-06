import {useEffect} from 'react';
import {useNavigate} from 'react-router-dom';
import {useChatStore} from '@/stores/chatStore';
import {SIDE_SPACE_ID} from '@/lib/db';

/**
 * 全局导航桥 + 统一会话/页面视图导航入口（2026-09-05 复用审计落地）。
 *
 * 背景：全 GUI 曾有 21 处各自手写「关页面视图 + selectSession + navigate」，
 * 「点不回」类 bug 反复发生。此处收敛为唯一入口：
 * - `openSession` / `newSession`：切会话/新建会话的唯一方式（页面视图随路由
 *   自动退出，无需调用方手动关闭）。
 * - `openPageView` / `closePageView`：用量/扩展中心页面视图的唯一开合方式
 *   （真路由 /usage、/plugins，互斥由「路由只有一个」天然保证）。
 *
 * 非组件上下文（zustand slice、Esc 处理器）也能调用：App 通过 AppNavBridge
 * 把 react-router 的 navigate 注入本模块。
 */

type NavigateFn = (to: string, opts?: {replace?: boolean}) => void;

let navigateFn: NavigateFn | null = null;

export function setAppNavigator(fn: NavigateFn | null): void {
	navigateFn = fn;
}

function go(to: string, opts?: {replace?: boolean}): void {
	if (!navigateFn) {
		// Router 未挂载（单测/极早期调用）：静默丢弃，不抛错。
		return;
	}
	navigateFn(to, opts);
}

/** 地址栏路径（BrowserRouter 下即真路由路径）。非浏览器环境回落 '/'。 */
function currentPathname(): string {
	return typeof window === 'undefined' ? '/' : window.location.pathname;
}

/** 在 Router 内部挂载一次：把 navigate 注入本模块（App.tsx 使用）。 */
export function AppNavBridge(): null {
	const navigate = useNavigate();
	useEffect(() => {
		setAppNavigator(navigate);
		return () => setAppNavigator(null);
	}, [navigate]);
	return null;
}

export type PageViewKind = 'usage' | 'plugins' | 'diagnostics';

/**
 * 路径归一：React Router 默认忽略大小写并接受尾随斜杠，页面视图/路由段派生
 * 必须遵循同一规则，否则同一个界面会被判成两种路由（曾致 `/Side/<id>` 下
 * 侧栏点亮错行）。全站路径谓词一律走这里，不再各自 `startsWith`。
 */
function normalizePath(pathname: string): string {
	return pathname.replace(/\/+$/, '').toLowerCase() || '/';
}

/** 路径 → 页面视图；非页面视图路径返回 null。 */
export function pageViewFromPath(pathname: string): PageViewKind | null {
	const path = normalizePath(pathname);
	if (path === '/usage') {
		return 'usage';
	}
	if (path === '/plugins') {
		return 'plugins';
	}
	if (path === '/diagnostics') {
		return 'diagnostics';
	}
	return null;
}

/** 路径是否侧聊路由（`/side/<id>`）。与 `pageViewFromPath` 同一归一规则。 */
export function isSideChatPath(pathname: string): boolean {
	return normalizePath(pathname).startsWith('/side/');
}

/**
 * 路径是否正好停在某个会话自己的路由上（归档/删除「当前会话」时的落点判定）。
 * 页面视图（/usage 等）不带会话 id，因此一律返回 false。
 */
export function sessionRouteMatches(
	pathname: string,
	id: string,
	side = false,
): boolean {
	return normalizePath(pathname) === `${side ? '/side/' : '/c/'}${id.toLowerCase()}`;
}

/** 打开页面视图（真路由导航；互斥天然成立）。`query` 用于可深链的页面（诊断）。 */
export function openPageView(
	kind: PageViewKind,
	query?: Record<string, string | undefined>,
): void {
	const q = new URLSearchParams();
	for (const [k, v] of Object.entries(query ?? {})) {
		if (v) q.set(k, v);
	}
	const qs = q.toString();
	// 页面视图 → 页面视图（用量→扩展→诊断）用 replace：一次往返若每条都 push，
	// 浏览器历史会留下 4 条，后退键要把每个页面视图重放一遍。
	// 从聊天界面首次进入页面视图仍 push，后退才回得去那个会话。
	go(`/${kind}${qs ? `?${qs}` : ''}`, {
		replace: pageViewFromPath(currentPathname()) !== null,
	});
}

/** 关闭页面视图：回到当前会话（主会话 /c/:id，侧聊 /side/:id），无会话则回 '/'。 */
export function closePageView(opts?: {replace?: boolean}): void {
	const st = useChatStore.getState();
	const activeId = st.activeId;
	const active = st.sessions.find(session => session.id === activeId);
	if (active?.spaceId === SIDE_SPACE_ID) {
		go(`/side/${active.id}`, opts);
		return;
	}
	go(active ? `/c/${active.id}` : '/', opts);
}

/**
 * 切换到某个会话（唯一入口）。侧聊会话按 space 元数据走 /side/ 路由。
 * 页面视图若开着，随路由切换自动退出。
 */
export async function openSession(
	id: string,
	opts?: {replace?: boolean},
): Promise<void> {
	const before = useChatStore.getState().sessions.find(session => session.id === id);
	if (!before) return;
	await useChatStore.getState().selectSession(id);
	const session = useChatStore.getState().sessions.find(item => item.id === id);
	if (!session) return;
	go(
		session.spaceId === SIDE_SPACE_ID ? `/side/${id}` : `/c/${id}`,
		opts,
	);
}

/**
 * 新建会话（唯一入口）。`side: true` 建侧聊并走 /side/ 路由；
 * 否则建主会话（可指定 spaceId）并走 /c/ 路由。
 */
export async function newSession(opts?: {
	spaceId?: string;
	side?: boolean;
	replace?: boolean;
}): Promise<string> {
	const st = useChatStore.getState();
	if (opts?.side) {
		const id = await st.createSideSession();
		go(`/side/${id}`, {replace: opts?.replace});
		st.requestComposerFocus();
		return id;
	}
	const id = await st.createSession(opts?.spaceId);
	go(`/c/${id}`, {replace: opts?.replace});
	// 用户显式要新会话 ⇒ 输入面就绪（否则要先点一下输入框才能打字；
	// 请求焦点机制本来就有，只是从来没人接这一枪）。
	st.requestComposerFocus();
	return id;
}
