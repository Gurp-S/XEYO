import {beforeEach, describe, expect, it, vi} from 'vitest';

const listWorkspaceEntries = vi.fn();
const setWorkspace = vi.fn();
const readWorkspaceFile = vi.fn();
const writeWorkspaceFile = vi.fn();

vi.mock('@/lib/api', () => ({
	listWorkspaceEntries: (...args: unknown[]) => listWorkspaceEntries(...args),
	readWorkspaceFile: (...args: unknown[]) => readWorkspaceFile(...args),
	writeWorkspaceFile: (...args: unknown[]) => writeWorkspaceFile(...args),
	setWorkspace: (...args: unknown[]) => setWorkspace(...args),
}));

vi.mock('@/stores/chatStore', () => ({
	useChatStore: {
		getState: () => ({
			activeSpaceId: 's1',
			spaces: [{id: 's1', rootPath: 'D:/proj', name: 'proj'}],
		}),
	},
}));

vi.mock('@/stores/commandPaletteStore', () => ({
	useCommandPaletteStore: {
		getState: () => ({
			touchFile: vi.fn(),
		}),
	},
}));

import {
	useExplorerStore,
	workspaceFileUnchanged,
} from './explorerStore';

describe('explorerStore', () => {
	beforeEach(() => {
		listWorkspaceEntries.mockReset();
		setWorkspace.mockReset();
		readWorkspaceFile.mockReset();
		writeWorkspaceFile.mockReset();
		useExplorerStore.setState({
			open: false,
			expanded: {},
			childrenByPath: {},
			selectedPath: null,
			doc: null,
			reviewDiff: null,
			previewExpanded: false,
			loadingTree: false,
			loadingFile: false,
			error: null,
			rootName: '',
			loadedRoot: '',
		});
	});

	it('ensureRoot skips disk when the same workspace is already loaded', async () => {
		listWorkspaceEntries.mockResolvedValue({
			name: 'proj',
			entries: [{kind: 'file', name: 'a.ts', path: 'a.ts'}],
		});
		await useExplorerStore.getState().ensureRoot();
		await useExplorerStore.getState().ensureRoot();
		expect(listWorkspaceEntries).toHaveBeenCalledTimes(1);
	});

	it('toggleDir expands before listing children', async () => {
		let resolveList: (v: unknown) => void = () => undefined;
		listWorkspaceEntries.mockImplementation(
			() =>
				new Promise(r => {
					resolveList = r;
				}),
		);
		const pending = useExplorerStore.getState().toggleDir('src');
		expect(useExplorerStore.getState().expanded.src).toBe(true);
		expect(useExplorerStore.getState().loadingTree).toBe(false);
		resolveList({name: 'src', entries: []});
		await pending;
	});

	it('closePreview clears previewExpanded', () => {
		useExplorerStore.setState({
			selectedPath: 'a.ts',
			previewExpanded: true,
			doc: {
				cwd: 'D:/proj',
				path: 'a.ts',
				name: 'a.ts',
				mime: 'text/plain',
				size: 1,
				mtime: 1,
				kind: 'text',
				text: 'x',
			},
		});
		useExplorerStore.getState().closePreview();
		expect(useExplorerStore.getState().selectedPath).toBeNull();
		expect(useExplorerStore.getState().previewExpanded).toBe(false);
		expect(useExplorerStore.getState().doc).toBeNull();
	});

	it('reloadIfOpen skips set when content is unchanged', async () => {
		const doc = {
			cwd: 'D:/proj',
			path: 'a.ts',
			name: 'a.ts',
			mime: 'text/plain',
			size: 3,
			mtime: 100,
			kind: 'text' as const,
			text: 'abc',
		};
		useExplorerStore.setState({selectedPath: 'a.ts', doc});
		readWorkspaceFile.mockResolvedValue({...doc});
		const changed = await useExplorerStore.getState().reloadIfOpen('a.ts');
		expect(changed).toBe(false);
		expect(useExplorerStore.getState().doc).toBe(doc);
	});

	it('reloadIfOpen updates when content changes', async () => {
		const prev = {
			cwd: 'D:/proj',
			path: 'a.ts',
			name: 'a.ts',
			mime: 'text/plain',
			size: 3,
			mtime: 100,
			kind: 'text' as const,
			text: 'abc',
		};
		const next = {...prev, text: 'abcd', size: 4, mtime: 200};
		useExplorerStore.setState({selectedPath: 'a.ts', doc: prev});
		readWorkspaceFile.mockResolvedValue(next);
		const changed = await useExplorerStore
			.getState()
			.reloadIfOpen('D:/proj/a.ts');
		expect(changed).toBe(true);
		expect(useExplorerStore.getState().doc?.text).toBe('abcd');
	});

	it('reloadIfOpen ignores unrelated paths', async () => {
		useExplorerStore.setState({
			selectedPath: 'a.ts',
			doc: {
				cwd: 'D:/proj',
				path: 'a.ts',
				name: 'a.ts',
				mime: 'text/plain',
				size: 1,
				kind: 'text',
				text: 'x',
			},
		});
		const changed = await useExplorerStore.getState().reloadIfOpen('b.ts');
		expect(changed).toBe(false);
		expect(readWorkspaceFile).not.toHaveBeenCalled();
	});
});

describe('workspaceFileUnchanged', () => {
	it('treats same mtime/size as unchanged', () => {
		const a = {
			cwd: 'D:/proj',
			path: 'a.ts',
			name: 'a.ts',
			mime: 'text/plain',
			size: 3,
			mtime: 100,
			kind: 'text' as const,
			text: 'abc',
		};
		expect(workspaceFileUnchanged(a, {...a, text: 'different'})).toBe(true);
	});

	it('compares text when mtime missing', () => {
		const a = {
			cwd: 'D:/proj',
			path: 'a.ts',
			name: 'a.ts',
			mime: 'text/plain',
			size: 3,
			kind: 'text' as const,
			text: 'abc',
		};
		expect(workspaceFileUnchanged(a, {...a})).toBe(true);
		expect(workspaceFileUnchanged(a, {...a, text: 'xyz'})).toBe(false);
	});

	it('invalidateDir drops a cached dir snapshot and relists it when expanded', async () => {
		// 预置：根展开，src 目录已列（含已删文件残留）。
		useExplorerStore.setState({
			loadedRoot: 'D:/proj',
			expanded: {'': true, src: true},
			childrenByPath: {
				'': [
					{kind: 'dir', name: 'src', path: 'src'},
				],
				src: [
					{kind: 'file', name: 'deleted.ts', path: 'src/deleted.ts'},
				],
			},
		});
		// 删除文件后重列 src → 不再含残留。
		listWorkspaceEntries.mockImplementation(async (dir: string) => {
			if (dir === 'src') {
				return {name: 'src', entries: []};
			}
			return {name: 'proj', entries: [{kind: 'dir', name: 'src', path: 'src'}]};
		});
		await useExplorerStore.getState().invalidateDir('src');
		// 展开的目录会被立即重列为空，残留的 deleted.ts 消失。
		await vi.waitFor(() => {
			expect(useExplorerStore.getState().childrenByPath['src']).toEqual([]);
		});
	});

	it('invalidateDir on an uncached dir is a no-op', async () => {
		useExplorerStore.setState({childrenByPath: {}});
		listWorkspaceEntries.mockClear();
		await useExplorerStore.getState().invalidateDir('nope');
		expect(listWorkspaceEntries).not.toHaveBeenCalled();
	});
});
