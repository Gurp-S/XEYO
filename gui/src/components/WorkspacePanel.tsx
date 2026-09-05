import {memo, useEffect, useMemo, useRef, useState, type ComponentType, type MouseEvent as ReactMouseEvent, type ReactNode} from 'react';
import {
	ChevronRight,
	ChevronsUpDown,
	Folder,
	GitBranch,
	History,
	GitCommitHorizontal,
	Boxes,
	Terminal,
	FileText,
	TerminalSquare,
	PanelRight,
	Map,
	Globe,
} from 'lucide-react';
import {PaneResizeHandle} from '@/components/PaneResizeHandle';
import {PaneSlot} from '@/components/PaneSlot';
import {showContextMenu} from '@/components/ui/ContextMenu';
import type {WorkspaceEntry} from '@/lib/api';
import {cn} from '@/lib/utils';
import {filePathMenuItems} from '@/lib/contextMenus';
import {joinWorkspacePath} from '@/lib/workspaceOpen';
import {useHoverScroll} from '@/hooks/useHoverScroll';
import {usePaneResize} from '@/hooks/usePaneResize';
import {usePresence} from '@/hooks/usePresence';
import {useChatStore} from '@/stores/chatStore';
import {useExplorerStore} from '@/stores/explorerStore';
import {useSettingsStore, PANE_WIDTH_MAX, PANE_WIDTH_MIN, isSmoothnessOn} from '@/stores/settingsStore';
import {useWorkspaceStore, type WorkspaceSection, type WorkspaceTool} from '@/stores/workspaceStore';
import {usePaneViewportClamp} from '@/hooks/paneViewportClamp';
import {
	gitBranches,
	gitLog,
	gitStatus,
	fetchWorkspaceJournal,
	type GitBranchesResult,
	type GitLogResult,
	type GitStatusResult,
	type JournalChange,
} from '@/lib/api';
import {collectChangedFilesFromItems, type ChangedFile} from '@/lib/toolActivity';
import {groupTranscript, type TurnItem} from '@/lib/groupTranscript';
import {useIconTheme} from '@/lib/iconThemeLoader';
import type {ChatMessage, ChatSession} from '@/lib/types';

type Icon = ComponentType<{className?: string; strokeWidth?: number}>;

/* ==== 顶层入口：文件夹根目录/审查/git=可展开树；终端=功能节点（滑出右侧面板）==== */
type TopEntry =
	| {key: WorkspaceSection; label: string; Icon: Icon; kind: 'tree'}
	| {key: WorkspaceSection; label: string; Icon: Icon; kind: 'func'; func: WorkspaceTool};

const TOP_ENTRIES: TopEntry[] = [
	{key: 'files', label: '文件夹根目录', Icon: Folder, kind: 'tree'},
	{key: 'history', label: '审查', Icon: History, kind: 'tree'},
	{key: 'git', label: 'git', Icon: GitBranch, kind: 'tree'},
	{key: 'map', label: '地图', Icon: Map, kind: 'func', func: 'map'},
	{key: 'terminal', label: '终端', Icon: Terminal, kind: 'func', func: 'terminal'},
	{key: 'browser', label: '浏览器', Icon: Globe, kind: 'func', func: 'browser'},
];

function SectionIcon({entry}: {entry: WorkspaceEntry}) {
	const mod = useIconTheme();
	if (!mod) {
		return null;
	}
	const ext = entry.name.includes('.') ? (entry.name.split('.').pop()?.toLowerCase() ?? '') : '';
	const icon = mod.getFileIcon({
		fileExtension: ext || undefined,
		fileName: entry.name,
		fallback: entry.kind === 'dir' ? 'folder' : 'file',
	});
	return <mod.MaterialIcon name={icon} size={16} />;
}

/* 可展开容器：grid-rows 高度过渡（与左侧侧边栏完全一致，动画随设置 smoothness 开/关） */
function TreeChildren({open, children}: {open: boolean; children: ReactNode}) {
	return (
		<div className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')} aria-hidden={!open}>
			<ul className="min-h-0 overflow-hidden">{children}</ul>
		</div>
	);
}

