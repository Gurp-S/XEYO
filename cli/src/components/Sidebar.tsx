import {
		BarChart3,

	ChevronRight,
	Folder,
	FolderPlus,
	PanelLeftClose,
	Plus,
	Search,
	Trash2,
} from 'lucide-react';
import {
	memo,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
} from 'react';
import {useLocation, useNavigate} from 'react-router-dom';
import {PaneResizeHandle} from '@/components/PaneResizeHandle';
import {PaneSlot} from '@/components/PaneSlot';
import {useHoverScroll} from '@/hooks/useHoverScroll';
import {usePaneResize} from '@/hooks/usePaneResize';
import {usePresence} from '@/hooks/usePresence';
import {useViewport} from '@/hooks/useViewport';
import {DEFAULT_SPACE_ID} from '@/lib/db';
import {pickFolder} from '@/lib/openFolder';
import {formatRelativeShort} from '@/lib/time';
import type {ChatSession, ChatSpace} from '@/lib/types';
import {cn} from '@/lib/utils';
import {useChatStore} from '@/stores/chatStore';
import {useSideChatStore} from '@/stores/sideChatStore';

import {
	SIDEBAR_WIDTH_MAX,
	SIDEBAR_WIDTH_MIN,
	isSmoothnessOn,
	useSettingsStore,
} from '@/stores/settingsStore';

