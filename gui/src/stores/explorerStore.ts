import {create} from 'zustand';
import {
	listWorkspaceEntries,
	readWorkspaceFile,
	writeWorkspaceFile,
	setWorkspace,
	type WorkspaceEntry,
	type WorkspaceFile,
} from '@/lib/api';
import {previewPathMatches} from '@/lib/toolFilePath';
import {useChatStore} from '@/stores/chatStore';
import {useCommandPaletteStore} from '@/stores/commandPaletteStore';

export type ReviewDiff = {
	path: string;
	name: string;
	diff: string;
};

type ExplorerState = {
	open: boolean;
	expanded: Record<string, boolean>;
	childrenByPath: Record<string, WorkspaceEntry[]>;
	selectedPath: string | null;
	doc: WorkspaceFile | null;
	reviewDiff: ReviewDiff | null;
	/** 预览覆盖聊天列（放大展示）；不持久化。 */
	previewExpanded: boolean;
	loadingTree: boolean;
	loadingFile: boolean;
	error: string | null;
	rootName: string;
	loadedRoot: string;
	toggle: () => void;
	setOpen: (open: boolean) => void;
	closePreview: () => void;
	setPreviewExpanded: (expanded: boolean) => void;
	ensureRoot: () => Promise<void>;
	toggleDir: (path: string) => Promise<void>;
	openFile: (path: string) => Promise<void>;
	openReview: (file: ReviewDiff) => Promise<void>;
	reloadIfOpen: (path: string) => Promise<boolean>;
	saveFile: (path: string, text: string) => Promise<void>;
	/** 失效某目录的快照；若该目录当前展开则重列（P1-⑦：删除/新增文件后文件树残留）。 */
	invalidateDir: (path: string) => Promise<void>;
};

let openSeq = 0;
let reloadSeq = 0;

/* ---- 展开状态持久化（smoke-test #13）：跨重启/重开工作区保留用户手工展开的目录。
   key 绑定工作区根路径；根切换时旧展开不套用。 ---- */
const EXPANDED_KEY = 'xeyo.explorer_expanded.v1';

function loadExpandedForRoot(root: string): Record<string, boolean> | null {
	try {
		const raw = globalThis.localStorage?.getItem(EXPANDED_KEY) ?? null;
		if (!raw) return null;
		const parsed = JSON.parse(raw) as unknown;
		if (
			parsed &&
			typeof parsed === 'object' &&
			typeof (parsed as {root?: unknown}).root === 'string' &&
			(parsed as {root: string}).root === root &&
			(parsed as {expanded?: unknown}).expanded &&
			typeof (parsed as {expanded: unknown}).expanded === 'object'
		) {
			const map = (parsed as {expanded: Record<string, boolean>}).expanded;
			return Object.fromEntries(
				Object.entries(map).filter(([, v]) => typeof v === 'boolean'),
			);
		}
		return null;
	} catch {
		return null;
	}
}

function saveExpandedForRoot(root: string, expanded: Record<string, boolean>): void {
	try {
		globalThis.localStorage?.setItem(
			EXPANDED_KEY,
			JSON.stringify({root, expanded}),
		);
	} catch {
		// 存储不可用（隐私模式/已满）：仅放弃持久化
	}
}

function activeRootPath(): string {
	const st = useChatStore.getState();
	const space = st.spaces.find(s => s.id === st.activeSpaceId);
	return space?.rootPath?.trim() || '';
}

/** 内容未变则跳过 set，避免 Prism / Markdown 无效重绘。 */
export function workspaceFileUnchanged(
	prev: WorkspaceFile | null,
	next: WorkspaceFile,
): boolean {
	if (!prev) {
		return false;
	}
	if (
		prev.path === next.path &&
		prev.kind === next.kind &&
		prev.size === next.size &&
		prev.mtime != null &&
		next.mtime != null &&
		prev.mtime === next.mtime
	) {
		return true;
	}
	if (prev.kind !== next.kind || prev.path !== next.path) {
		return false;
	}
	if (next.kind === 'image') {
		return prev.data_url === next.data_url && prev.size === next.size;
	}
	if (next.kind === 'binary') {
		return prev.text === next.text && prev.size === next.size;
	}
	return (
		prev.text === next.text &&
		prev.size === next.size &&
		Boolean(prev.truncated) === Boolean(next.truncated)
	);
}