function Row({
	depth,
	open,
	active,
	chev,
	onClick,
	onContextMenu,
	role,
	ariaLevel,
	ariaExpanded,
	children,
}: {
	depth: number;
	open?: boolean;
	active?: boolean;
	chev?: boolean;
	onClick?: () => void;
	onContextMenu?: (event: ReactMouseEvent) => void;
	role?: string;
	ariaLevel?: number;
	ariaExpanded?: boolean;
	children: ReactNode;
}) {
	return (
		<li>
			<button
				type="button"
				onClick={onClick}
				onContextMenu={onContextMenu}
				role={role}
				aria-level={ariaLevel}
				aria-expanded={ariaExpanded}
				className={cn(
					'xy-pressable flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13px] transition-colors',
					active ? 'bg-glass-strong font-medium text-ink' : 'text-ink-soft hover:bg-glass-hover hover:text-ink',
				)}
				style={{paddingLeft: 8 + depth * 12}}
			>
				<span className="flex w-3.5 shrink-0 items-center justify-center text-mute">
					{chev ? (
						<ChevronRight
							className={cn('h-3.5 w-3.5 transition-transform duration-150', open && 'rotate-90')}
							strokeWidth={1.8}
						/>
					) : (
						<span className="w-3.5" />
					)}
				</span>
				{children}
			</button>
		</li>
	);
}

function fileEntryMenuItems(
	entry: WorkspaceEntry,
	absolutePath: string,
	onOpen: () => void,
) {
	return filePathMenuItems({
		entryPath: entry.path,
		entryName: entry.name,
		absolutePath,
		kind: entry.kind,
		onOpen,
	});
}

/* ==== 项目文件树（复用 explorerStore，目录展开/收起带平滑动画）==== */
/* 每个文件行独立订阅 store 的展开/选中状态：任一状态变化只重渲染受影响行，
   目录展开/收起不再触发整棵文件树重渲染（大目录打开不卡顿）。 */
const FileRow = memo(function FileRow({entry, depth}: {entry: WorkspaceEntry; depth: number}) {
	const isDir = entry.kind === 'dir';
	const isOpen = useExplorerStore(s => Boolean(s.expanded[entry.path]));
	const isSel = useExplorerStore(s => s.selectedPath === entry.path);
	const toggleDir = useExplorerStore(s => s.toggleDir);
	const openFile = useExplorerStore(s => s.openFile);
	const rootPath = useChatStore(s => {
		const space = s.spaces.find(sp => sp.id === s.activeSpaceId);
		return space?.rootPath ?? '';
	});

	const open = () => {
		if (isDir) void toggleDir(entry.path);
		else void openFile(entry.path);
	};

	const onContextMenu = (event: ReactMouseEvent) => {
		const absolutePath = joinWorkspacePath(rootPath, entry.path);
		showContextMenu(
			event,
			fileEntryMenuItems(entry, absolutePath, open),
			`${entry.name} 文件操作`,
		);
	};

	return (
		<div>
			<Row
				depth={depth}
				open={isOpen}
				active={isSel}
				chev={isDir}
				role="treeitem"
				ariaLevel={depth}
				ariaExpanded={isDir ? isOpen : undefined}
				onClick={open}
				onContextMenu={onContextMenu}
			>
				<span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
					<SectionIcon entry={entry} />
				</span>
				<span className="min-w-0 flex-1 truncate">{entry.name}</span>
			</Row>
			{isDir ? (
				<TreeChildren open={isOpen}>
					<FileRows parent={entry.path} depth={depth + 1} />
				</TreeChildren>
			) : null}
		</div>
	);
});

/* 超大目录分页懒渲染：单页最多 PAGE_SIZE 行，点击“显示更多”再补一段，
   首屏与逐段渲染恒定成本，避免一次性渲染千行导致卡顿。 */
const FILE_PAGE_SIZE = 300;

function FileRows({parent, depth}: {parent: string; depth: number}) {
	const entries = useExplorerStore(s => s.childrenByPath[parent]);
	const [limit, setLimit] = useState(FILE_PAGE_SIZE);

	useEffect(() => {
		setLimit(FILE_PAGE_SIZE);
	}, [parent]);

	const all = entries ?? [];
	const loading = entries == null;
	const visible = all.slice(0, limit);
	const rest = all.length - visible.length;

	return (
		<>
			{loading ? (
				<li className="px-7 py-1">
					<span className="inline-block h-2.5 w-24 animate-pulse rounded bg-glass-strong" />
				</li>
			) : null}
			{visible.map(entry => (
				<FileRow key={entry.path} entry={entry} depth={depth} />
			))}
			{rest > 0 ? (
				<li className="px-7 py-1">
					<button
						type="button"
						className="w-full text-left font-mono text-[10px] text-mute hover:text-ink-soft"
						onClick={() => setLimit(l => l + FILE_PAGE_SIZE)}
					>
						显示更多 {rest} 项
					</button>
				</li>
			) : null}
		</>
	);
}

