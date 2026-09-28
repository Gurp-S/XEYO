/**
 * ChatHeader 标题行的截断可复原守卫。
 *
 * 复现的缺陷：会话标题与工作区名挤在同一个 `max-w-[28ch] truncate` 的 span 里，
 * 且整行没有任何 title 属性 → 被截掉的那一段文本再也回不来；`ch` 是拉丁字宽，
 * 中文标题在同一宽度下少掉将近一半信息。
 * 现在：主文本（会话标题）与次文本（工作区名）分成两格各自截断，次文本自己封顶
 * 10ch，长路径再也吃不掉标题；两截都带 title，截断可复原。
 */
import {cleanup, render} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {ChatHeader} from './ChatHeader';

const LONG_TITLE = '把用量界面真正融进 A3 报告：折叠口径、分母与实付成本一起对齐';
const ROOT_PATH = 'D:\\lea\\XenYon code';

const state = vi.hoisted(() => ({
	// 该组件里 sidebarOpen=true 走的是"整块塌掉"的动画分支（改动前后同一套三元判断），
	// 默认测标题可见的那一支——截断只可能发生在这一支。
	sidebarOpen: false,
}));

vi.mock('@/stores/chatUiStore', () => ({
	useChatUiStore: (sel: (s: never) => unknown) =>
		sel(
			{
				activeId: 's1',
				activeSpaceId: 'w1',
				sessions: [{id: 's1', title: LONG_TITLE}],
				spaces: [{id: 'w1', name: 'XenYon code', rootPath: ROOT_PATH}],
				sessionUsageById: {},
			} as never,
		),
}));

vi.mock('@/stores/chatStore', () => ({
	useChatStore: (sel: (s: never) => unknown) =>
		sel(
			{
				sidebarOpen: state.sidebarOpen,
				setSidebarOpen: vi.fn(),
				requestSearchFocus: vi.fn(),
				historyById: {},
				agentViewStack: [],
				agentViewIndex: 0,
				multiAgentTasksBySession: {},
			} as never,
		),
}));

vi.mock('@/lib/appNav', () => ({
	newSession: vi.fn(),
	openPageView: vi.fn(),
	pageViewFromPath: () => null,
}));

vi.mock('@/lib/api', () => ({getCachedModelContextLimit: () => 0}));
vi.mock('@/lib/modelWindow', () => ({
	registeredWindowFromSettings: () => null,
	resolveWindowLimit: () => null,
	windowUsagePercent: () => null,
}));
vi.mock('@/components/SessionJobsBadge', () => ({
	SessionJobsBadge: () => null,
}));

function renderHeader(mode: 'main' | 'side' = 'main') {
	return render(
		<MemoryRouter initialEntries={['/']}>
			<ChatHeader mode={mode} />
		</MemoryRouter>,
	);
}

/** 主文本格与次文本格：按 class 里的截断预算区分。 */
function titleCell(): HTMLElement {
	return document.querySelector('.xy-hdr-title > span:first-child') as HTMLElement;
}
function workspaceCell(): HTMLElement | null {
	return document.querySelector('.xy-hdr-title > span:nth-child(2)') as HTMLElement | null;
}

describe('ChatHeader 标题截断', () => {
	afterEach(cleanup);

	it('标题格带完整会话标题的 title，被截断也能复原', () => {
		renderHeader();
		const cell = titleCell();
		expect(cell.textContent).toBe(LONG_TITLE);
		expect(cell).toHaveAttribute('title', LONG_TITLE);
		expect(cell.className).toContain('truncate');
	});

	it('工作区名单独一格：自己封顶并带 title，不再吃标题', () => {
		renderHeader();
		const ws = workspaceCell();
		expect(ws).not.toBeNull();
		expect(ws!.textContent).toBe(` · ${'XenYon code'}`);
		expect(ws).toHaveAttribute('title', 'XenYon code');
		// 次文本有独立预算，且明显小于整行 28ch 的上限
		expect(ws!.className).toMatch(/max-w-\[10ch\]/);
		expect(ws!.className).toContain('truncate');
		expect(titleCell().className).toMatch(/flex-1/);
	});

	it('整行上限仍是 28ch，侧栏展开且不在页面视图时整块塌掉的动画类没变', () => {
		// 组件判据是 `sidebarOpen && !pageViewOpen` 才塌（侧栏已给出上下文，标题让位）。
		state.sidebarOpen = false;
		renderHeader();
		const row = document.querySelector('.xy-hdr-title') as HTMLElement;
		expect(row.className).toMatch(/max-w-\[28ch\]/);
		expect(row).not.toHaveAttribute('aria-hidden', 'true');
		cleanup();
		state.sidebarOpen = true;
		renderHeader();
		const collapsed = document.querySelector('.xy-hdr-title') as HTMLElement;
		expect(collapsed.className).toMatch(/max-w-0/);
		expect(collapsed).toHaveAttribute('aria-hidden', 'true');
	});

	it('side 模式不显示工作区名（行为不变）', () => {
		renderHeader('side');
		expect(workspaceCell()).toBeNull();
		expect(titleCell()).toHaveAttribute('title', LONG_TITLE);
	});
});
