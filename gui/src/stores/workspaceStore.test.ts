import {beforeEach, describe, expect, it} from 'vitest';
import {useWorkspaceStore} from './workspaceStore';
import {useExplorerStore} from './explorerStore';
import {bindWorkspaceExplorerSync} from './workspaceExplorerSync';

bindWorkspaceExplorerSync();

describe('workspaceStore', () => {
	beforeEach(() => {
		useWorkspaceStore.setState({
			open: true,
			active: 'files',
			expanded: {
				files: true,
				map: false,
				history: false,
				git: false,
				terminal: false,
				browser: false,
			},
			activeTool: null,
			navHidden: false,
		});
		useExplorerStore.setState({
			selectedPath: null,
			reviewDiff: null,
			loadingFile: false,
			doc: null,
		});
	});

	it('collapseWorkspace persists open content so re-expanding reveals it', () => {
		useWorkspaceStore.setState({activeTool: 'terminal', navHidden: true});

		useWorkspaceStore.getState().collapseWorkspace();

		const s = useWorkspaceStore.getState();
		expect(s.open).toBe(false);
		expect(s.activeTool).toBe('terminal');
		expect(s.navHidden).toBe(true);

		useWorkspaceStore.getState().setOpen(true);
		const reopened = useWorkspaceStore.getState();
		expect(reopened.open).toBe(true);
		expect(reopened.activeTool).toBe('terminal');
		expect(reopened.navHidden).toBe(true);
	});

	it('toggleNavHidden flips right-content collapse', () => {
		useWorkspaceStore.setState({activeTool: 'git'});

		useWorkspaceStore.getState().toggleNavHidden();
		expect(useWorkspaceStore.getState().navHidden).toBe(true);

		useWorkspaceStore.getState().toggleNavHidden();
		expect(useWorkspaceStore.getState().navHidden).toBe(false);
	});

	it('opening a file preview closes the function tool', () => {
		useWorkspaceStore.setState({activeTool: 'terminal'});

		useExplorerStore.setState({selectedPath: 'src/a.ts'});

		expect(useWorkspaceStore.getState().activeTool).toBeNull();
	});

	it('opening a function tool closes the file preview', () => {
		useExplorerStore.setState({selectedPath: 'src/a.ts'});

		useWorkspaceStore.getState().setActiveTool('git');

		expect(useExplorerStore.getState().selectedPath).toBeNull();
		expect(useWorkspaceStore.getState().activeTool).toBe('git');
	});
});