function FilesTree() {
	const ensureRoot = useExplorerStore(s => s.ensureRoot);
	const error = useExplorerStore(s => s.error);
	const rootLoaded = useExplorerStore(s => s.childrenByPath[''] != null);
	// chatStore 异步 hydrate：挂载时空间可能尚未还原（activeRootPath 为空），
	// ensureRoot 会静默失败；hydrate 完成或工作区切换后必须重试。
	const hydrated = useChatStore(s => s.hydrated);
	const rootPath = useChatStore(s => {
		const space = s.spaces.find(sp => sp.id === s.activeSpaceId);
		return space?.rootPath ?? '';
	});

	useEffect(() => {
		void ensureRoot();
	}, [hydrated, rootPath, ensureRoot]);

	return (
		<>
			{error && !rootLoaded ? (
				<li className="px-7 py-1 font-mono text-[11px] text-danger">
					文件树加载失败：{error}
				</li>
			) : null}
			<FileRows parent="" depth={1} />
		</>
	);
}

/* ==== 工作区变更：跨 agent 的共享 journal 只读流（多 Agent 可见性）==== */
function timeAgo(ts: number): string {
	if (!ts || Number.isNaN(ts)) return '';
	const diff = Math.max(0, Date.now() / 1000 - ts);
	if (diff < 60) return '刚刚';
	if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
	if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
	return `${Math.floor(diff / 86400)}天前`;
}

function JournalRow({change, depth}: {change: JournalChange; depth: number}) {
	const openFile = useExplorerStore(s => s.openFile);
	const openReview = useExplorerStore(s => s.openReview);
	const isSel = useExplorerStore(s => s.selectedPath === change.path);
	const rootPath = useChatStore(s => {
		const space = s.spaces.find(sp => sp.id === s.activeSpaceId);
		return space?.rootPath ?? '';
	});
	const label = change.brief ? ` — ${change.brief}` : '';
	const stale = change.conflict_task ? ' [stale]' : '';
	const fileName = change.path.split(/[\\/]/).pop() || change.path;
	const hasDiff = Boolean(change.diff);
	const open = () => {
		if (hasDiff) void openReview({path: change.path, name: fileName, diff: change.diff});
		else void openFile(change.path);
	};
	const openDiff = () => {
		if (hasDiff) void openReview({path: change.path, name: fileName, diff: change.diff});
	};
	const onContextMenu = (event: ReactMouseEvent) => {
		showContextMenu(
			event,
			filePathMenuItems({
				entryPath: change.path,
				entryName: fileName,
				absolutePath: joinWorkspacePath(rootPath, change.path),
				kind: 'file',
				onOpen: open,
				...(hasDiff ? {onOpenReview: openDiff} : {}),
			}),
			`${fileName} 文件操作`,
		);
	};
	return (
		<Row
			depth={depth}
			active={isSel}
			role="treeitem"
			ariaLevel={depth}
			onClick={open}
			onContextMenu={onContextMenu}
		>
			<FileText
				className={cn(
					'h-3.5 w-3.5 shrink-0',
					change.syntax_valid ? 'text-mute' : 'text-danger',
				)}
				strokeWidth={1.8}
			/>
			<span className="min-w-0 flex-1 truncate font-mono text-[11px]">{change.path}</span>
			<span className="shrink-0 font-mono text-[10px] text-mute">
				{change.agent_id || '?'}:{change.action}
				{stale}
			</span>
			<span className="shrink-0 font-mono text-[10px] text-mute/70">{timeAgo(change.ts)}</span>
			{label ? <span className="shrink-0 max-w-24 truncate text-[10px] text-mute">{label}</span> : null}
		</Row>
	);
}