export const Sidebar = memo(function Sidebar() {
	const navigate = useNavigate();
	const location = useLocation();
	const isSideChat = location.pathname.startsWith('/side/');
	const spaces = useChatStore(s => s.spaces);
	const sessions = useChatStore(s => s.sessions);
	const activeId = useChatStore(s => s.activeId);
	const collapsedSpaces = useChatStore(s => s.collapsedSpaces);
	const sidebarOpen = useChatStore(s => s.sidebarOpen);
	const setSidebarOpen = useChatStore(s => s.setSidebarOpen);
	const createSession = useChatStore(s => s.createSession);
	const openFolder = useChatStore(s => s.openFolder);
	const enterSpace = useChatStore(s => s.enterSpace);
	const removeSpace = useChatStore(s => s.removeSpace);
	const toggleSpaceCollapsed = useChatStore(s => s.toggleSpaceCollapsed);
	const selectSession = useChatStore(s => s.selectSession);
	const removeSession = useChatStore(s => s.removeSession);
	const sidebarWidth = useSettingsStore(s => s.sidebarWidth);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const updateSettings = useSettingsStore(s => s.update);
	const openUsage = useSettingsStore(s => s.openUsage);
	const closeUsage = useSettingsStore(s => s.closeUsage);
			const usageOpen = useSettingsStore(s => s.usagePanelOpen);
			const sideChatSessions = useSideChatStore(s => s.sessions);
			const sideChatActiveId = useSideChatStore(s => s.activeId);
			const sideChatCollapsed = useSideChatStore(s => s.collapsed);
			const setSideChatCollapsed = useSideChatStore(s => s.setCollapsed);

		const initSideChat = useSideChatStore(s => s.init);
		
		const createSideChat = useSideChatStore(s => s.createSession);
		const selectSideChat = useSideChatStore(s => s.selectSession);
		const removeSideChat = useSideChatStore(s => s.removeSession);
		const {compact} = useViewport();

	const hover = useHoverScroll();
	const paneRef = useRef<HTMLElement | null>(null);

	const searchFocusSeq = useChatStore(s => s.searchFocusSeq);
	const [query, setQuery] = useState('');
	const [searchFocused, setSearchFocused] = useState(false);
			const [opening, setOpening] = useState(false);
		const [workspaceExpanded, setWorkspaceExpanded] = useState(true);

	const searchRef = useRef<HTMLInputElement>(null);
	const onSidebarWidth = useCallback(
		(next: number) => updateSettings({sidebarWidth: next}),
		[updateSettings],
	);
	const {dragging, onResizeStart: startPaneResize} = usePaneResize(
		sidebarWidth,
		onSidebarWidth,
		SIDEBAR_WIDTH_MIN,
		SIDEBAR_WIDTH_MAX,
		{paneRef},
	);
	const onResizeStart = useCallback(
		(e: React.MouseEvent) => {
			if (compact) {
				return;
			}
			startPaneResize(e);
		},
		[compact, startPaneResize],
	);

	const filteredSessions = useMemo(() => {
		const q = query.trim().toLowerCase();
		if (!q) {
			return sessions;
		}
		return sessions.filter(
			s =>
				s.title.toLowerCase().includes(q) ||
				spaces
					.find(sp => sp.id === s.spaceId)
					?.name.toLowerCase()
					.includes(q) ||
				spaces
					.find(sp => sp.id === s.spaceId)
					?.rootPath.toLowerCase()
					.includes(q),
		);
	}, [sessions, spaces, query]);

	const sessionsBySpace = useMemo(() => {
		const map = new Map<string, ChatSession[]>();
		for (const s of filteredSessions) {
			const list = map.get(s.spaceId) ?? [];
			list.push(s);
			map.set(s.spaceId, list);
		}
		for (const [, list] of map) {
			list.sort((a, b) => b.updatedAt - a.updatedAt);
		}
		return map;
	}, [filteredSessions]);

	const orderedSpaces = useMemo(() => {
		const q = query.trim().toLowerCase();
		return spaces.filter(sp => {
			if (!q) {
				return true;
			}
			if (sp.name.toLowerCase().includes(q)) {
				return true;
			}
			if (sp.rootPath.toLowerCase().includes(q)) {
				return true;
			}
			return (sessionsBySpace.get(sp.id) ?? []).length > 0;
		});
	}, [spaces, query, sessionsBySpace]);

	const width = compact ? Math.min(sidebarWidth, 280) : sidebarWidth;
	const {mounted, shown} = usePresence(
		sidebarOpen,
		smoothness && !compact ? 200 : 0,
		0,
	);

	const goSession = useCallback(
		async (id: string) => {
			closeUsage?.();
			await selectSession(id);
			navigate(`/c/${id}`);
			if (compact) {
				setSidebarOpen(false);
			}
		},
		[closeUsage, compact, navigate, selectSession, setSidebarOpen],
	);

	const onNewInSpace = useCallback(
		async (spaceId: string) => {
			closeUsage?.();
			const id = await createSession(spaceId);
			navigate(`/c/${id}`);
			if (compact) {
				setSidebarOpen(false);
			}
		},
		[closeUsage, compact, createSession, navigate, setSidebarOpen],
	);

	const onNew = useCallback(async () => {
		closeUsage?.();
		const id = await createSession();
		navigate(`/c/${id}`);
		if (compact) {
			setSidebarOpen(false);
		}
	}, [closeUsage, compact, createSession, navigate, setSidebarOpen]);

	const onOpenFolder = useCallback(async () => {
		if (opening) {
			return;
		}
		setOpening(true);
		try {
			const path = await pickFolder();
			if (!path) {
				return;
			}
			const spaceId = await openFolder(path);
			const id = await enterSpace(spaceId);
			closeUsage?.();
			navigate(`/c/${id}`);
			if (compact) {
				setSidebarOpen(false);
			}
		} catch (err) {
			window.alert(
				err instanceof Error ? err.message : `打开文件夹失败：${String(err)}`,
			);
		} finally {
			setOpening(false);
		}
	}, [closeUsage, compact, enterSpace, navigate, openFolder, opening, setSidebarOpen]);

			useEffect(() => {
			void initSideChat();
		}, [initSideChat]);

		useEffect(() => {
			if (searchFocusSeq === 0) {

			return;
		}
		const t = window.setTimeout(() => searchRef.current?.focus(), 40);
		return () => window.clearTimeout(t);
	}, [searchFocusSeq]);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const mod = e.ctrlKey || e.metaKey;
			if (!mod || e.shiftKey) {
				return;
			}
			if (e.key.toLowerCase() === 'k') {
				e.preventDefault();
				useChatStore.getState().requestSearchFocus();
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, []);

	const panelInner = (
			<div className="flex h-full min-w-0 w-full flex-col">
				<div className="flex items-center px-2 pt-2.5 pb-1">
					<button
						type="button"
						aria-label="折叠侧栏"
						onClick={() => setSidebarOpen(false)}
className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
							
					>
						<PanelLeftClose className="h-3.5 w-3.5" />
					</button>
				</div>

				<div className="flex flex-col px-1.5 pb-1">
					<button
						type="button"
						onClick={() => void onNew()}
						className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-ink-soft hover:bg-glass-hover hover:text-ink"
					>
						<Plus className="h-3.5 w-3.5 shrink-0" />
						<span className="min-w-0 flex-1 truncate text-[13px]">
							New Chat
						</span>
						<span className="shrink-0 font-mono text-[10px] text-mute/70">
							Ctrl+N
						</span>
					</button>

					<label
						className={cn(
							'flex w-full cursor-text items-center gap-2 rounded-md px-2 py-1.5',
							searchFocused || query
								? 'bg-glass-hover text-ink'
								: 'text-ink-soft hover:bg-glass-hover hover:text-ink',
						)}
					>
						<Search className="h-3.5 w-3.5 shrink-0" />
						<input
							ref={searchRef}
							value={query}
							onChange={e => setQuery(e.target.value)}
							onFocus={() => setSearchFocused(true)}
							onBlur={() => setSearchFocused(false)}
							onKeyDown={e => {
								if (e.key === 'Escape') {
									e.preventDefault();
									setQuery('');
									searchRef.current?.blur();
								}
							}}
							placeholder="Search"
							className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-mute"
							aria-label="搜索会话"
						/>
						{!query ? (
							<span className="shrink-0 font-mono text-[10px] text-mute/70">
								Ctrl+K
							</span>
						) : null}
					</label>

					<button
						type="button"
						onClick={() => {
							if (usageOpen) {
								closeUsage?.();
							} else {
								openUsage?.();
							}
							if (compact) {
								setSidebarOpen(false);
							}
						}}
						className={cn(
							'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left',
							usageOpen
								? 'bg-glass-hover text-ink'
								: 'text-ink-soft hover:bg-glass-hover hover:text-ink',
						)}
					>
						<BarChart3 className="h-3.5 w-3.5 shrink-0" />
						<span className="min-w-0 flex-1 truncate text-[13px]">
							用量
						</span>
					</button>
				</div>

				

<div
								ref={hover.scrollerRef}
								className="xy-hover-scroll min-h-0 flex-1 overflow-y-auto"
							>
								<div className="px-1.5 pb-2">
													<div className="group/section mt-1 flex items-center justify-between gap-3 rounded-md px-1 pb-1 text-mute transition-colors hover:bg-glass-hover hover:text-accent focus-within:text-accent">
								<button
									type="button"
									onClick={() => setWorkspaceExpanded(value => !value)}
									aria-expanded={workspaceExpanded}
									className="flex min-w-0 flex-1 items-center gap-1 rounded-md px-1.5 py-1 text-left text-[11px] font-medium tracking-wide text-current focus:outline-none focus-visible:outline-none"
								>
										<span className="min-w-0 truncate">工作区</span>
										<ChevronRight
											className={cn(
												'h-3.5 w-3.5 shrink-0 opacity-0 transition-[transform,opacity] duration-150 group-hover/section:opacity-100',
												workspaceExpanded && 'rotate-90',
											)}
										/>
								</button>
							<button

						type="button"
						onClick={() => void onOpenFolder()}
						disabled={opening}
className="xy-icon-btn rounded-md p-1 text-current hover:bg-glass-hover hover:text-current disabled:opacity-60"
							
						aria-label="打开文件夹"
					>
						<FolderPlus className="h-3.5 w-3.5" />
					</button>
				</div>

						{workspaceExpanded ? (
							orderedSpaces.length === 0 ? (
						<p className="px-2 py-6 text-center font-mono text-xs text-mute">
							无匹配结果
						</p>
					) : (
						orderedSpaces.map(space => (
							<SpaceFolder
								key={space.id}
								space={space}
								sessions={sessionsBySpace.get(space.id) ?? []}
								collapsed={Boolean(collapsedSpaces[space.id])}
									activeId={isSideChat ? null : activeId}
								forceOpen={Boolean(query.trim())}
								onToggle={() => toggleSpaceCollapsed(space.id)}
								onAdd={() => void onNewInSpace(space.id)}
								onSelect={id => void goSession(id)}
								onRemoveSession={id => {
									void (async () => {
										const wasActive =
											useChatStore.getState().activeId === id;
										await removeSession(id);
										if (wasActive) {
											const next =
												useChatStore.getState().activeId;
											navigate(next ? `/c/${next}` : '/');
										}
									})();
								}}
								onRemoveSpace={
									space.id === DEFAULT_SPACE_ID
										? undefined
										: () => {
												void (async () => {
													await removeSpace(space.id);
													const next =
														useChatStore.getState()
															.activeId;
													navigate(
														next ? `/c/${next}` : '/',
													);
												})();
											}
								}
								/>
							))
							)
							) : null}


									</div>
<div className="shrink-0 px-1.5 pb-3">
								<SideChatSection
									sessions={sideChatSessions}
									activeId={isSideChat ? sideChatActiveId : null}
									expanded={!sideChatCollapsed}
									onToggle={() => setSideChatCollapsed(!sideChatCollapsed)}

								onAdd={() => {
									const id = createSideChat();
									navigate(`/side/${id}`);
									if (compact) setSidebarOpen(false);
								}}
								onSelect={(id) => {
									selectSideChat(id);
									navigate(`/side/${id}`);
									if (compact) setSidebarOpen(false);
								}}
								onRemoveSession={(id) => {
									const wasActive = sideChatActiveId === id;
									removeSideChat(id);
									if (wasActive) {
										const next = useSideChatStore.getState().activeId;
										navigate(next ? `/side/${next}` : '/');
									}
								}}
							/>
						</div>
		
				</div>
				</div>
			);

	if (compact) {
		return (
			<>
				{sidebarOpen ? (
					<button
						type="button"
						aria-label="关闭侧栏"
						className="anim-fade absolute inset-0 z-30 bg-ink/20"
						onClick={() => setSidebarOpen(false)}
					/>
				) : null}
				<aside
					ref={paneRef}
					aria-hidden={!sidebarOpen}
					className={cn(
						'xy-sidebar xy-sidebar-drawer xy-pane-slide absolute inset-y-0 left-0 z-40 flex h-full shrink-0 flex-col border-r border-line/70 bg-transparent',
						dragging && 'xy-sidebar-dragging xy-pane-dragging',
						!sidebarOpen && 'pointer-events-none',
					)}
					style={{
						width,
						transform: sidebarOpen
							? 'translateX(0)'
							: 'translateX(-100%)',
					}}
					onMouseEnter={hover.onMouseEnter}
					onMouseLeave={hover.onMouseLeave}
				>
					{panelInner}
				</aside>
			</>
		);
	}

	return (
		<PaneSlot
			open={sidebarOpen}
			mounted={mounted}
				shown={shown}
				keepAlive={smoothness}
			width={width}
			smoothness={smoothness}
			dragging={dragging}
			side="left"
			paneRef={paneRef}
			className={cn(
				'bg-transparent',
				sidebarOpen
					? 'border-r border-line/70'
					: 'pointer-events-none border-r border-transparent',
			)}
			onMouseEnter={hover.onMouseEnter}
			onMouseLeave={hover.onMouseLeave}
		>
			{panelInner}
			{sidebarOpen || (smoothness && mounted) ? (
				<PaneResizeHandle
					edge="right"
					dragging={dragging}
					label="拖动调整侧栏宽度"
					onMouseDown={onResizeStart}
				/>
			) : null}
		</PaneSlot>
	);
});

