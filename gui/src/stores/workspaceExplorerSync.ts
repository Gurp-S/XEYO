import {useExplorerStore} from '@/stores/explorerStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';

/** 应用启动时一次性绑定 workspace ↔ explorer 的互斥关系。 */
export function bindWorkspaceExplorerSync(): void {
	useExplorerStore.subscribe((state, prev) => {
		const openedPreview = Boolean(state.selectedPath);
		const hadPreview = Boolean(prev.selectedPath);
		if (openedPreview && !hadPreview) {
			useWorkspaceStore.setState({activeTool: null});
		}
	});
	useWorkspaceStore.subscribe((state, prev) => {
		if (state.activeTool && state.activeTool !== prev.activeTool) {
			useExplorerStore.getState().closePreview();
		}
	});
}
