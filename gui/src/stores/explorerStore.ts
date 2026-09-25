import {create} from 'zustand';
import {
	listWorkspaceEntries,
	readWorkspaceFile,
	writeWorkspaceFile,
	type WorkspaceEntry,
	type WorkspaceFile,
} from '@/lib/api';
import {previewPathMatches} from '@/lib/toolFilePath';
import {samePath} from '@/lib/paths';
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
	directoryErrors: Record<string, string>;
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
	ensureDir: (path: string) => Promise<void>;
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
let treeSeq = 0;
let directoryRequestSeq = 0;
const directoryRequests = new Map<
	string,
	{token: number; promise: Promise<void>}
>();

function directoryRequestKey(root: string, path: string): string {
	return `${root}\0${path}`;
}

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
			samePath((parsed as {root: string}).root, root) &&
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
	directoryErrors: {},
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
		// 让未完成的 openFile 失效，避免已切换到工具面板后 loadingFile
		// 仍撑住预览槽，或迟到的文件响应重新回写已关闭的预览。
		openSeq += 1;
		set({
			selectedPath: null,
			doc: null,
			reviewDiff: null,
			previewExpanded: false,
			loadingFile: false,
		});
	},
	setPreviewExpanded(expanded) {
		set({previewExpanded: expanded});
	},
	async ensureRoot() {
		const root = activeRootPath();
		if (!root) {
			treeSeq += 1;
			openSeq += 1;
			reloadSeq += 1;
			directoryRequests.clear();
			set({
				error: '还没有打开文件夹。请先在左侧打开一个工作区。',
				childrenByPath: {},
				directoryErrors: {},
				expanded: {},
				rootName: '',
				loadedRoot: '',
				selectedPath: null,
				doc: null,
				reviewDiff: null,
				loadingTree: false,
				loadingFile: false,
			});
			return;
		}
		const current = get();
		if (samePath(current.loadedRoot, root) && current.childrenByPath['']) {
			return;
		}
		const seq = ++treeSeq;
		const switchingRoot = !samePath(current.loadedRoot, root);
		if (switchingRoot) {
			openSeq += 1;
			reloadSeq += 1;
			// 令旧工作区的目录请求失去写入资格；token 单调递增，切回同一路径
			// 时旧响应也不能冒充新请求。
			directoryRequests.clear();
		}
		set({
			loadingTree: true,
			error: null,
			...(switchingRoot
				? {
					childrenByPath: {},
					directoryErrors: {},
						expanded: {},
						rootName: '',
						loadedRoot: '',
						selectedPath: null,
						doc: null,
						reviewDiff: null,
						loadingFile: false,
						previewExpanded: false,
					}
				: {}),
		});
		try {
			const listing = await listWorkspaceEntries('', root);
			if (
				seq !== treeSeq ||
				!samePath(activeRootPath(), root)
			) {
				return;
			}
			// 默认收起根目录，避免重新打开工作区时整棵文件树全部展开（smoke-test #13）。
			// 用户随后手动展开的目录按工作区根持久化到 localStorage，跨重启恢复。
			const saved = loadExpandedForRoot(root);
			const expanded = saved ?? {'': false};
			saveExpandedForRoot(root, expanded);
			set({
				childrenByPath: {'': listing.entries},
				directoryErrors: {},
				rootName: listing.name || root.split(/[\\/]/).pop() || 'Workspace',
				expanded,
				loadingTree: false,
				loadedRoot: root,
			});
		} catch (err) {
			if (seq === treeSeq && samePath(activeRootPath(), root)) {
				set({
					loadingTree: false,
					error: err instanceof Error ? err.message : String(err),
				});
			}
		}
	},
	async ensureDir(path) {
		const key = path || '';
		const root = get().loadedRoot;
		if (!root || !samePath(root, activeRootPath())) {
			return;
		}
		if (get().childrenByPath[key] != null) {
			return;
		}
		const requestKey = directoryRequestKey(root, key);
		const pending = directoryRequests.get(requestKey);
		if (pending) {
			return pending.promise;
		}
		const token = ++directoryRequestSeq;
		set(s => {
			if (!(key in s.directoryErrors)) return s;
			const directoryErrors = {...s.directoryErrors};
			delete directoryErrors[key];
			return {directoryErrors};
		});
		const promise = Promise.resolve()
			.then(async () => {
				try {
					const listing = await listWorkspaceEntries(key, root);
					if (
						directoryRequests.get(requestKey)?.token !== token ||
						!samePath(root, get().loadedRoot) ||
						!samePath(root, activeRootPath())
					) {
						return;
					}
					set(s => ({
						childrenByPath: {
							...s.childrenByPath,
							[key]: listing.entries,
						},
						directoryErrors: Object.fromEntries(
							Object.entries(s.directoryErrors).filter(([dir]) => dir !== key),
						),
						...(key === ''
							? {rootName: listing.name || root.split(/[\\/]/).pop() || 'Workspace'}
							: {}),
					}));
				} catch (err) {
					if (
						directoryRequests.get(requestKey)?.token === token &&
						samePath(root, get().loadedRoot) &&
						samePath(root, activeRootPath())
					) {
						set(s => ({
							directoryErrors: {
								...s.directoryErrors,
								[key]: err instanceof Error ? err.message : String(err),
							},
						}));
					}
				}
			})
			.finally(() => {
				if (directoryRequests.get(requestKey)?.token === token) {
					directoryRequests.delete(requestKey);
				}
			});
		directoryRequests.set(requestKey, {token, promise});
		return promise;
	},
	async toggleDir(path) {
		const key = path;
		const was = Boolean(get().expanded[key]);
		if (
			was &&
			(get().childrenByPath[key] != null || get().directoryErrors[key] != null)
		) {
			const expanded = {...get().expanded, [key]: false};
			set({expanded});
			saveExpandedForRoot(get().loadedRoot, expanded);
			return;
		}
		if (!was) {
			const expanded = {...get().expanded, [key]: true};
			set({expanded});
			saveExpandedForRoot(get().loadedRoot, expanded);
		}
		await get().ensureDir(key);
	},
	async openFile(path) {
		const root = activeRootPath();
		if (!root) {
			return;
		}
		if (!samePath(get().loadedRoot, root)) {
			await get().ensureRoot();
			if (!samePath(get().loadedRoot, root) || !samePath(activeRootPath(), root)) {
				return;
			}
		}
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
			const doc = await readWorkspaceFile(path, root);
			if (
				openSeq !== seq ||
				get().selectedPath !== path ||
				!samePath(get().loadedRoot, root) ||
				!samePath(activeRootPath(), root)
			) {
				// 被更新的 openFile 或被 closePreview 抢先时，只撤自己仍拥有的加载旗；
				// 新请求的 loading 状态不能被旧响应覆盖。
				if (openSeq === seq) set({loadingFile: false});
				return;
			}
			set({doc, loadingFile: false});
			useCommandPaletteStore.getState().touchFile({
				path: doc.path || path,
				name: doc.name || path.split(/[\\/]/).pop() || path,
			});
		} catch (err) {
			if (
				openSeq !== seq ||
				get().selectedPath !== path ||
				!samePath(get().loadedRoot, root) ||
				!samePath(activeRootPath(), root)
			) {
				if (openSeq === seq) set({loadingFile: false});
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
		const root = activeRootPath();
		if (!root) {
			return;
		}
		if (!samePath(get().loadedRoot, root)) {
			await get().ensureRoot();
			if (!samePath(get().loadedRoot, root) || !samePath(activeRootPath(), root)) {
				return;
			}
		}
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
		const root = get().loadedRoot;
		if (!root || !samePath(root, activeRootPath())) {
			return false;
		}
		reloadSeq += 1;
		const seq = reloadSeq;
		try {
			const doc = await readWorkspaceFile(cur, root);
			if (
				seq !== reloadSeq ||
				get().selectedPath !== cur ||
				!samePath(root, get().loadedRoot) ||
				!samePath(root, activeRootPath())
			) {
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
		const root = get().loadedRoot;
		if (!root || !samePath(root, activeRootPath())) {
			throw new Error('工作区已切换，请重新打开文件');
		}
		const doc = await writeWorkspaceFile(path, text, root);
		if (
			get().selectedPath === path &&
			samePath(root, get().loadedRoot) &&
			samePath(root, activeRootPath())
		) {
			set({doc, error: null});
		}
	},
	async invalidateDir(path) {
		// P1-⑦：删除/新增文件后，失效该目录的 childrenByPath 快照，
		// 避免「已删除文件仍显示」的残留。若该目录当前展开，则立即重列；
		// 未展开的目录缓存清掉，下次展开 toggleDir 会重新拉取。
		const key = path || '';
		const state = get();
		const root = state.loadedRoot;
		const requestKey = root ? directoryRequestKey(root, key) : '';
		const had = key in state.childrenByPath;
		const hadError = key in state.directoryErrors;
		const wasPending = Boolean(requestKey && directoryRequests.delete(requestKey));
		if (!had && !hadError && !wasPending) {
			return;
		}
		const childrenByPath = {...state.childrenByPath};
		delete childrenByPath[key];
		const directoryErrors = {...state.directoryErrors};
		delete directoryErrors[key];
		set({childrenByPath, directoryErrors});
		// 仅当目录正处于展开态且缓存存在时才重列（避免不必要的网络/文件系统读）。
		if (get().expanded[key]) {
			if (!root || !samePath(root, activeRootPath())) {
				return;
			}
			await get().ensureDir(key);
		}
	},
}));
