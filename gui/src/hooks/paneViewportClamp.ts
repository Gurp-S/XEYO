/**
 * paneViewportClamp.ts — 窄窗口下面板让位钳制（2026-09-05 GUI 审计 P1 修复）。
 *
 * 结构性根因：侧栏与工作区都是**用户持久化固定宽**（默认各 248，上限 420），
 * 三栏 flex 里聊天列是唯一 flex-1 可压缩项且只有 min-w-[180px] 硬地板——
 * 窗口接近 Tauri minWidth 720 时（700 实测更早），聊天列被压到 ~204px，
 * 欢迎语一字一行、Composer 底行溢出截断。
 *
 * 修复规则：**工作区先让位**（辅助面板，让到 PANE_WIDTH_MIN），侧栏后让；
 * 仍不够时双面板等比向 0 收缩，保证聊天列 ≥ CHAT_MIN_READABLE。
 * 只影响**有效渲染宽**，不写回持久化设置——窗口重新变宽即恢复用户设定宽。
 * 让位是连续的（PaneSlot 有宽度过渡动画），不跳变。
 */
import {useChatStore} from '@/stores/chatStore';
import {
	PANE_WIDTH_MIN,
	useSettingsStore,
} from '@/stores/settingsStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {useViewport} from './useViewport';

/** 聊天列可读下限：正文 34ch + Composer 底行不溢出的经验值。 */
export const CHAT_MIN_READABLE = 340;

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
): PaneClamp {
	let sEff = sidebar.open ? Math.max(0, sidebar.width) : 0;
	let wEff = workspace.open ? Math.max(0, workspace.width) : 0;
	const restore = (): PaneClamp => ({
		sidebarEff: sidebar.open ? Math.round(sEff) : sidebar.width,
		workspaceEff: workspace.open ? Math.round(wEff) : workspace.width,
	});

	const overflow = sEff + wEff + chatMin - viewportWidth;
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
	const sidebarOpen = useChatStore(s => s.sidebarOpen);
	// 工作区开合在独立 workspaceStore（TitleBar 开关同一来源）。
	const workspaceOpen = useWorkspaceStore(s => s.open);
	return computePaneViewportClamp(
		vp.width,
		{open: sidebarOpen, width: sidebarWidth},
		{open: workspaceOpen, width: explorerWidth},
	);
}