function JournalTree() {
	const hydrated = useChatStore(s => s.hydrated);
	const rootPath = useChatStore(s => {
		const space = s.spaces.find(sp => sp.id === s.activeSpaceId);
		return space?.rootPath ?? '';
	});
	const [changes, setChanges] = useState<JournalChange[]>([]);
	const [loaded, setLoaded] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let disposed = false;
		setLoaded(false);
		void (async () => {
			try {
				const res = await fetchWorkspaceJournal({limit: 50});
				if (!disposed) {
					setChanges(res.changes);
					setError(null);
				}
			} catch (err) {
				if (!disposed) setError(err instanceof Error ? err.message : String(err));
			} finally {
				if (!disposed) setLoaded(true);
			}
		})();
		return () => {
			disposed = true;
		};
	}, [hydrated, rootPath]);

	return (
		<>
			{!loaded ? (
				<li className="px-7 py-1">
					<span className="inline-block h-2.5 w-24 animate-pulse rounded bg-glass-strong" />
				</li>
			) : error ? (
				<li className="px-7 py-1 font-mono text-[11px] text-mute/70">变更流加载失败</li>
			) : changes.length === 0 ? (
				<li className="px-7 py-1 font-mono text-[11px] text-mute/70">暂无变更</li>
			) : (
				<PagedRows
					items={changes}
					empty={<li className="px-7 py-1 font-mono text-[11px] text-mute/70">暂无变更</li>}
					renderItem={c => <JournalRow key={c.seq} change={c} depth={2} />}
				/>
			)}
		</>
	);
}

/* ==== 审查：以对话为树，含 历史diff / 历史命令行 ==== */
function collectChangedFor(
	sessions: ChatSession[],
	messagesById: Record<string, ChatMessage[]>,
): Array<{
	session: ChatSession;
	changed: ChangedFile[];
	commands: Array<{name: string; input: string}>;
}> {
	return sessions
		.map(session => {
			const msgs = messagesById[session.id] ?? [];
			let changed: ChangedFile[] = [];
			let commands: Array<{name: string; input: string}> = [];
			try {
				const blocks = groupTranscript(msgs);
				const items = blocks.flatMap(b => (b.kind === 'turn' ? b.items : []));
				changed = collectChangedFilesFromItems(items);
				commands = items
					.filter((it): it is Extract<TurnItem, {kind: 'tool'}> => it.kind === 'tool')
					.filter(it => it.tool.name && it.tool.input)
					.map(it => ({name: it.tool.name, input: it.tool.input}));
			} catch {
				/* 保持空 */
			}
			return {session, changed, commands};
		})
		.filter(b => b.changed.length > 0 || b.commands.length > 0);
}

function sessionMessagesKey(sessionId: string, msgs: ChatMessage[] | undefined): string {
	if (!msgs) {
		return `${sessionId}:0;`;
	}
	let sig = `${sessionId}:${msgs.length}`;
	for (let i = 0; i < msgs.length; i += 1) {
		const m = msgs[i];
		if (m.toolStatus != null) {
			sig += `,${m.id}${m.toolStatus}${m.text.length}`;
		}
	}
	return `${sig};`;
}

function reviewMessagesKey(sessions: ChatSession[], messagesById: Record<string, ChatMessage[]>): string {
	const win = sessions.length > 60 ? sessions.slice(-60) : sessions;
	let sig = '';
	for (const session of win) {
		sig += sessionMessagesKey(session.id, messagesById[session.id]);
	}
	return sig;
}

/* 单页行数上限：diff / 命令列表超长时按段渲染，长会话不再一次性产出几十上百行。 */
const REVIEW_PAGE_SIZE = 40;

/** 当前对话的命令条数（与「历史命令」功能界面同源口径）。 */
function countCommands(messages: ChatMessage[]): number {
	try {
		const blocks = groupTranscript(messages);
		const items = blocks.flatMap(b => (b.kind === 'turn' ? b.items : []));
		return items.filter(
			(it): it is Extract<TurnItem, {kind: 'tool'}> =>
				it.kind === 'tool' && Boolean(it.tool.name && it.tool.input),
		).length;
	} catch {
		return 0;
	}
}

