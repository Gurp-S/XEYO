import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {SIDE_SPACE_ID} from '@/lib/db';
import {useChatStore} from '@/stores/chatStore';
import type {ChatSession} from '@/lib/types';
import {
	closePageView,
	isSideChatPath,
	openPageView,
	pageViewFromPath,
	sessionRouteMatches,
	setAppNavigator,
} from './appNav';

/**
 * 导航入口回归：路径谓词必须全站一条规则（bug #1），
 * 页面视图之间不得往浏览器历史里堆条目（bug #4）。
 */

type NavCall = {to: string; replace?: boolean};

function recordingNavigator(): {
	calls: NavCall[];
	set: (to: string, opts?: {replace?: boolean}) => void;
} {
	const calls: NavCall[] = [];
	return {
		calls,
		set: (to, opts) => calls.push({to, replace: opts?.replace}),
	};
}

function goTo(pathname: string): void {
	window.history.replaceState({}, '', pathname);
}

beforeEach(() => {
	goTo('/');
});

afterEach(() => {
	setAppNavigator(null);
});

describe('路径谓词按 React Router 的规则归一（bug #1）', () => {
	it('isSideChatPath 忽略大小写与尾随斜杠', () => {
		expect(isSideChatPath('/side/s1')).toBe(true);
		expect(isSideChatPath('/Side/s1')).toBe(true);
		expect(isSideChatPath('/SIDE/s1')).toBe(true);
		expect(isSideChatPath('/side/s1/')).toBe(true);
		expect(isSideChatPath('/c/m1')).toBe(false);
		expect(isSideChatPath('/')).toBe(false);
	});

	it('sessionRouteMatches 与它同源：大小写不同的会话路由也算停在原位', () => {
		expect(sessionRouteMatches('/c/m1', 'm1')).toBe(true);
		expect(sessionRouteMatches('/C/m1', 'm1')).toBe(true);
		expect(sessionRouteMatches('/c/m1/', 'm1')).toBe(true);
		expect(sessionRouteMatches('/side/s1', 's1', true)).toBe(true);
		expect(sessionRouteMatches('/Side/s1', 's1', true)).toBe(true);
		expect(sessionRouteMatches('/usage', 'm1')).toBe(false);
		expect(sessionRouteMatches('/c/m2', 'm1')).toBe(false);
	});

	it('pageViewFromPath 与 isSideChatPath 对同一路径不会各说各话', () => {
		goTo('/Side/s1');
		expect(pageViewFromPath(window.location.pathname)).toBeNull();
		expect(isSideChatPath(window.location.pathname)).toBe(true);
	});
});

describe('页面视图导航不污染历史（bug #4）', () => {
	it('从聊天界面进入页面视图仍是 push：后退要回得来那个会话', () => {
		const nav = recordingNavigator();
		setAppNavigator(nav.set);
		goTo('/c/m1');
		openPageView('usage');
		expect(nav.calls).toEqual([{to: '/usage', replace: false}]);
	});

	it('页面视图之间（用量→扩展→诊断）走 replace：一次往返不再堆 4 条', () => {
		const nav = recordingNavigator();
		setAppNavigator(nav.set);
		goTo('/c/m1');
		openPageView('usage');
		goTo('/usage');
		openPageView('plugins');
		goTo('/plugins');
		openPageView('diagnostics', {session: 'm1'});
		expect(nav.calls.map(c => c.to)).toEqual([
			'/usage',
			'/plugins',
			'/diagnostics?session=m1',
		]);
		expect(nav.calls.map(c => Boolean(c.replace))).toEqual([false, true, true]);
	});

	it('打开会话仍然 push（交接目的地要留在历史里）', () => {
		const nav = recordingNavigator();
		setAppNavigator(nav.set);
		closePageView();
		expect(nav.calls).toEqual([{to: '/', replace: undefined}]);
		const side: ChatSession = {
			id: 's1',
			spaceId: SIDE_SPACE_ID,
			title: '侧聊',
			createdAt: 0,
			updatedAt: 0,
		};
		useChatStore.setState({sessions: [side], activeId: 's1'});
		closePageView();
		expect(nav.calls[1]).toEqual({to: '/side/s1', replace: undefined});
	});

	it('Router 未挂载时静默丢弃，不抛错', () => {
		setAppNavigator(null);
		expect(() => openPageView('usage')).not.toThrow();
	});
});