export const useExplorerStore = create<ExplorerState>((set, get) => ({
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
	toggle() {
		const next = !get().open;
		set({open: next});
		if (next) {
			void get().ensureRoot();
		}
	},
	setOpen(open) {
		set({open});
		if (open) {
			void get().ensureRoot();
		}
	},
	closePreview() {
		set({
			selectedPath: null,
			doc: null,
			reviewDiff: null,
			previewExpanded: false,
		});
	},
	setPreviewExpanded(expanded) {
		set({previewExpanded: expanded});
	},
	async ensureRoot() {
		const root = activeRootPath();
		if (!root) {
			set({
				error: '还没有打开文件夹。请先在左侧打开一个工作区。',
				childrenByPath: {},
				rootName: '',
				loadedRoot: '',
			});
			return;
		}
		if (get().loadedRoot === root && get().childrenByPath['']) {
			return;
		}
		set({loadingTree: true, error: null});
		try {
			await setWorkspace(root);
			const listing = await listWorkspaceEntries('');
			// 默认收起根目录，避免重新打开工作区时整棵文件树全部展开（smoke-test #13）。
			// 用户随后手动展开的目录按工作区根持久化到 localStorage，跨重启恢复。
			const saved = loadExpandedForRoot(root);
			const expanded = saved ?? {'': false};
			saveExpandedForRoot(root, expanded);
			set({
				childrenByPath: {'': listing.entries},
				rootName: listing.name || root.split(/[\\/]/).pop() || 'Workspace',
				expanded,
				loadingTree: false,
				loadedRoot: root,
			});
		} catch (err) {
			set({
				loadingTree: false,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	},
	async toggleDir(path) {
		const key = path;
		const was = Boolean(get().expanded[key]);
		if (was) {
			const expanded = {...get().expanded, [key]: false};
			set({expanded});
			saveExpandedForRoot(get().loadedRoot, expanded);
			return;
		}
		const expanded = {...get().expanded, [key]: true};
		set({expanded});
		saveExpandedForRoot(get().loadedRoot, expanded);
		if (get().childrenByPath[key]) {
			return;
		}
		try {
			const listing = await listWorkspaceEntries(key);
			if (!get().expanded[key]) {
				return;
			}
			set({
				childrenByPath: {
					...get().childrenByPath,
					[key]: listing.entries,
				},
			});
		} catch (err) {
			set({
				expanded: {...get().expanded, [key]: false},
				error: err instanceof Error ? err.message : String(err),
			});
		}
	},
	async openFile(path) {
		openSeq += 1;
		const seq = openSeq;
		const keepReview = get().reviewDiff?.path === path;
		set({
			selectedPath: path,
			loadingFile: true,
			error: null,
			...(keepReview ? {} : {reviewDiff: null}),
		});
		try {
			const doc = await readWorkspaceFile(path);
			if (openSeq !== seq || get().selectedPath !== path) {
				return;
			}
			set({doc, loadingFile: false});
			useCommandPaletteStore.getState().touchFile({
				path: doc.path || path,
				name: doc.name || path.split(/[\\/]/).pop() || path,
			});
		} catch (err) {
			if (openSeq !== seq || get().selectedPath !== path) {
				return;
			}
			set({
				loadingFile: false,
				doc: null,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	},
	async openReview(file) {
		set({
			selectedPath: file.path,
			reviewDiff: file,
			error: null,
		});
		await get().openFile(file.path);
	},
	async reloadIfOpen(path) {
		const cur = get().selectedPath;
		if (!cur || !previewPathMatches(cur, path)) {
			return false;
		}
		reloadSeq += 1;
		const seq = reloadSeq;
		try {
			const doc = await readWorkspaceFile(cur);
			if (seq !== reloadSeq || get().selectedPath !== cur) {
				return false;
			}
			if (workspaceFileUnchanged(get().doc, doc)) {
				return false;
			}
			set({doc, error: null});
			return true;
		} catch {
			/* 预览保持现状 */
			return false;
		}
	},
	async saveFile(path, text) {
		const doc = await writeWorkspaceFile(path, text);
		if (get().selectedPath === path) {
			set({doc, error: null});
		}
	},
	async invalidateDir(path) {
		// P1-⑦：删除/新增文件后，失效该目录的 childrenByPath 快照，
		// 避免「已删除文件仍显示」的残留。若该目录当前展开，则立即重列；
		// 未展开的目录缓存清掉，下次展开 toggleDir 会重新拉取。
		const key = path || '';
		const had = key in get().childrenByPath;
		if (!had) {
			return;
		}
		const childrenByPath = {...get().childrenByPath};
		delete childrenByPath[key];
		set({childrenByPath});
		// 仅当目录正处于展开态且缓存存在时才重列（避免不必要的网络/文件系统读）。
		if (get().expanded[key]) {
			try {
				const listing = await listWorkspaceEntries(key);
				if (!get().expanded[key]) {
					return;
				}
				set({
					childrenByPath: {
						...get().childrenByPath,
						[key]: listing.entries,
					},
				});
			} catch (err) {
				set({
					expanded: {...get().expanded, [key]: false},
					error: err instanceof Error ? err.message : String(err),
				});
			}
		}
	},
}));
