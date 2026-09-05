import {
	Archive,
	ArrowLeft,
	ArrowRight,
	BarChart3,
	Blocks,
	ChevronRight,
	Clipboard,
	Folder,
	GitBranch,
	MoreHorizontal,
	PanelLeftClose,
	Pencil,
	Plus,
	RotateCcw,
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
import {SidebarPetDock} from '@/components/SidebarPetDock';
import {WorkspaceAddButton} from '@/components/WorkspaceAddMenu';
import {showContextMenu, type ContextMenuItem} from '@/components/ui/ContextMenu';

import {useHoverScroll} from '@/hooks/useHoverScroll';
import {usePaneResize} from '@/hooks/usePaneResize';
import {usePresence} from '@/hooks/usePresence';
import {useViewport} from '@/hooks/useViewport';
import {usePaneViewportClamp} from '@/hooks/paneViewportClamp';
import {fetchWorkspacePeers, type WorkspacePeerInfo} from '@/lib/api';
import {pickFolder} from '@/lib/openFolder';
import {formatRelativeShort} from '@/lib/time';
import type {ChatSession, ChatSpace} from '@/lib/types';
import {cn} from '@/lib/utils';
import {SIDE_SPACE_ID} from '@/lib/db';
import {selectRunningSessionIds, selectRunningSessionKey} from '@/lib/sessionStreams';
import {copyTextToClipboard} from '@/lib/workspaceOpen';
import {useChatStore} from '@/stores/chatStore';
import {useExplorerStore} from '@/stores/explorerStore';
import {useNavJournalStore} from '@/stores/navJournalStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {confirmDialog, promptDialog} from '@/lib/inlineDialog';
import {toast} from '@/lib/toast';
import {invokePet} from '@/pet/PetBridge';
import './ux-loaders.css';

/** 侧栏会话行：同工作区 peer 在场摘要（人类可见，不进 LLM）。 */
export type SessionPeerHint = {
	busy: boolean;
	/** 例如 `auth.ts` 或 `git pull` */
	label: string;
};

function peerHintFromInfo(peer: WorkspacePeerInfo): SessionPeerHint {
	const file = peer.owned_files[0]
		? peer.owned_files[0].replace(/\\/g, '/').split('/').pop() ||
			peer.owned_files[0]
		: '';
	let label = '';
	if (peer.git_op) {
		label = `git ${peer.git_op}`;
	} else if (file) {
		label = file;
	} else if (peer.todo_brief[0]) {
		label = peer.todo_brief[0].slice(0, 24);
	}
	// 忙碌已由会话行前的微光点（xy-run-dot）表达，不再重复渲染文字标签。
	return {busy: peer.busy, label};
}

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
	const hydrated = useChatStore(s => s.hydrated);
	const activeId = useChatStore(s => s.activeId);
	const collapsedSpaces = useChatStore(s => s.collapsedSpaces);
			const sidebarOpen = useChatStore(s => s.sidebarOpen);
			const [petDocked, setPetDocked] = useState(true);
			const petExtractionInFlight = useRef(false);

	const setSidebarOpen = useChatStore(s => s.setSidebarOpen);
	const createSession = useChatStore(s => s.createSession);
	const openFolder = useChatStore(s => s.openFolder);
	const enterSpace = useChatStore(s => s.enterSpace);
	const removeSpace = useChatStore(s => s.removeSpace);
	const toggleSpaceCollapsed = useChatStore(s => s.toggleSpaceCollapsed);
	const selectSession = useChatStore(s => s.selectSession);
	const removeSession = useChatStore(s => s.removeSession);
	// smoke-test #3：会话三点菜单（重命名 / 分叉 / 归档 / 恢复）。
	const renameSession = useChatStore(s => s.renameSession);
	const forkSession = useChatStore(s => s.forkSession);
	const archiveSession = useChatStore(s => s.archiveSession);
	const restoreSession = useChatStore(s => s.restoreSession);
	const sidebarWidth = useSettingsStore(s => s.sidebarWidth);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const updateSettings = useSettingsStore(s => s.update);
	const openUsage = useSettingsStore(s => s.openUsage);
	const closeUsage = useSettingsStore(s => s.closeUsage);
			const usageOpen = useSettingsStore(s => s.usagePanelOpen);
	// P3-⑪：插件 / MCP 面板（侧边栏「用量」下方入口）。
	const openPlugins = useSettingsStore(s => s.openPlugins);
	const closePlugins = useSettingsStore(s => s.closePlugins);
	const pluginsOpen = useSettingsStore(s => s.pluginsPanelOpen);
	// 侧聊会话并入 chatStore：虚拟 space（side-chat-space）标记，按需派生。
	const sideChatSessions = useMemo(
		() =>
			sessions
				.filter(s => s.spaceId === SIDE_SPACE_ID)
				.map(s => ({
					id: s.id,
					title: s.title,
					updatedAt: s.updatedAt,
					archived: s.archived === true,
				}))
				.sort((a, b) => b.updatedAt - a.updatedAt),
		[sessions],
	);
	const sideChatActiveId = activeId?.startsWith('side-') ? activeId : null;
	const sideChatCollapsed = collapsedSpaces[SIDE_SPACE_ID] === true;
	const setSideChatCollapsed = useCallback(
		(collapsed: boolean) => {
			if (collapsedSpaces[SIDE_SPACE_ID] !== collapsed) {
				toggleSpaceCollapsed(SIDE_SPACE_ID);
			}
		},
		[collapsedSpaces, toggleSpaceCollapsed],
	);
	// 正在运行：只订稳定 running key，避免整份 sessionStreams 每 token 重绘侧栏。
	const mainRunningKey = useChatStore(selectRunningSessionKey);
	const sideRunningKey = useChatStore(s =>
		selectRunningSessionIds(s)
			.filter(id => id.startsWith('side-'))
			.sort()
			.join('\0'),
	);
	const mainRunningIds = useMemo(
		() => new Set(mainRunningKey ? mainRunningKey.split('\0') : []),
		[mainRunningKey],
	);
	const sideRunningIds = useMemo(
		() => new Set(sideRunningKey ? sideRunningKey.split('\0') : []),
		[sideRunningKey],
	);

	// —— 完成未回看微光：任务在用户浏览别处时结束的会话，点亮静态绿色
	// 微光（不呼吸）作为"已完成待查看"提示；点击/切回该会话后熄灭。 ——
	// 注意：主 Chat 与侧栏 Chat 是两套独立 store（各自的 streaming 与
	// activeId），必须分开追踪、分别用自己仓库的 activeId 判定"是否在看"，
	// 否则侧栏会话会被误判为"不在看"而点亮，且因 activeId 不变化而无法熄灭。
	const [doneUnseenIds, setDoneUnseenIds] = useState<Set<string>>(() => new Set());
	const doneUnseenRef = useRef(doneUnseenIds);
	doneUnseenRef.current = doneUnseenIds;
	const prevMainRunningRef = useRef<Set<string>>(new Set());
	const prevSideRunningRef = useRef<Set<string>>(new Set());

	useEffect(() => {
		const prev = prevMainRunningRef.current;
		const next = new Set(mainRunningKey ? mainRunningKey.split('\0') : []);
		prevMainRunningRef.current = next;
		const active = useChatStore.getState().activeId;
		for (const id of prev) {
			if (!next.has(id) && active !== id) {
				setDoneUnseenIds(cur => new Set(cur).add(id));
			}
		}
	}, [mainRunningKey]);

	useEffect(() => {
		const prev = prevSideRunningRef.current;
		const next = new Set(sideRunningKey ? sideRunningKey.split('\0') : []);
		prevSideRunningRef.current = next;
		const activeNow = useChatStore.getState().activeId;
		const active = activeNow?.startsWith('side-') ? activeNow : null;
		for (const id of prev) {
			if (!next.has(id) && active !== id) {
				setDoneUnseenIds(cur => new Set(cur).add(id));
			}
		}
	}, [sideRunningKey]);

	// 兜底：程序化切到某会话（路由/selectSession 任意路径）也熄灭对应灯。
	useEffect(() => {
		for (const viewed of [activeId, sideChatActiveId]) {
			if (!viewed || !doneUnseenRef.current.has(viewed)) {
				continue;
			}
			setDoneUnseenIds(cur => {
				if (!cur.has(viewed)) {
					return cur;
				}
				const next = new Set(cur);
				next.delete(viewed);
				return next;
			});
		}
	}, [activeId, sideChatActiveId]);

	// 点击即熄灭：不依赖 effect 的依赖变化（点击当前已是 active 的行时
	// selectSession 可能早退、路由不变，兜底 effect 不会触发）。
	const clearDoneGlow = useCallback((id?: string | null) => {
		if (!id) {
			return;
		}
		setDoneUnseenIds(cur => {
			if (!cur.has(id)) {
				return cur;
			}
			const next = new Set(cur);
			next.delete(id);
			return next;
		});
	}, []);

	// 同工作区多会话在场：轮询 /v1/workspace/peers，侧栏行显示「也在改 xxx」。
	const [peerHintsById, setPeerHintsById] = useState<
		Record<string, SessionPeerHint>
	>({});
	const workspaceRootsKey = useMemo(() => {
		const roots = spaces
			.map(s => (s.rootPath || '').trim())
			.filter(Boolean)
			.sort();
		return roots.join('\0');
	}, [spaces]);

	useEffect(() => {
		if (!sidebarOpen || !workspaceRootsKey) {
			setPeerHintsById({});
			return;
		}
		let cancelled = false;
		const roots = workspaceRootsKey.split('\0').filter(Boolean);

		const refresh = async () => {
			const next: Record<string, SessionPeerHint> = {};
			await Promise.all(
				roots.map(async root => {
					try {
						const res = await fetchWorkspacePeers(root);
						for (const peer of res.peers) {
							const hint = peerHintFromInfo(peer);
							if (hint.label) {
								next[peer.session_id] = hint;
							}
						}
					} catch {
						/* 后端未就绪时静默 */
					}
				}),
			);
			if (!cancelled) {
				setPeerHintsById(next);
			}
		};

		void refresh();
		const timer = window.setInterval(() => {
			void refresh();
		}, 5000);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
		};
	}, [sidebarOpen, workspaceRootsKey, mainRunningKey]);

	// 全局导航历史（整个 GUI 的 上一个/下一个界面；右上角常驻，浏览器式）。
	const canNavBack = useNavJournalStore(s => s.index > 0);
	const canNavForward = useNavJournalStore(
		s => s.index >= 0 && s.index < s.entries.length - 1,
	);
	const goToNavEntry = useCallback(
		(target: {path: string; usageOpen: boolean} | null) => {
			if (!target) {
				return;
			}
			if (useSettingsStore.getState().usagePanelOpen !== target.usageOpen) {
				useSettingsStore.getState().setUsagePanel(target.usageOpen);
			}
			navigate(target.path);
		},
		[navigate],
	);

	// 多 Agent 子视图上下文：‹ 箭头优先驱动 agentViewStack 全局栈回退，
	// 仅主会话路由生效；不在子视图时保持原有的界面历史回退。
	const agentViewActive = useChatStore(
		s => Boolean(s.activeId) && s.agentViewIndex > 0,
	);
	const handleBack = useCallback(() => {
		if (!isSideChat) {
			const st = useChatStore.getState();
			if (st.activeId && st.agentViewStack[st.agentViewIndex] !== 'main') {
				st.backAgentView();
				return;
			}
		}
		goToNavEntry(useNavJournalStore.getState().peekBack());
	}, [goToNavEntry, isSideChat]);

	const hover = useHoverScroll();
	const paneRef = useRef<HTMLElement | null>(null);

			const [opening, setOpening] = useState(false);
		const [workspaceExpanded, setWorkspaceExpanded] = useState(false);

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
			useEffect(() => {
			void invokePet('character_drop_on_island');
		}, []);

			const extractPet = useCallback(async () => {
				if (petExtractionInFlight.current) return;
				petExtractionInFlight.current = true;
				try {
					const lift = invokePet('character_lift', {x: 220, y: 200});
					// Remove the dock as soon as the lift command is dispatched. This
					// avoids waiting on a newly-created WebviewWindow to settle.
					setPetDocked(false);
					await lift;
				} catch (error) {
					setPetDocked(true);
					console.error('[XeyoPet] failed to lift pet from sidebar', error);
					// Restore the dock if the native window cannot be lifted.
				} finally {
					petExtractionInFlight.current = false;
				}
			}, []);

		const onResizeStart = useCallback(
		(e: React.MouseEvent) => {
			startPaneResize(e);
		},
		[startPaneResize],
	);

	// 主侧栏只分组主工作区会话；侧聊会话由 SideChatSection 单独渲染。
	const filteredSessions = useMemo(
		() => sessions.filter(s => s.spaceId !== SIDE_SPACE_ID),
		[sessions],
	);

	const sessionsBySpace = useMemo(() => {
		const map = new Map<string, ChatSession[]>();
		for (const s of filteredSessions) {
			const list = map.get(s.spaceId) ?? [];
			list.push(s);
			map.set(s.spaceId, list);
		}
		for (const list of map.values()) {
			list.sort((a, b) => b.updatedAt - a.updatedAt);
		}
		return map;
	}, [filteredSessions]);

	const visibleSpaces = useMemo(() => {
		return [...spaces].sort((a, b) => b.updatedAt - a.updatedAt);
	}, [spaces]);

	const orderedSpaces = visibleSpaces;
	const recentWorkspaces = useMemo(
		() =>
			orderedSpaces
				.filter(s => Boolean(s.rootPath?.trim()))
				.map(s => ({path: s.rootPath, name: s.name})),
		[orderedSpaces],
	);

	const {compact} = useViewport();
	// 窄窗口让位钳制：与工作区协调收缩，保聊天列可读（paneViewportClamp.ts）。
	const {sidebarEff} = usePaneViewportClamp();
	const width = compact
		? Math.min(sidebarEff, 280)
		: sidebarEff;
	const {mounted, shown} = usePresence(
		sidebarOpen,
		smoothness ? 200 : 0,
		0,
	);

	const goSession = useCallback(
		async (id: string) => {
			clearDoneGlow(id);
			closeUsage?.();
			await selectSession(id);
			navigate(`/c/${id}`);
		},
		[clearDoneGlow, closeUsage, navigate, selectSession],
	);

	const onNewInSpace = useCallback(
		async (spaceId: string) => {
			closeUsage?.();
			const id = await createSession(spaceId);
			navigate(`/c/${id}`);
		},
		[closeUsage, createSession, navigate],
	);

	const onNew = useCallback(async () => {
		closeUsage?.();
		const id = await createSession();
		navigate(`/c/${id}`);
	}, [closeUsage, createSession, navigate]);

	const onOpenFolder = useCallback(async (path?: string) => {
		if (opening) {
			return;
		}
		setOpening(true);
		try {
			const selected = path ?? (await pickFolder());
			if (!selected) {
				return;
			}
			const spaceId = await openFolder(selected);
			const id = await enterSpace(spaceId);
			setWorkspaceExpanded(true);
			useWorkspaceStore.getState().setOpen(true);
			useWorkspaceStore.getState().setActive('files');
			void useExplorerStore.getState().ensureRoot();
			closeUsage?.();
			navigate(`/c/${id}`);
		} catch (err) {
			toast.error(
				err instanceof Error ? err.message : `打开文件夹失败：${String(err)}`,
			);
		} finally {
			setOpening(false);
		}
	}, [closeUsage, enterSpace, navigate, openFolder, opening]);

	// smoke-test #3：会话三点菜单命令 → store action + 路由（归档/恢复在 SpaceFolder 内渲染）。
	const handleRenameSession = useCallback(
		async (id: string, title: string) => {
			try {
				await renameSession(id, title);
			} catch (err) {
				toast.error(
					err instanceof Error ? err.message : '重命名失败',
				);
			}
		},
		[renameSession],
	);

	const handleForkSession = useCallback(
		async (id: string) => {
			closeUsage?.();
			try {
				const newId = await forkSession(id);
				clearDoneGlow(id);
				navigate(`/c/${newId}`);
			} catch (err) {
				toast.error(
					err instanceof Error ? err.message : '分叉失败',
				);
			}
		},
		[closeUsage, clearDoneGlow, forkSession, navigate],
	);

	const handleArchiveSession = useCallback(
		async (id: string) => {
			const wasActive = useChatStore.getState().activeId === id;
			try {
				await archiveSession(id);
			} catch (err) {
				toast.error(
					err instanceof Error ? err.message : '归档失败',
				);
				return;
			}
			if (wasActive) {
				// 归档了当前正打开的会话：切到同空间最近的非归档会话。
				const st = useChatStore.getState();
				const spaceId = st.sessions.find(x => x.id === id)?.spaceId;
				const next =
					st.sessions.find(
						x =>
							x.spaceId === spaceId &&
							x.id !== id &&
							!x.archived,
					) ??
					st.sessions.find(
						x =>
							x.spaceId !== SIDE_SPACE_ID &&
							x.id !== id &&
							!x.archived,
					);
				navigate(next ? `/c/${next.id}` : '/');
			}
		},
		[archiveSession, navigate],
	);

	const handleRestoreSession = useCallback(
		async (id: string) => {
			try {
				await restoreSession(id);
			} catch (err) {
				toast.error(
					err instanceof Error ? err.message : '恢复失败',
				);
			}
		},
		[restoreSession],
	);

	const createSideChat = useChatStore(s => s.createSideSession);

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
					<div className="ml-auto flex items-center gap-0.5">
						<button
							type="button"
							aria-label="上一个界面"
							title="上一个界面"
							disabled={!canNavBack && !agentViewActive}
							onClick={handleBack}
							className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:pointer-events-none disabled:opacity-30"
						>
							<ArrowLeft className="h-3.5 w-3.5" />
						</button>
						<button
							type="button"
							aria-label="下一个界面"
							title="下一个界面"
							disabled={!canNavForward}
							onClick={() =>
								goToNavEntry(useNavJournalStore.getState().peekForward())
							}
							className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:pointer-events-none disabled:opacity-30"
						>
							<ArrowRight className="h-3.5 w-3.5" />
						</button>
					</div>
				</div>

				<div className="flex flex-col px-1.5 pb-1">
					<button
						type="button"
						onClick={() => void onNew()}
						className="xy-pressable flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-ink-soft hover:bg-glass-hover hover:text-ink"
					>
						<Plus className="h-3.5 w-3.5 shrink-0" />
						<span className="min-w-0 flex-1 truncate text-[13px]">
							New Chat
						</span>
						<span className="shrink-0 font-mono text-[10px] text-mute/70">
							Ctrl+N
						</span>
					</button>

					<button
						type="button"
						onClick={() => useChatStore.getState().requestSearchFocus()}
						className="xy-pressable flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-ink-soft hover:bg-glass-hover hover:text-ink"
					>
						<Search className="h-3.5 w-3.5 shrink-0" />
						<span className="min-w-0 flex-1 truncate text-[13px]">
							Search
						</span>
						<span className="shrink-0 font-mono text-[10px] text-mute/70">
							Ctrl+K
						</span>
					</button>

					<button
						type="button"
						onClick={() => {
							if (usageOpen) {
								closeUsage?.();
							} else {
								openUsage?.();
							}
						}}
						className={cn(
							'xy-pressable flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left',
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

					{/* P3-⑪：插件 / MCP 管理面板（侧边栏「用量」下方入口）。 */}
					<button
						type="button"
						onClick={() => {
							if (pluginsOpen) {
								closePlugins?.();
							} else {
								openPlugins?.();
							}
						}}
						className={cn(
							'xy-pressable flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left',
							pluginsOpen
								? 'bg-glass-hover text-ink'
								: 'text-ink-soft hover:bg-glass-hover hover:text-ink',
						)}
					>
						<Blocks className="h-3.5 w-3.5 shrink-0" />
						<span className="min-w-0 flex-1 truncate text-[13px]">
							插件 / MCP
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
										<span className="min-w-0 truncate pl-0.125">工作区</span>
										<ChevronRight
											className={cn(
												'h-3.5 w-3.5 shrink-0 opacity-0 transition-[transform,opacity] duration-150 group-hover/section:opacity-100',
												workspaceExpanded && 'rotate-90',
											)}
										/>
								</button>
							<WorkspaceAddButton
								recents={recentWorkspaces}
								busy={opening}
								onOpenPath={path => onOpenFolder(path)}
							/>
				</div>

					{!hydrated ? (
						<ul className="mt-1 pb-1" aria-hidden="true">
							{Array.from({length: 6}, (_, i) => (
								<li
									key={i}
									className="xy-skeleton-row flex w-full items-center gap-2 rounded-md py-1 pr-2 pl-7"
								>
									<span className="xy-skeleton-bar" />
								</li>
							))}
						</ul>
					) : workspaceExpanded ? (
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
								runningIds={mainRunningIds}
								doneUnseen={doneUnseenIds}
								peerHints={peerHintsById}
								collapsed={Boolean(collapsedSpaces[space.id])}
									activeId={isSideChat ? null : activeId}
								forceOpen={false}
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
								onRenameSession={handleRenameSession}
								onForkSession={handleForkSession}
								onArchiveSession={handleArchiveSession}
								onRestoreSession={handleRestoreSession}
								onRemoveSpace={
									() => {
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
									runningIds={sideRunningIds}
									doneUnseen={doneUnseenIds}
									activeId={isSideChat ? sideChatActiveId : null}
									expanded={!sideChatCollapsed}
									onToggle={() => setSideChatCollapsed(!sideChatCollapsed)}

								onAdd={() => {
									closeUsage();
									void createSideChat().then(id => {
										navigate(`/side/${id}`);
									});
								}}
								onSelect={(id) => {
									clearDoneGlow(id);
									closeUsage();
									void selectSession(id);
									navigate(`/side/${id}`);
								}}
								onRemoveSession={async id => {
									const wasActive = sideChatActiveId === id;
									await removeSession(id);
									if (wasActive) {
										const next = useChatStore
											.getState()
											.sessions.find(s => s.id.startsWith('side-'));
										navigate(next ? `/side/${next.id}` : '/');
									}
								}}
								onArchiveSession={handleArchiveSession}
								onRestoreSession={handleRestoreSession}
							/>
						</div>
						{petDocked ? <SidebarPetDock onExtract={extractPet} /> : null}

				</div>
				</div>
			);

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
				'xy-sidebar-chrome bg-transparent',
				!sidebarOpen && 'pointer-events-none',
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
	runningIds,
	doneUnseen,
	peerHints,
	onToggle,
	onAdd,
	onSelect,
	onRemoveSession,
	onRenameSession,
	onForkSession,
	onArchiveSession,
	onRestoreSession,
	onRemoveSpace,
}: {
	space: ChatSpace;
	sessions: ChatSession[];
	collapsed: boolean;
	activeId: string | null;
	forceOpen: boolean;
	runningIds: ReadonlySet<string>;
	/** 任务完成且未回看的会话 id 集合 → 静态绿色微光。 */
	doneUnseen?: Set<string>;
	/** 同工作区 peer 在场：会话 id → 短标签。 */
	peerHints?: Record<string, SessionPeerHint>;
	onToggle: () => void;
	onAdd: () => void;
	onSelect: (id: string) => void;
	onRemoveSession: (id: string) => void;
	/** smoke-test #3：三点菜单命令（重命名 / 分叉 / 归档 / 恢复）。 */
	onRenameSession: (id: string, title: string) => void;
	onForkSession: (id: string) => void;
	onArchiveSession: (id: string) => void;
	onRestoreSession: (id: string) => void;
	onRemoveSpace?: () => void;
}) {
	const open = forceOpen || !collapsed;
	const hasRoot = Boolean(space.rootPath);
	const activeSessions = sessions.filter(x => !x.archived);
	const archivedSessions = sessions.filter(x => x.archived);

	// smoke-test #3 + 归档门槛（2026-09-05）：常态菜单 = 重命名/分叉/归档，
	// **不提供删除**；已归档菜单 = 恢复/删除（删除前危险确认）。
	// 「归档了才能删除」——删除是不可逆操作，归档作为缓冲层。
	const openItemMenu = useCallback(
		(e: React.MouseEvent, item: ChatSession) => {
			e.preventDefault();
			e.stopPropagation();
			const items: ContextMenuItem[] = [];
			if (item.archived) {
				items.push({
					kind: 'action',
					id: 'restore',
					label: '恢复会话',
					icon: <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => onRestoreSession(item.id),
				});
				items.push({kind: 'sep'});
				items.push({
					kind: 'action',
					id: 'delete',
					label: '删除会话',
					danger: true,
					icon: <Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => {
						void (async () => {
							const ok = await confirmDialog({
								title: '删除已归档会话？',
								body: `「${item.title}」将连同全部聊天记录永久删除，不可恢复。`,
								confirmText: '删除',
								danger: true,
							});
							if (ok) {
								onRemoveSession(item.id);
							}
						})();
					},
				});
			} else {
				items.push({
					kind: 'action',
					id: 'rename',
					label: '重命名',
					icon: <Pencil className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => {
						void (async () => {
							const next = await promptDialog({
								title: '重命名对话',
								initial: item.title,
								confirmText: '保存',
							});
							if (next != null) {
								onRenameSession(item.id, next);
							}
						})();
					},
				});
				items.push({
					kind: 'action',
					id: 'fork',
					label: '分叉会话',
					icon: <GitBranch className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => onForkSession(item.id),
				});
				items.push({
					kind: 'action',
					id: 'archive',
					label: '归档会话',
					icon: <Archive className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => onArchiveSession(item.id),
				});
			}
			showContextMenu(e, items, item.title || '会话操作');
		},
		[
			onRenameSession,
			onForkSession,
			onArchiveSession,
			onRestoreSession,
			onRemoveSession,
		],
	);

	const renderSessionRow = (item: ChatSession) => {
		const active = item.id === activeId;
		const running = runningIds.has(item.id);
		const peer = peerHints?.[item.id];
		const peerLabel = peer?.label?.trim() || '';
		return (
			<li
				key={item.id}
				className="group/item relative"
				style={{
					contentVisibility: 'auto',
					containIntrinsicSize: 'auto 32px',
				}}
			>
				<button
					type="button"
					onClick={() => onSelect(item.id)}
					title={peerLabel ? `也在改 ${peerLabel}` : undefined}
					className={cn(
						'xy-pressable flex w-full items-center gap-2 rounded-md py-1 pr-2 pl-4 text-left text-[13px]',
						active
							? 'bg-glass-strong font-medium text-accent'
							: item.archived
								? 'text-ink-soft/80 hover:bg-glass-hover'
								: 'text-ink-soft hover:bg-glass-hover',
					)}
				>
					<span
						className={cn(
							'xy-run-dot',
							running
								? 'is-running'
								: doneUnseen?.has(item.id) && 'is-done-unseen',
						)}
						aria-hidden="true"
					/>
					<span
						className={cn(
							'min-w-0 flex-1 truncate',
							item.archived && 'text-mute',
						)}
					>
						{item.title}
					</span>
					{peerLabel && !item.archived ? (
						<span className="max-w-[5.5rem] shrink-0 truncate font-mono text-[10px] text-warn/90 group-hover/item:opacity-0">
							{peerLabel}
						</span>
					) : (
						<span className="xy-session-meta shrink-0 font-mono text-[10px] text-mute/70 group-hover/item:opacity-0">
							{formatRelativeShort(item.updatedAt)}
						</span>
					)}
				</button>
				<button
					type="button"
					aria-label={item.archived ? '已归档会话操作' : '会话操作'}
					title={
						item.archived
							? '恢复 / 删除'
							: '重命名 / 分叉 / 归档'
					}
					onClick={e => openItemMenu(e, item)}
					className="xy-icon-btn xy-sidebar-affordance absolute top-1/2 right-1 -translate-y-1/2 translate-x-1 rounded p-1 text-mute opacity-0 invisible pointer-events-none hover:bg-glass-hover hover:text-ink group-hover/item:visible group-hover/item:pointer-events-auto group-hover/item:opacity-100 group-hover/item:translate-x-0 group-focus-within/item:visible group-focus-within/item:pointer-events-auto group-focus-within/item:opacity-100 group-focus-within/item:translate-x-0"
				>
					<MoreHorizontal className="h-3.5 w-3.5" />
				</button>
			</li>
		);
	};

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
							void (async () => {
								const ok = await confirmDialog({
									title: '关闭工作区？',
									body: `关闭工作区「${space.name}」并删除其全部对话？`,
									confirmText: '关闭',
									danger: true,
								});
								if (ok) {
									onRemoveSpace();
								}
							})();
						}}
						className="xy-icon-btn xy-sidebar-affordance mr-0.5 rounded p-1 text-mute opacity-0 translate-x-1 invisible pointer-events-none hover:bg-danger/10 hover:text-danger group-hover:visible group-hover:pointer-events-auto group-hover:opacity-100 group-hover:translate-x-0"
						
					>
						<Trash2 className="h-3 w-3" />
					</button>
				) : null}
			</div>

			<div className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')} aria-hidden={!open}>
				<ul className="min-h-0 overflow-hidden pb-1">
					{activeSessions.length === 0 && archivedSessions.length === 0 ? (
						<li className="px-7 py-1 font-mono text-[11px] text-mute/70">
							{hasRoot ? '暂无对话' : '打开文件夹后开始'}
						</li>
					) : (
						activeSessions.map(item => renderSessionRow(item))
					)}
				</ul>
				{archivedSessions.length > 0 ? (
					<ul className="min-h-0 overflow-hidden pb-1">
						<li className="flex items-center gap-1 px-7 py-0.5 font-mono text-[10px] tracking-wider text-mute/70">
							<Archive className="h-3 w-3 shrink-0" aria-hidden />
							<span>已归档 {archivedSessions.length}</span>
						</li>
						{archivedSessions.map(item => renderSessionRow(item))}
					</ul>
				) : null}
			</div>
		</div>
		);
	});


