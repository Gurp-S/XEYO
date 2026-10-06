import {REVIEW_LAYOUT_ENABLED} from '@/lib/reviewLayout';
/**
 * paneViewportClamp.ts — 窄窗口下面板让位钳制（2026-09-05 GUI 审计 P1 修复）。
 *
 * 结构性根因：侧栏与工作区都是**用户持久化固定宽**（默认各 248，上限 420），
 * 三栏 flex 里聊天列是唯一 flex-1 可压缩项且只有 min-w-[180px] 硬地板——
 * 窗口接近 Tauri minWidth 720 时，聊天列会被压到窄于可读宽度，欢迎语
 * 一字一行、Composer 底行溢出截断。聊天列的 180px CSS 下限只防止完全崩塌。
 *
 * 修复规则：**工作区先让位**（辅助面板，让到 PANE_WIDTH_MIN），侧栏后让；
 * 仍不够时双面板等比向 0 收缩，保证聊天列 ≥ CHAT_MIN_READABLE。
 * 只影响**有效渲染宽**，不写回持久化设置——窗口重新变宽即恢复用户设定宽。
 * 让位是连续的（PaneSlot 有宽度过渡动画），不跳变。
 */
import {useEffect, useState} from 'react';
import {useChatStore} from '@/stores/chatStore';
import {
	PANE_WIDTH_MAX,
	PANE_WIDTH_MIN,
	isSmoothnessOn,
	useSettingsStore,
} from '@/stores/settingsStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {useViewport} from './useViewport';

/** 聊天列可读下限：正文 34ch + Composer 底行不溢出的经验值。 */
export const CHAT_MIN_READABLE = 340;
export const SIDEBAR_COMPACT_WIDTH_MAX = 280;

/** Track the space shared by chat and its preview/tool panes as sibling panes change width. */
export function usePaneChatHostWidth(): number {
	const [hostWidth, setHostWidth] = useState(() => {
		if (typeof document === 'undefined') return PANE_WIDTH_MAX * 2;
		const host = document.querySelector<HTMLElement>('.xy-pane-chat-host');
		if (host) return host.clientWidth;
		return (
			document.querySelector<HTMLElement>('.xy-pane-row')?.clientWidth ??
			PANE_WIDTH_MAX * 2
		);
	});

	useEffect(() => {
		const host = document.querySelector<HTMLElement>('.xy-pane-chat-host');
		const row = document.querySelector<HTMLElement>('.xy-pane-row');
		const target = host ?? row;
		if (!target) return;

		const sync = () => {
			const next = host?.clientWidth ?? row?.clientWidth ?? PANE_WIDTH_MAX * 2;
			setHostWidth(current => (current === next ? current : next));
		};
		sync();
		if (typeof ResizeObserver === 'undefined') {
			window.addEventListener('resize', sync);
			return () => window.removeEventListener('resize', sync);
		}

		const observer = new ResizeObserver(sync);
		observer.observe(target);
		return () => observer.disconnect();
	}, []);

	return hostWidth;
}

/** 侧栏在紧凑窗口里的渲染宽；存储值继续保留，窗口变宽后恢复。 */
export function sidebarRenderedWidth(width: number, compact: boolean): number {
	return compact ? Math.min(width, SIDEBAR_COMPACT_WIDTH_MAX) : width;
}

export type PaneClamp = {
	sidebarEff: number;
	workspaceEff: number;
};

/** 纯函数：便于单测与两侧面板一致计算。 */
export function computePaneViewportClamp(
	viewportWidth: number,
	sidebar: {open: boolean; width: number},
	workspace: {open: boolean; width: number},
	chatMin = CHAT_MIN_READABLE,
	paneFloor = PANE_WIDTH_MIN,
	layoutGap = 0,
): PaneClamp {
	let sEff = sidebar.open ? Math.max(0, sidebar.width) : 0;
	let wEff = workspace.open ? Math.max(0, workspace.width) : 0;
	const restore = (): PaneClamp => ({
		sidebarEff: sidebar.open ? Math.round(sEff) : sidebar.width,
		workspaceEff: workspace.open ? Math.round(wEff) : workspace.width,
	});

	const overflow = sEff + wEff + chatMin + Math.max(0, layoutGap) - viewportWidth;
	if (overflow <= 0) {
		return restore();
	}

	// 第一优先：工作区让位（辅助面板），但不让破 PANE_WIDTH_MIN。
	const wYieldMax = Math.max(0, wEff - paneFloor);
	const wYield = Math.min(wYieldMax, overflow);
	wEff -= wYield;
	let rest = overflow - wYield;

	// 第二优先：侧栏让位。
	if (rest > 0) {
		const sYieldMax = Math.max(0, sEff - paneFloor);
		const sYield = Math.min(sYieldMax, rest);
		sEff -= sYield;
		rest -= sYield;
	}

	// 兜底：双面板等比向 0 收缩（极窄窗口保聊天可读优先于保面板）。
	if (rest > 0) {
		const total = wEff + sEff;
		if (total > 0) {
			wEff = Math.max(0, wEff - (wEff / total) * rest);
			sEff = Math.max(0, sEff - (sEff / total) * rest);
		} else {
			return restore();
		}
	}
	return restore();
}

/**
 * 两侧面板共用同一计算（读同一组 store 值），保证结果一致、无竞态。
 * 面板关闭时原样返回用户设定宽（不参与钳制）。
 */
export function usePaneViewportClamp(): PaneClamp {
	const vp = useViewport();
	const sidebarWidth = useSettingsStore(s => s.sidebarWidth);
	const explorerWidth = useSettingsStore(s => s.explorerWidth);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const sidebarOpen = useChatStore(s => s.sidebarOpen);
	const paneLayout = useSettingsStore(s => s.paneLayout);
	// 工作区开合在独立 workspaceStore（TitleBar 开关同一来源）。
	const workspaceOpen = useWorkspaceStore(s => s.open);
	const workspaceVisible = useWorkspaceStore(s => s.open && !s.navHidden);
	const sidebarRendered = sidebarRenderedWidth(sidebarWidth, vp.compact);
	if (REVIEW_LAYOUT_ENABLED) {
		const available = Math.max(0, vp.width - (vp.width <= 600 ? 44 : 48) - 6);
		const drawer = vp.width <= 900;
		const sidebarEff = Math.min(sidebarWidth, Math.max(0, available - (drawer ? 0 : CHAT_MIN_READABLE + (workspaceOpen ? PANE_WIDTH_MIN : 0))));
		const host = Math.max(0, available - (!drawer && sidebarOpen ? sidebarEff : 0));
		return {
			sidebarEff,
			workspaceEff: Math.min(explorerWidth, vp.width <= 640 ? Math.max(0, host - 16) : Math.max(0, Math.min(host * .52, host - CHAT_MIN_READABLE))),
		};
	}
	// islands 的 row gap 作用于实际 flex 子项，宽度为 0 的过渡槽也占一道 gap。
	// 平滑模式始终保留左右槽；关闭平滑模式时槽随面板卸载，只计仍打开的槽。
	const layoutGap =
		!REVIEW_LAYOUT_ENABLED && paneLayout === 'islands'
			? 8 *
					(Number(smoothness || sidebarOpen) + Number(smoothness || workspaceOpen))
			: 0;
	return computePaneViewportClamp(
		vp.width,
		{open: sidebarOpen, width: sidebarRendered},
		{open: workspaceVisible, width: explorerWidth},
		CHAT_MIN_READABLE,
		PANE_WIDTH_MIN,
		layoutGap,
	);
}