function PagedRows<T>({
	items,
	renderItem,
	empty,
}: {
	items: T[];
	renderItem: (item: T, index: number) => ReactNode;
	empty: ReactNode;
}) {
	const [limit, setLimit] = useState(REVIEW_PAGE_SIZE);

	return (
		<>
			{items.length === 0 ? empty : null}
			{items.slice(0, limit).map(renderItem)}
			{items.length - limit > 0 ? (
				<li className="px-7 py-1">
					<button
						type="button"
						className="w-full text-left font-mono text-[10px] text-mute hover:text-ink-soft"
						onClick={() => setLimit(l => l + REVIEW_PAGE_SIZE)}
					>
						显示更多 {items.length - limit} 项
					</button>
				</li>
			) : null}
		</>
	);
}

function ReviewTree() {
	const sessions = useChatStore(s => s.sessions);
	const activeId = useChatStore(s => s.activeId);
	const branchesKey = useChatStore(s => reviewMessagesKey(s.sessions, s.messagesById));
	const activeKey = useChatStore(s =>
		s.activeId ? sessionMessagesKey(s.activeId, s.messagesById[s.activeId]) : '',
	);
	const selectedPath = useExplorerStore(s => s.selectedPath);
	const openReview = useExplorerStore(s => s.openReview);
	const setActiveTool = useWorkspaceStore(s => s.setActiveTool);

	const [open, setOpen] = useState<Record<string, boolean>>({});
	// P2-⑧：默认收起。此前 journalOpen 默认 true + isOpen 用 `open[id] !== false`，
	// 导致点开「审查」整棵树全层展开。改为显式开才开、变更流默认收起。
	const [journalOpen, setJournalOpen] = useState(false);
	const branchesCache = useRef<{
		key: string;
		sessions: ChatSession[];
		value: ReturnType<typeof collectChangedFor>;
	} | null>(null);
	if (
		!branchesCache.current ||
		branchesCache.current.key !== branchesKey ||
		branchesCache.current.sessions !== sessions
	) {
		branchesCache.current = {
			key: branchesKey,
			sessions,
			value: collectChangedFor(sessions.slice(-60), useChatStore.getState().messagesById),
		};
	}
	const branches = branchesCache.current.value;
	const commandsCount = useMemo(
		() => countCommands(activeId ? useChatStore.getState().messagesById[activeId] ?? [] : []),
		[activeId, activeKey],
	);
	// P2-⑧：改为「显式开才开」而非「未关过即默认开」，否则进入审查即全层展开。
	const isOpen = (id: string) => open[id] === true;

	return (
		<>
			{/* 工作区变更：跨 agent 共享 journal 流（多 Agent 可见性） */}
			<Row
				depth={1}
				open={journalOpen}
				chev
				role="treeitem"
				ariaLevel={1}
				ariaExpanded={journalOpen}
				onClick={() => setJournalOpen(v => !v)}
			>
				<FileText className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={1.8} />
				<span className="min-w-0 flex-1 truncate">工作区变更</span>
			</Row>
			{journalOpen ? (
				<TreeChildren open>
					<JournalTree />
				</TreeChildren>
			) : null}
			{branches.length === 0 ? (
				<li className="px-7 py-1 font-mono text-[11px] text-mute/70">暂无对话记录</li>
			) : (
				branches.map(b => {
					const convId = b.session.id;
					const convOpen = isOpen(convId);
					const diffOpen = isOpen(`${convId}:diff`);
					return (
						<div key={convId}>
							<Row
								depth={1}
								open={convOpen}
								chev
								role="treeitem"
								ariaLevel={1}
								ariaExpanded={convOpen}
								onClick={() => setOpen(o => ({...o, [convId]: !convOpen}))}
							>
								<History className="h-3.5 w-3.5 shrink-0 text-mute" strokeWidth={1.8} />
								<span className="min-w-0 flex-1 truncate">{b.session.title}</span>
							</Row>
							{convOpen ? (
								<TreeChildren open>
									<div>
										<Row
											depth={2}
											open={diffOpen}
											chev
											role="treeitem"
											ariaLevel={2}
											ariaExpanded={diffOpen}
											onClick={() => setOpen(o => ({...o, [`${convId}:diff`]: !diffOpen}))}
										>
											<Boxes className="h-3.5 w-3.5 shrink-0 text-mute" strokeWidth={1.8} />
											<span className="min-w-0 flex-1 truncate">历史diff</span>
										</Row>
										{diffOpen ? (
											<TreeChildren open>
												<PagedRows
													items={b.changed}
													empty={<li className="px-7 py-1 font-mono text-[11px] text-mute/70">无 diff</li>}
													renderItem={f => (
													<Row
														key={f.path}
														depth={3}
														active={selectedPath === f.path}
														role="treeitem"
														ariaLevel={3}
														onClick={() => void openReview({path: f.path, name: f.name, diff: f.diff ?? ''})}
														onContextMenu={event => {
															const root =
																useChatStore.getState().spaces.find(
																	sp =>
																		sp.id ===
																		useChatStore.getState().activeSpaceId,
																)?.rootPath ?? '';
															const absolutePath = joinWorkspacePath(
																root,
																f.path,
															);
															showContextMenu(
																event,
																filePathMenuItems({
																	entryPath: f.path,
																	entryName: f.name,
																	absolutePath,
																	kind: 'file',
																	onOpen: () =>
																		void useExplorerStore
																			.getState()
																			.openFile(f.path),
																	onOpenReview: () =>
																		void openReview({
																			path: f.path,
																			name: f.name,
																			diff: f.diff ?? '',
																		}),
																	includeSaveAs: false,
																}),
																`${f.name} 审查操作`,
															);
														}}
													>
															<FileText className="h-3.5 w-3.5 shrink-0 text-mute" strokeWidth={1.8} />
															<span className="min-w-0 flex-1 truncate">{f.name}</span>
															<span className="font-mono text-[10px]">
																{f.add > 0 ? <span className="text-ok">+{f.add}</span> : null}
																{f.del > 0 ? <span className="text-danger">-{f.del}</span> : null}
															</span>
														</Row>
													)}
												/>
											</TreeChildren>
										) : null}
									{/* 历史命令行：打开终端风格功能区界面（当前对话的所有命令行） */}
									<Row depth={2} role="treeitem" ariaLevel={2} onClick={() => setActiveTool('history')}>
											<TerminalSquare className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={1.8} />
											<span className="min-w-0 flex-1 truncate">历史命令行</span>
											{commandsCount > 0 ? (
												<span className="shrink-0 font-mono text-[10px] text-ok">+{commandsCount}</span>
											) : null}
										</Row>
									</div>
								</TreeChildren>
							) : null}
						</div>
					);
				})
			)}
		</>
	);
}