const SideChatSection = memo(function SideChatSection({
	sessions,
			activeId,
			runningIds,
		doneUnseen,
		expanded,
		onToggle,
		onAdd,
		onSelect,
		onRemoveSession,
		onArchiveSession,
		onRestoreSession,
	}: {
		sessions: Array<{
			id: string;
			title: string;
			updatedAt: number;
			archived: boolean;
		}>;
		activeId: string | null;
		runningIds: ReadonlySet<string>;
		doneUnseen?: Set<string>;
		expanded: boolean;
		onToggle: () => void;
		onAdd: () => void;

	onSelect: (id: string) => void;
	onRemoveSession: (id: string) => void;
	/** 归档门槛（2026-09-05）：与主会话同规则——常态不提供删除。 */
	onArchiveSession: (id: string) => void;
	onRestoreSession: (id: string) => void;
}) {
	// 归档门槛：常态列表只显示未归档；已归档分组渲染，仅提供恢复/删除。
	const activeSessions = sessions.filter(s => !s.archived);
	const archivedSessions = sessions.filter(s => s.archived);

	const openSideMenu = useCallback(
		(e: React.MouseEvent, session: {id: string; title: string; archived: boolean}) => {
			e.preventDefault();
			e.stopPropagation();
			const items: ContextMenuItem[] = [
				{
					kind: 'action',
					id: 'copy-id',
					label: '复制会话 ID',
					icon: <Clipboard className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () =>
						void copyTextToClipboard(session.id, '已复制会话 ID'),
				},
			];
			if (session.archived) {
				items.push({
					kind: 'action',
					id: 'restore',
					label: '恢复对话',
					icon: <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => onRestoreSession(session.id),
				});
				items.push({kind: 'sep'});
				items.push({
					kind: 'action',
					id: 'delete',
					label: '删除对话',
					danger: true,
					icon: <Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => {
						void (async () => {
							const ok = await confirmDialog({
								title: '删除已归档对话？',
								body: `「${session.title}」将连同全部聊天记录永久删除，不可恢复。`,
								confirmText: '删除',
								danger: true,
							});
							if (ok) {
								onRemoveSession(session.id);
							}
						})();
					},
				});
			} else {
				items.push({
					kind: 'action',
					id: 'archive',
					label: '归档对话',
					icon: <Archive className="h-3.5 w-3.5" strokeWidth={1.9} />,
					onSelect: () => onArchiveSession(session.id),
				});
			}
			showContextMenu(e, items, session.title || '会话操作');
		},
		[onArchiveSession, onRemoveSession, onRestoreSession],
	);

	const renderSideRow = (
		session: {id: string; title: string; updatedAt: number; archived: boolean},
	) => {
		const active = session.id === activeId;
		const running = runningIds.has(session.id);
		return (
			<li
				key={session.id}
				className="group/item relative"
				style={{
					contentVisibility: 'auto',
					containIntrinsicSize: 'auto 32px',
				}}
			>
				<button
					type="button"
					onClick={() => onSelect(session.id)}
					onContextMenu={event => openSideMenu(event, session)}
					className={cn(
						'xy-pressable flex w-full items-center gap-2 rounded-md py-1 pr-2 pl-4 text-left text-[13px]',
						active
							? 'bg-glass-strong font-medium text-accent'
							: session.archived
								? 'text-ink-soft/80 hover:bg-glass-hover'
								: 'text-ink-soft hover:bg-glass-hover',
					)}
				>
					<span
						className={cn(
							'xy-run-dot',
							running
								? 'is-running'
								: doneUnseen?.has(session.id) && 'is-done-unseen',
						)}
						aria-hidden="true"
					/>
					<span
						className={cn(
							'min-w-0 flex-1 truncate',
							session.archived && 'text-mute',
						)}
					>
						{session.title}
					</span>
					<span className="xy-session-meta shrink-0 font-mono text-[10px] text-mute/70 group-hover/item:opacity-0">
						{formatRelativeShort(session.updatedAt)}
					</span>
				</button>
				<button
					type="button"
					aria-label={session.archived ? '已归档对话操作' : '对话操作'}
					title={session.archived ? '恢复 / 删除' : '归档'}
					onClick={event => openSideMenu(event, session)}
					className="xy-icon-btn xy-sidebar-affordance absolute top-1/2 right-1 -translate-y-1/2 translate-x-1 rounded p-1 text-mute opacity-0 invisible pointer-events-none hover:bg-glass-hover hover:text-ink group-hover/item:visible group-hover/item:pointer-events-auto group-hover/item:opacity-100 group-hover/item:translate-x-0 group-focus-within/item:visible group-focus-within/item:pointer-events-auto group-focus-within/item:opacity-100 group-focus-within/item:translate-x-0"
				>
					<MoreHorizontal className="h-3.5 w-3.5" />
				</button>
			</li>
		);
	};

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
				{activeSessions.length === 0 && archivedSessions.length === 0 ? (
					<li className="px-7 py-1 font-mono text-[11px] text-mute/70">暂无 Chat 对话</li>
				) : (
					activeSessions.map(session => renderSideRow(session))
				)}
				{archivedSessions.length > 0 ? (
					<>
						<li className="flex items-center gap-1 px-7 py-0.5 font-mono text-[10px] tracking-wider text-mute/70">
							<Archive className="h-3 w-3 shrink-0" aria-hidden />
							<span>已归档 {archivedSessions.length}</span>
						</li>
						{archivedSessions.map(session => renderSideRow(session))}
					</>
				) : null}
			</ul>
		</div>
	</div>
	);
});