const SpaceFolder = memo(function SpaceFolder({
	space,
	sessions,
	collapsed,
	activeId,
	forceOpen,
	onToggle,
	onAdd,
	onSelect,
	onRemoveSession,
	onRemoveSpace,
}: {
	space: ChatSpace;
	sessions: ChatSession[];
	collapsed: boolean;
	activeId: string | null;
	forceOpen: boolean;
	onToggle: () => void;
	onAdd: () => void;
	onSelect: (id: string) => void;
	onRemoveSession: (id: string) => void;
	onRemoveSpace?: () => void;
}) {
	const open = forceOpen || !collapsed;
	const hasRoot = Boolean(space.rootPath);

	return (
		<div className="mb-0.5">
			<div className="group flex items-center gap-0.5 rounded-md hover:bg-glass-hover">
				<button
					type="button"
					onClick={onToggle}
className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-ink-soft focus:outline-none focus-visible:outline-none"
 
				>
					
					<Folder className="h-3.5 w-3.5 shrink-0 text-mute" />
					<span className="min-w-0 flex-1 truncate text-[13px] text-ink">
						{space.name}
					</span>
				</button>
				<button
					type="button"
					aria-label={`在 ${space.name} 中新建对话`}
					onClick={e => {
						e.stopPropagation();
						onAdd();
					}}
className="xy-icon-btn xy-sidebar-affordance mr-0.5 rounded p-1 text-mute opacity-0 translate-x-1 invisible pointer-events-none hover:bg-glass-strong hover:text-ink group-hover:visible group-hover:pointer-events-auto group-hover:opacity-100 group-hover:translate-x-0"
						
				>
					<Plus className="h-3.5 w-3.5" />
				</button>
				{onRemoveSpace ? (
					<button
						type="button"
						aria-label={`关闭工作区 ${space.name}`}
						onClick={e => {
							e.stopPropagation();
							if (
								window.confirm(
									`关闭工作区「${space.name}」并删除其全部对话？`,
								)
							) {
								onRemoveSpace();
							}
						}}
						className="xy-icon-btn xy-sidebar-affordance mr-0.5 rounded p-1 text-mute opacity-0 translate-x-1 invisible pointer-events-none hover:bg-danger/10 hover:text-danger group-hover:visible group-hover:pointer-events-auto group-hover:opacity-100 group-hover:translate-x-0"
						
					>
						<Trash2 className="h-3 w-3" />
					</button>
				) : null}
			</div>

			<div className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')} aria-hidden={!open}>
				<ul className="min-h-0 overflow-hidden pb-1">
					{sessions.length === 0 ? (
						<li className="px-7 py-1 font-mono text-[11px] text-mute/70">
							{hasRoot ? '暂无对话' : '打开文件夹后开始'}
						</li>
					) : (
						sessions.map(item => {
						const active = item.id === activeId;
						return (
							<li key={item.id} className="group/item relative">
								<button
									type="button"
									onClick={() => onSelect(item.id)}
									className={cn(
										'flex w-full items-center gap-2 rounded-md py-1 pr-2 pl-7 text-left text-[13px]',
										active
											? 'bg-glass-strong font-medium text-accent'
											: 'text-ink-soft hover:bg-glass-hover',
									)}
								>
									<span className="min-w-0 flex-1 truncate">
										{item.title}
									</span>
									<span className="xy-session-meta shrink-0 font-mono text-[10px] text-mute/70 group-hover/item:opacity-0">
										{formatRelativeShort(item.updatedAt)}
									</span>
								</button>
								<button
									type="button"
									aria-label="删除会话"
									onClick={e => {
										e.stopPropagation();
										onRemoveSession(item.id);
									}}
									className="xy-icon-btn xy-sidebar-affordance absolute top-1/2 right-1 -translate-y-1/2 translate-x-1 rounded p-1 text-mute opacity-0 invisible pointer-events-none hover:text-danger group-hover/item:visible group-hover/item:pointer-events-auto group-hover/item:opacity-100 group-hover/item:translate-x-0"
								>
									<Trash2 className="h-3 w-3" />
								</button>
							</li>
						);
					})
				)}
				</ul>
			</div>
		</div>
		);
	});