/* ==== git：分支 / 提交记录（接入后端 /v1/workspace/git/*）==== */
type GitTreeState = {
	loading: boolean;
	error: string | null;
	status: GitStatusResult | null;
	log: GitLogResult | null;
	branches: GitBranchesResult | null;
};

function GitTree() {
	const setActiveTool = useWorkspaceStore(s => s.setActiveTool);
	const [open, setOpen] = useState<Record<string, boolean>>({branches: true, commits: true});
	const [state, setState] = useState<GitTreeState>({loading: true, error: null, status: null, log: null, branches: null});
	const isOpen = (id: string) => open[id] !== false;

	// hydrate 完成或工作区切换后刷新（后端 cwd 或空间变化时 git 数据会变）。
	const hydrated = useChatStore(s => s.hydrated);
	const rootPath = useChatStore(s => {
		const space = s.spaces.find(sp => sp.id === s.activeSpaceId);
		return space?.rootPath ?? '';
	});

	useEffect(() => {
		let disposed = false;
		setState(prev => ({...prev, loading: prev.status ? prev.status.ok && prev.log != null : true}));
		void (async () => {
			try {
				const [status, log, branches] = await Promise.all([gitStatus(), gitLog(500), gitBranches()]);
				if (!disposed) {
					setState({loading: false, error: null, status, log, branches});
				}
			} catch (err) {
				if (!disposed) {
					setState({loading: false, error: err instanceof Error ? err.message : String(err), status: null, log: null, branches: null});
				}
			}
		})();
		return () => {
			disposed = true;
		};
	}, [hydrated, rootPath]);

	const noRepo = state.status ? !state.status.repo : false;

	return (
		<>
			<Row depth={1} open={isOpen('branches')} chev onClick={() => setOpen(o => ({...o, branches: !isOpen('branches')}))}>
				<GitBranch className="h-3.5 w-3.5 shrink-0 text-mute" strokeWidth={1.8} />
				<span className="min-w-0 flex-1 truncate">分支</span>
			</Row>
			{isOpen('branches') ? (
				<TreeChildren open>
					{state.loading ? (
						<li className="px-7 py-1 font-mono text-[11px] text-mute/70">加载中…</li>
					) : state.error || noRepo ? (
						<li className="px-7 py-1 font-mono text-[11px] text-mute/70">
							{state.error ? '加载失败' : '当前工作区不是 Git 仓库'}
						</li>
					) : (
						(state.branches?.branches ?? []).map(b => (
							<Row key={b} depth={2} onClick={() => setActiveTool('git')}>
								<GitBranch
									className={cn(
										'h-3.5 w-3.5 shrink-0',
										b === state.branches?.current ? 'text-accent' : 'text-mute',
									)}
									strokeWidth={1.8}
								/>
								<span className={cn('min-w-0 flex-1 truncate', b === state.branches?.current && 'text-accent')}>
									{b}
								</span>
								{b === state.branches?.current ? (
									<span className="rounded bg-accent/15 px-1 py-0.5 text-[10px] leading-none text-accent">当前</span>
								) : null}
							</Row>
						))
					)}
				</TreeChildren>
			) : null}
			{/* 提交记录：打开终端风格功能区界面（全部提交记录） */}
			<Row depth={1} onClick={() => setActiveTool('commits')}>
				<GitCommitHorizontal className="h-3.5 w-3.5 shrink-0 text-mute" strokeWidth={1.8} />
				<span className="min-w-0 flex-1 truncate">提交记录</span>
				{state.log && state.log.repo && state.log.commits.length > 0 ? (
					<span className="shrink-0 font-mono text-[10px] text-ok">+{state.log.commits.length}</span>
				) : null}
			</Row>
		</>
	);
}

