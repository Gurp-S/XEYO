import {useExplorerStore} from '@/stores/explorerStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';

/** Bind workspace ↔ explorer mutual exclusion once at app startup. */
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