const SideChatSection = memo(function SideChatSection({
	sessions,
			activeId,
		expanded,
		onToggle,
		onAdd,
		onSelect,
		onRemoveSession,
	}: {
		sessions: Array<{id: string; title: string; updatedAt: number}>;
		activeId: string | null;
		expanded: boolean;
		onToggle: () => void;
		onAdd: () => void;

	onSelect: (id: string) => void;
	onRemoveSession: (id: string) => void;
}) {
	return (
		<div className="mb-0.5">
							<div className="group/section mt-1 flex items-center justify-between gap-3 rounded-md px-1 pb-1 text-mute transition-colors hover:bg-glass-hover hover:text-accent focus-within:text-accent">
					<button
						type="button"
						onClick={onToggle}
						aria-expanded={expanded}
						className="flex min-w-0 flex-1 items-center gap-1 rounded-md px-1.5 py-1 text-left text-[11px] font-medium tracking-wide text-current focus:outline-none focus-visible:outline-none"
					>
								<span className="min-w-0 truncate">Chat</span>
								<ChevronRight
									className={cn(
										'h-3.5 w-3.5 shrink-0 opacity-0 transition-[transform,opacity] duration-150 group-hover/section:opacity-100',
										expanded && 'rotate-90',
									)}
								/>
					</button>
					<button

					type="button"
					aria-label="新建 Chat 对话"
					onClick={event => {
						event.stopPropagation();
						onAdd();
					}}
					className="xy-icon-btn rounded-md p-1 text-current hover:bg-glass-hover hover:text-current"
				>
					<Plus className="h-3.5 w-3.5" />
				</button>
			</div>
				<div
					className={cn('xy-sidebar-tree grid', expanded ? 'is-open' : 'is-closed')}
					aria-hidden={!expanded}
				>
				<ul className="min-h-0 overflow-hidden pb-1">
					{sessions.length === 0 ? (
						<li className="px-7 py-1 font-mono text-[11px] text-mute/70">暂无 Chat 对话</li>
					) : (
						sessions.map(session => {
							const active = session.id === activeId;
							return (
								<li key={session.id} className="group/item relative">
									<button
										type="button"
										onClick={() => onSelect(session.id)}
										className={cn(
											'flex w-full items-center gap-2 rounded-md py-1 pr-2 pl-7 text-left text-[13px]',
											active
												? 'bg-glass-strong font-medium text-accent'
												: 'text-ink-soft hover:bg-glass-hover',
										)}
									>
										<span className="min-w-0 flex-1 truncate">{session.title}</span>
										<span className="xy-session-meta shrink-0 font-mono text-[10px] text-mute/70 group-hover/item:opacity-0">
											{formatRelativeShort(session.updatedAt)}
										</span>
									</button>
									<button
										type="button"
										aria-label="删除 Chat 对话"
										onClick={event => {
											event.stopPropagation();
											onRemoveSession(session.id);
										}}
										className="xy-icon-btn xy-sidebar-affordance absolute top-1/2 right-1 -translate-y-1/2 translate-x-1 rounded p-1 text-mute opacity-0 invisible pointer-events-none hover:text-danger group-hover/item:visible group-hover/item:pointer-events-auto group-hover/item:opacity-100 group-hover/item:translate-x-0"
									>
										<Trash2 className="h-3 w-3" />
									</button>
								</li>
							);
						})
					)}
				</ul>
			</div>
		</div>
	);
});