/* ==== 右侧工作区侧栏（树状导航入口）==== */
export const WorkspacePanel = memo(function WorkspacePanel() {
	const open = useWorkspaceStore(s => s.open);
	const expanded = useWorkspaceStore(s => s.expanded);
	const active = useWorkspaceStore(s => s.active);
	const setActive = useWorkspaceStore(s => s.setActive);
	const toggleSection = useWorkspaceStore(s => s.toggleSection);
	const setActiveTool = useWorkspaceStore(s => s.setActiveTool);
	const navHidden = useWorkspaceStore(s => s.navHidden);
	const toggleNavHidden = useWorkspaceStore(s => s.toggleNavHidden);
	const collapseWorkspace = useWorkspaceStore(s => s.collapseWorkspace);
	const activeTool = useWorkspaceStore(s => s.activeTool);
	const selectedPath = useExplorerStore(s => s.selectedPath);
	const reviewDiff = useExplorerStore(s => s.reviewDiff);
	const loadingFile = useExplorerStore(s => s.loadingFile);
	const width = useSettingsStore(s => s.explorerWidth);
	// 窄窗口让位钳制：与侧栏协调收缩，保聊天列可读（paneViewportClamp.ts）。
	const {workspaceEff} = usePaneViewportClamp();
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const updateSettings = useSettingsStore(s => s.update);
	// T32：AgentMap 等「半成品」收进实验菜单默认隐藏；showExperimental=开启后出现在主界面 chrome。
	const showExperimental = useSettingsStore(s => s.showExperimental);
	const topEntries = showExperimental
		? TOP_ENTRIES
		: TOP_ENTRIES.filter(e => e.key !== 'map');
	const hover = useHoverScroll();
	const paneRef = useRef<HTMLElement | null>(null);
	const onWidth = (next: number) => updateSettings({explorerWidth: next});
	const {dragging, onResizeStart} = usePaneResize(width, onWidth, PANE_WIDTH_MIN, PANE_WIDTH_MAX, {invert: true, paneRef});
	const {mounted, shown} = usePresence(open, smoothness ? 200 : 0, 0);

	// 收起右边内容（navHidden）后若没有任何功能面板/预览打开，自动恢复，避免无从展开的死角；
	// 若仍开着内容则保留状态，工作区收起再展开时恢复上次打开的内容。
	const anyFunctionOpen = Boolean(activeTool || selectedPath || reviewDiff || loadingFile);
	useEffect(() => {
		if (navHidden && !anyFunctionOpen) {
			toggleNavHidden();
		}
	}, [navHidden, anyFunctionOpen, toggleNavHidden]);

	const isTreeOpen = (key: WorkspaceSection) => Boolean(expanded[key]);
	const isTreeActive = (key: WorkspaceSection) => active === key;

	// 右侧内容收起/展开：
	// - 只有树导航（没有功能面板/预览）时，点击直接收起整个工作区；
	// - 否则收起右边内容（树导航），把按钮交给功能区继续“展开右边内容”。
	const onToggleNavHidden = () => {
		if (!anyFunctionOpen) {
			collapseWorkspace();
			return;
		}
		toggleNavHidden();
	};

	const onTop = (entry: TopEntry) => {
		if (entry.kind === 'func') {
			setActiveTool(entry.func);
			return;
		}
		if (!isTreeOpen(entry.key) || !isTreeActive(entry.key)) setActive(entry.key);
		else toggleSection(entry.key);
	};

	const onToggleAll = () => {
		const treeKeys = topEntries.filter(e => e.kind === 'tree').map(e => e.key);
		const anyClosed = treeKeys.some(k => !expanded[k]);
		if (anyClosed) {
			// 全部展开
			for (const k of treeKeys) setActive(k);
		} else {
			// 全部收起
			for (const k of treeKeys) {
				if (expanded[k]) toggleSection(k);
			}
		}
	};

	if (!smoothness && !mounted) return null;

	// 只在工作区打开时「收起右边内容」才生效；关闭时等同于未收起，不残留任何按钮。
	const navEff = open && navHidden;

	return (
		<PaneSlot
			as="section"
			open={open}
			mounted={mounted}
			shown={shown}
			width={navEff ? 0 : workspaceEff}
			smoothness={smoothness}
			dragging={dragging}
			side="right"
			paneRef={paneRef}
			className={cn(
				'xy-workspace-chrome bg-transparent',
				!open && 'pointer-events-none',
			)}
			onMouseEnter={hover.onMouseEnter}
			onMouseLeave={hover.onMouseLeave}
		>
			{!navEff && (open || mounted) ? (
				<PaneResizeHandle edge="left" dragging={dragging} label="拖动调整工作区宽度" onMouseDown={onResizeStart} />
			) : null}

			{(open || mounted) && !navEff ? (
				/* 头部：展开时显示；收起（退出动画）期间保持挂载随面板滑出 */
				<div className="xy-soft-rule-b flex h-10 shrink-0 items-center justify-between gap-1 px-2">
					<span className="min-w-0 truncate px-1 text-[11px] font-medium tracking-wide text-mute">XEYO 工作区</span>
					<div className="flex items-center gap-0.5">
						<button
							type="button"
							className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
							aria-label="全部展开/收起"
							onClick={onToggleAll}
						>
							<ChevronsUpDown className="h-3.5 w-3.5" />
						</button>
						<button
							type="button"
							className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
							aria-label="收起/展开右边内容"
							title="收起/展开右边内容"
							onClick={onToggleNavHidden}
						>
							<PanelRight className="h-3.5 w-3.5" />
						</button>
					</div>
				</div>
			) : null}

			{(open || mounted) && !navEff ? (
				/* 树状入口：展开时显示；收起（退出动画）期间保持挂载随面板滑出 */
				<div ref={hover.scrollerRef} className="xy-hover-scroll min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
					<ul className="pb-1">
						{topEntries.map(entry => {
							const Icon = entry.Icon;
							const isTree = entry.kind === 'tree';
							const entryOpen = isTree ? isTreeOpen(entry.key) : false;
							const entryActive =
								entry.kind === 'tree'
									? entryOpen
									: activeTool === entry.func;
							return (
								<div key={entry.key}>
								<Row
									depth={0}
									open={entryOpen}
									active={entryActive}
									chev={isTree}
									onClick={() => onTop(entry)}
								>
									<Icon className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={1.9} />
									<span className="min-w-0 flex-1 truncate">{entry.label}</span>
								</Row>
								{isTree ? (
									/* 常挂载 + is-open/is-closed：展开/收起都有 grid-rows 平滑过渡；
									   首次挂载/卸载没有前值，动画不会触发。 */
									<TreeChildren open={entryOpen}>
										{entry.key === 'files' ? (
											<FilesTree />
										) : entry.key === 'history' ? (
											<ReviewTree />
										) : (
											<GitTree />
										)}
									</TreeChildren>
								) : null}
								</div>
							);
						})}
					</ul>
				</div>
			) : null}
		</PaneSlot>
	);
});
