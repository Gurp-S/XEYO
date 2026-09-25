import {create} from 'zustand';
import {fetchWorkspaceGraph, type WorkspaceGraph} from '@/lib/workspaceMapApi';
import {useChatStore} from '@/stores/chatStore';
import {samePath} from '@/lib/paths';

export type MapViewMode = 'architecture' | 'code' | 'turn' | 'authored';

export type AuthoredMapDoc = {
	kind: 'architecture' | 'workflow' | 'sequence' | 'dataflow' | 'lifecycle';
	title?: string;
	nodes: Array<{
		id: string;
		label: string;
		lane?: string;
		file?: string;
	}>;
	edges: Array<{from: string; to: string; label?: string}>;
};

type CodeMapState = {
	graph: WorkspaceGraph | null;
	loading: boolean;
	error: string | null;
	view: MapViewMode;
	query: string;
	selectedId: string | null;
	/** 图内卡片选中的节点（不触发文件预览 XOR）。 */
	cardId: string | null;
	cardKind: 'file' | 'package' | 'step' | 'symbol' | 'authored' | null;
	loadedRoot: string;
	authored: AuthoredMapDoc | null;
	/** 按需 LLM 摘要缓存（fileId → text）。 */
	summaries: Record<string, string>;
	summaryLoading: string | null;
	load: (root?: string) => Promise<void>;
	reload: () => Promise<void>;
	setView: (view: MapViewMode) => void;
	setQuery: (query: string) => void;
	setSelected: (id: string | null) => void;
	setCard: (
		id: string | null,
		kind?: CodeMapState['cardKind'],
	) => void;
	setAuthored: (doc: AuthoredMapDoc | null) => void;
	setSummary: (id: string, text: string) => void;
	setSummaryLoading: (id: string | null) => void;
};

function activeRootPath(): string {
	const st = useChatStore.getState();
	const space = st.spaces.find(s => s.id === st.activeSpaceId);
	return space?.rootPath?.trim() || '';
}

let loadSeq = 0;
/** 按需摘要硬顶，按插入序淘汰最旧，避免无限涨。 */
const SUMMARY_CAP = 24;

function withSummaryCap(
	prev: Record<string, string>,
	id: string,
	text: string,
): Record<string, string> {
	if (prev[id] === text) {
		return prev;
	}
	const next: Record<string, string> = {...prev};
	if (id in next) {
		delete next[id];
	}
	next[id] = text;
	const keys = Object.keys(next);
	if (keys.length <= SUMMARY_CAP) {
		return next;
	}
	const drop = keys.length - SUMMARY_CAP;
	for (let i = 0; i < drop; i += 1) {
		delete next[keys[i]!];
	}
	return next;
}

export const useCodeMapStore = create<CodeMapState>((set, get) => ({
	graph: null,
	loading: false,
	error: null,
	view: 'turn',
	query: '',
	selectedId: null,
	cardId: null,
	cardKind: null,
	loadedRoot: '',
	authored: null,
	summaries: {},
	summaryLoading: null,
	async load(root) {
		const cwd = (root ?? activeRootPath()).trim();
		// 每次请求意图都接管当前代次，包括空工作区和命中缓存的路径；否则较早的
		// 工作区请求可能在切走/切回后落盘，覆盖当前图，或留下错误的 loading 状态。
		loadSeq += 1;
		const seq = loadSeq;
		if (!cwd) {
			const cur = get();
			if (
				cur.error === '还没有打开文件夹。请先在左侧打开一个工作区。' &&
				!cur.graph &&
				!cur.loading
			) {
				return;
			}
			set({
				error: '还没有打开文件夹。请先在左侧打开一个工作区。',
				graph: null,
				loadedRoot: '',
				loading: false,
			});
			return;
		}
		if (samePath(get().loadedRoot, cwd) && get().graph && !get().error) {
			if (get().loading) {
				set({loading: false});
			}
			return;
		}
		set({loading: true, error: null});
		try {
			const graph = await fetchWorkspaceGraph({root: cwd});
			if (seq !== loadSeq) {
				return;
			}
			const rootChanged = !samePath(get().loadedRoot, cwd);
			set({
				graph,
				loading: false,
				loadedRoot: cwd,
				error: null,
				...(rootChanged ? {summaries: {}, summaryLoading: null} : {}),
			});
		} catch (err) {
			if (seq !== loadSeq) {
				return;
			}
			set({
				loading: false,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	},
	async reload() {
		loadSeq += 1;
		const seq = loadSeq;
		const cwd = (activeRootPath() || get().loadedRoot).trim();
		if (!cwd) {
			set({
				loading: false,
				error: '还没有打开文件夹。请先在左侧打开一个工作区。',
				graph: null,
				loadedRoot: '',
			});
			return;
		}
		set({loading: true, error: null});
		try {
			const graph = await fetchWorkspaceGraph({refresh: true, root: cwd});
			if (seq !== loadSeq) {
				return;
			}
			set({
				graph,
				loading: false,
				loadedRoot: cwd || graph.cwd,
				error: null,
				summaries: {},
				summaryLoading: null,
			});
		} catch (err) {
			if (seq !== loadSeq) {
				return;
			}
			set({
				loading: false,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	},
	setView(view) {
		// 清掉 query：架构点包钻进代码时会把 pkg id 写入 query，
		// 不清会导致切回架构被 filterGraph 滤成单节点。
		set({
			view,
			query: '',
			selectedId: null,
			cardId: null,
			cardKind: null,
		});
	},
	setQuery(query) {
		set({query});
	},
	setSelected(id) {
		set({selectedId: id});
	},
	setCard(id, kind = null) {
		set({cardId: id, cardKind: id ? kind : null, selectedId: id});
	},
	setAuthored(doc) {
		set({
			authored: doc,
			...(doc ? {view: 'authored' as const} : {}),
		});
	},
	setSummary(id, text) {
		set(s => ({
			summaries: withSummaryCap(s.summaries, id, text),
			summaryLoading: s.summaryLoading === id ? null : s.summaryLoading,
		}));
	},
	setSummaryLoading(id) {
		set({summaryLoading: id});
	},
}));
