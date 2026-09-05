import {useEffect} from 'react';
import {useNavigate} from 'react-router-dom';
import {useChatStore} from '@/stores/chatStore';

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

/** 在 Router 内部挂载一次：把 navigate 注入本模块（App.tsx 使用）。 */
export function AppNavBridge(): null {
	const navigate = useNavigate();
	useEffect(() => {
		setAppNavigator(navigate);
		return () => setAppNavigator(null);
	}, [navigate]);
	return null;
}

export type PageViewKind = 'usage' | 'plugins';

/** 路径 → 页面视图；非页面视图路径返回 null。 */
export function pageViewFromPath(pathname: string): PageViewKind | null {
	if (pathname === '/usage') {
		return 'usage';
	}
	if (pathname === '/plugins') {
		return 'plugins';
	}
	return null;
}

/** 打开页面视图（真路由导航；互斥天然成立）。 */
export function openPageView(kind: PageViewKind): void {
	go(`/${kind}`);
}

/** 关闭页面视图：回到当前会话（主会话 /c/:id，侧聊 /side/:id），无会话则回 '/'。 */
export function closePageView(opts?: {replace?: boolean}): void {
	const st = useChatStore.getState();
	const activeId = st.activeId;
	if (activeId?.startsWith('side-')) {
		const sideNext = st.sessions.find(s => s.id.startsWith('side-'));
		go(sideNext ? `/side/${sideNext.id}` : '/', opts);
		return;
	}
	go(activeId ? `/c/${activeId}` : '/', opts);
}

/**
 * 切换到某个会话（唯一入口）。侧聊会话（side- 前缀）自动走 /side/ 路由。
 * 页面视图若开着，随路由切换自动退出。
 */
export async function openSession(
	id: string,
	opts?: {replace?: boolean},
): Promise<void> {
	await useChatStore.getState().selectSession(id);
	go(
		id.startsWith('side-') ? `/side/${id}` : `/c/${id}`,
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
		return id;
	}
	const id = await st.createSession(opts?.spaceId);
	go(`/c/${id}`, {replace: opts?.replace});
	return id;
}
