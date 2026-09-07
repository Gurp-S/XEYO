import {create} from 'zustand';
import {registerWorkspaceAccessor} from '@/stores/storeRefs';

/** 右侧工作区 XEYO_Workspace 的入口分区。 */
export type WorkspaceSection =
	| 'files' // 项目文件
	| 'map' // 代码/架构地图
	| 'history' // 历史 diff
	| 'git'
	| 'terminal' // 终端
	| 'browser'; // 浏览器预览

/** 右侧工具面板（WorkspaceToolPanel）可选工具。 */
export type WorkspaceTool = 'git' | 'terminal' | 'history' | 'commits' | 'map' | 'browser';

type WorkspaceState = {
	/** 右侧工作区面板（整栏）是否展开。 */
	open: boolean;
	/** 当前激活的入口分区（内容顶满面板的那一个）。 */
	active: WorkspaceSection;
	/** 各分区自身是否展开（纵向列出、各自可独立展开）。 */
	expanded: Record<WorkspaceSection, boolean>;
	/** 工具面板当前激活的工具；null = 收起。 */
	activeTool: WorkspaceTool | null;
	/** 是否隐藏树导航（收起“右边内容”），让功能面板占满整个工作区宽度。 */
	navHidden: boolean;
	setOpen: (open: boolean) => void;
	setActive: (section: WorkspaceSection) => void;
	toggleSection: (section: WorkspaceSection) => void;
	setActiveTool: (tool: WorkspaceTool | null) => void;
	toggleNavHidden: () => void;
	/**
	 * 收起整个工作区：只切换开关，保留功能面板 / 文件预览 / “收起右边内容”等状态，
	 * 再次展开时恢复上次打开的内容。状态只读残留由面板侧用 open 门控，不渲染任何按钮。
	 */
	collapseWorkspace: () => void;
};

const DEFAULT_EXPANDED: Record<WorkspaceSection, boolean> = {
	files: false,
	map: false,
	history: false,
	git: false,
	terminal: false,
	browser: false,
};

export const useWorkspaceStore = create<WorkspaceState>(set => ({
	open: true,
	active: 'files',
	expanded: DEFAULT_EXPANDED,
	activeTool: null,
	navHidden: false,
	setOpen(open) {
		set({open});
	},
	setActive(section) {
		set({
			active: section,
			expanded: {...useWorkspaceStore.getState().expanded, [section]: true},
		});
	},
	toggleSection(section) {
		const current = useWorkspaceStore.getState();
		const nextOpen = !current.expanded[section];
		set({
			expanded: {...current.expanded, [section]: nextOpen},
			active: nextOpen ? section : current.active,
		});
	},
	setActiveTool(tool) {
		set({activeTool: tool});
	},
	toggleNavHidden() {
		set(s => ({navHidden: !s.navHidden}));
	},
	collapseWorkspace() {
		set({open: false});
	},
}));

registerWorkspaceAccessor(() => useWorkspaceStore.getState());
