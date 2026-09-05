import {gitFileDiff} from '@/lib/api';
import {useExplorerStore} from '@/stores/explorerStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';

export type OpenWorkspacePreviewOpts = {
	/**
	 * true：有工作区改动则开 diff，否则开文件。
	 * false/省略：始终开文件。
	 */
	preferDiff?: boolean;
};

/**
 * 打开右侧工作区文件预览（与 CommandPalette.openFilePath 同路径）。
 * FilePreview 要求 workspaceOpen && selectedPath。
 */
export async function openWorkspacePreview(
	path: string,
	opts?: OpenWorkspacePreviewOpts,
): Promise<void> {
	const trimmed = path.trim();
	if (!trimmed) {
		return;
	}
	useWorkspaceStore.getState().setOpen(true);
	useWorkspaceStore.getState().setActive('files');
	useExplorerStore.getState().setOpen(true);

	if (opts?.preferDiff) {
		try {
			const diff = await gitFileDiff(trimmed);
			if (diff.kind === 'diff' || diff.kind === 'untracked') {
				const name =
					trimmed.split(/[\\/]/).pop() || trimmed;
				await useExplorerStore.getState().openReview({
					path: trimmed,
					name,
					diff: diff.diff ?? '',
				});
				return;
			}
		} catch {
			/* 无 git / 失败时退回文件 */
		}
	}

	await useExplorerStore.getState().openFile(trimmed);
}

/** 打开工作区功能面板（git / terminal / history / map / commits / browser）。与文件预览互斥。 */
export function openWorkspacePanel(
	panel: 'git' | 'terminal' | 'history' | 'map' | 'commits' | 'browser',
): void {
	useWorkspaceStore.getState().setOpen(true);
	useWorkspaceStore.getState().setActiveTool(panel);
}

/**
 * 展示/关闭本轮工具流程地图（地图「本轮」视图）。
 * show=true 打开 map 并切到 turn；show=false 仅在当前是 map 时关闭工具面板。
 */
export function setMapToolFlowVisible(show: boolean): void {
	const ws = useWorkspaceStore.getState();
	if (show) {
		ws.setOpen(true);
		ws.setActiveTool('map');
		void import('@/stores/codeMapStore').then(({useCodeMapStore}) => {
			useCodeMapStore.getState().setView('turn');
		});
		return;
	}
	if (ws.activeTool === 'map') {
		ws.setActiveTool(null);
	}
}

export type BrowserUiOp = 'reload' | 'back' | 'fwd' | 'ext' | 'close';

/**
 * XeyoUI browser：打开预览面板并导航/控制。
 * url 优先；否则 op；都无则仅打开面板。
 */
export function controlBrowserPreview(opts?: {
	url?: string;
	op?: BrowserUiOp;
}): void {
	const url = opts?.url?.trim() ?? '';
	const op = opts?.op;
	const ws = useWorkspaceStore.getState();

	if (op === 'close') {
		if (ws.activeTool === 'browser') {
			ws.setActiveTool(null);
		}
		return;
	}

	ws.setOpen(true);
	ws.setActiveTool('browser');

	void import('@/stores/browserPreviewStore').then(({useBrowserPreviewStore}) => {
		const browser = useBrowserPreviewStore.getState();
		if (url) {
			browser.setUrl(url);
			browser.dispatch({kind: 'nav', url});
			return;
		}
		if (op === 'reload' || op === 'back' || op === 'fwd' || op === 'ext') {
			browser.dispatch({kind: op});
		}
	});
}
