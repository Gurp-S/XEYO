import {
	Bot,
	ChartNoAxesColumn,
	FileCode2,
	FolderOpen,
	Globe,
	Map,
	MessageSquarePlus,
	QrCode,
	Search,
	Settings,
	Terminal,
} from 'lucide-react';
import {
	useCallback,
	useEffect,
	useId,
	useMemo,
	useRef,
	useState,
	type KeyboardEvent as ReactKeyboardEvent,
	type ReactNode,
} from 'react';
import {createPortal} from 'react-dom';
import {searchWorkspace, setWorkspace, type WorkspaceEntry} from '@/lib/api';
import {newSession, openPageView, openSession} from '@/lib/appNav';
import {handleComposerSlash, lastUserText} from '@/lib/slashCommands';
import {pushEscLayer, popEscLayer} from '@/lib/escStack';
import {useIconTheme} from '@/lib/iconThemeLoader';
import {pickFolder} from '@/lib/openFolder';
import {formatRelativeShort} from '@/lib/time';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';
import {useModalA11y} from '@/hooks/useModalA11y';
import {usePresence} from '@/hooks/usePresence';
import {slashCommands, type SlashCommand} from '@/generated/slashManifest';
import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';
import {useCommandPaletteStore} from '@/stores/commandPaletteStore';
import {useRemoteStore} from '@/stores/remoteStore';
import {
	useSettingsStore,
	type SettingsTab,
} from '@/stores/settingsStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';

type FilterId = 'all' | 'agents' | 'files' | 'actions' | 'commands' | 'settings';

const FILTERS: {id: FilterId; label: string}[] = [
	{id: 'all', label: 'All'},
	{id: 'agents', label: 'Agents'},
	{id: 'files', label: 'Files'},
	{id: 'actions', label: 'Actions'},
	{id: 'commands', label: 'Commands'},
	{id: 'settings', label: 'Settings'},
];

type PaletteItem = {
	id: string;
	filter: Exclude<FilterId, 'all'>;
	section: string;
	label: string;
	detail?: string;
	meta?: string;
	icon?: ReactNode;
	run: () => void | Promise<void>;
};

const SETTINGS_ITEMS: {tab: SettingsTab; label: string; detail: string}[] = [
	{tab: 'appearance', label: '外观', detail: '主题、强调色、壁纸'},
	{tab: 'accounts', label: '模型与账号', detail: 'API Key、模型配置'},
	{tab: 'rewind', label: '回溯', detail: '工作区还原选项'},
	{tab: 'pet', label: '桌宠', detail: 'XEYO Pet 设置'},
	{tab: 'remote', label: '远程 · 微信', detail: '远程通道与扫码'},
];

function matchesQuery(haystack: string, query: string): boolean {
	const q = query.trim().toLowerCase();
	if (!q) {
		return true;
	}
	return haystack.toLowerCase().includes(q);
}

function fileDirLabel(path: string): string {
	const parts = path.replace(/\\/g, '/').split('/');
	if (parts.length <= 1) {
		return '';
	}
	return parts.slice(0, -1).join('\\');
}

function FileRowIcon({name, kind}: {name: string; kind?: 'file' | 'dir'}) {
	const mod = useIconTheme();
	if (!mod) {
		return <FileCode2 className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />;
	}
	const ext = name.includes('.') ? (name.split('.').pop()?.toLowerCase() ?? '') : '';
	const icon = mod.getFileIcon({
		fileExtension: ext || undefined,
		fileName: name,
		fallback: kind === 'dir' ? 'folder' : 'file',
	});
	return <mod.MaterialIcon name={icon} size={16} />;
}

function KbdHint({children}: {children: ReactNode}) {
	return (
		<span className="inline-flex items-center gap-1.5 text-[11px] text-mute">
			{children}
		</span>
	);
}

function Kbd({label}: {label: string}) {
	return (
		<kbd className="rounded border border-line/70 bg-glass-strong px-1 py-0.5 font-mono text-[10px] text-ink-soft">
			{label}
		</kbd>
	);
}

export function CommandPalette() {
	const open = useCommandPaletteStore(s => s.open);
	const closePalette = useCommandPaletteStore(s => s.closePalette);
	const recentAgents = useCommandPaletteStore(s => s.recentAgents);
	const recentFiles = useCommandPaletteStore(s => s.recentFiles);
	const touchAgent = useCommandPaletteStore(s => s.touchAgent);
	const touchFile = useCommandPaletteStore(s => s.touchFile);

	const sessions = useChatStore(s => s.sessions);
	const spaces = useChatStore(s => s.spaces);
	const openFolder = useChatStore(s => s.openFolder);
	const enterSpace = useChatStore(s => s.enterSpace);
	const setAgentMode = useChatStore(s => s.setAgentMode);

	const openSettings = useSettingsStore(s => s.openSettings);
	// T32：AgentMap 等半成品收进实验菜单——默认不在命令面板列出「打开地图」。
	const showExperimental = useSettingsStore(s => s.showExperimental);
	const toggleRemote = useRemoteStore(s => s.toggleRemote);
	const remoteLoggedIn = useRemoteStore(s => s.loggedIn);

	// enterRafs=0：打开时立刻 visible，避免 StrictMode 取消 rAF 导致一直透明
	const {mounted, shown} = usePresence(open, 160, 0);
	const visible = open || shown;
	const inputRef = useRef<HTMLInputElement>(null);
	const listRef = useRef<HTMLDivElement>(null);
	const titleId = useId();

	const [query, setQuery] = useState('');
	const [filter, setFilter] = useState<FilterId>('all');
	const [activeIndex, setActiveIndex] = useState(0);
	const [fileHits, setFileHits] = useState<WorkspaceEntry[]>([]);
	const [filesLoading, setFilesLoading] = useState(false);

	const spaceName = useCallback(
		(spaceId: string) => spaces.find(s => s.id === spaceId)?.name || 'XEYO',
		[spaces],
	);

	const close = useCallback(() => {
		closePalette();
	}, [closePalette]);

	// 可达性基座：焦点陷阱 + 关闭后焦点归还 + 背景 inert。
	// Esc 不在此接管——本组件已有 pushEscLayer('command-palette') 一处，
	// 再传 escId 会推入同 id 的第二层（pushEscLayer 按 id 去重，净效果是
	// 卸载顺序变成两个 cleanup 相互抵消，属于自找的时序风险）。
	// 陷阱与既有 Tab 语义兼容：面板把 Tab 用于切换过滤器，而陷阱仅在焦点
	// 位于首/末元素时回卷（回卷目标恰是输入框），中部按键一律放行。
	const a11yRootRef = useRef<HTMLDivElement>(null);
	useModalA11y({
		open: open && mounted,
		rootRef: a11yRootRef,
	});

	const runAndClose = useCallback(
		async (fn: () => void | Promise<void>) => {
			close();
			try {
				await fn();
			} catch (err) {
				toast.error(err instanceof Error ? err.message : String(err));
			}
		},
		[close],
	);

	const openAgent = useCallback(
		(sessionId: string, title: string, sid: string) => {
			void runAndClose(async () => {
				touchAgent({id: sessionId, title, spaceName: spaceName(sid)});
				// 统一入口（lib/appNav）：页面视图随路由自动退出。
				await openSession(sessionId);
			});
		},
		[runAndClose, spaceName, touchAgent],
	);

	const openFilePath = useCallback(
		(path: string, name: string) => {
			void runAndClose(async () => {
				touchFile({path, name});
				const {openWorkspacePreview} = await import(
					'@/lib/openWorkspacePreview'
				);
				await openWorkspacePreview(path);
			});
		},
		[runAndClose, touchFile],
	);

	// Slash 命令：跟随 Composer 的 handleComposerSlash 路径执行（本地或 POST /v1/slash）。
	const runSlash = useCallback(
		(cmd: SlashCommand) => {
			void runAndClose(async () => {
				const st = useChatStore.getState();
				const sid0 = st.activeId;
				if (!sid0) {
					toast.info('请先进入一个对话');
					return;
				}
				const sess0 = st.sessions.find(s => s.id === sid0);
				const ws0 =
					st.spaces.find(s => s.id === sess0?.spaceId)?.rootPath?.trim() || '';
				await handleComposerSlash(`/${cmd.name}`, {
					sessionId: sid0,
					backendSessionId:
						activeBackendSessionId(st.historyById, sid0) || undefined,
					workspace: ws0,
					onNewSession: () => {
						void st.createSession();
					},
					onRetryLast: () => {
						const last = lastUserText(sid0);
						if (last) {
							void st.sendMessage(last);
						} else {
							toast.info('还没有可重试的消息');
						}
					},
				});
			});
		},
		[runAndClose],
	);

	// 打开时重置 UI
	useEffect(() => {
		if (!open) {
			return;
		}
		setQuery('');
		setFilter('all');
		setActiveIndex(0);
		setFileHits([]);
		const t = window.setTimeout(() => inputRef.current?.focus(), 30);
		return () => window.clearTimeout(t);
	}, [open]);

	useEffect(() => {
		if (!open) {
			return;
		}
		pushEscLayer('command-palette', close);
		return () => popEscLayer('command-palette');
	}, [open, close]);

	// 防抖的工作区文件搜索
	useEffect(() => {
		if (!open) {
			return;
		}
		const q = query.trim();
		const wantsFiles = filter === 'all' || filter === 'files';
		const isSlashQuery = q.startsWith('/');
		if (isSlashQuery || !wantsFiles || !q) {
			setFileHits([]);
			setFilesLoading(false);
			return;
		}
		let cancelled = false;
		setFilesLoading(true);
		const timer = window.setTimeout(() => {
			void (async () => {
				try {
					const st = useChatStore.getState();
					const root =
						st.spaces.find(s => s.id === st.activeSpaceId)?.rootPath?.trim() ||
						'';
					if (root) {
						await setWorkspace(root);
					}
					const res = await searchWorkspace(q);
					if (!cancelled) {
						setFileHits(res.hits.filter(h => h.kind === 'file').slice(0, 24));
					}
				} catch {
					if (!cancelled) {
						setFileHits([]);
					}
				} finally {
					if (!cancelled) {
						setFilesLoading(false);
					}
				}
			})();
		}, 180);
		return () => {
			cancelled = true;
			window.clearTimeout(timer);
		};
	}, [open, query, filter]);

	const items = useMemo(() => {
		const q = query.trim();
		const isSlashQuery = q.startsWith('/');
		const out: PaletteItem[] = [];
		const now = Date.now();

		const pushAgents = (section: string, list: typeof sessions, limit?: number) => {
			const rows = list
				.filter(
					s =>
						matchesQuery(s.title, q) ||
						matchesQuery(spaceName(s.spaceId), q) ||
						matchesQuery(s.id, q),
				)
				.slice(0, limit ?? 40);
			for (const s of rows) {
				out.push({
					id: `agent:${s.id}`,
					filter: 'agents',
					section,
					label: s.title || '新对话',
					detail: spaceName(s.spaceId),
					meta: formatRelativeShort(s.updatedAt, now),
					icon: <Bot className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />,
					run: () => openAgent(s.id, s.title, s.spaceId),
				});
			}
		};

		if (filter === 'all' || filter === 'agents') {
			if (!q) {
				const recentIds = new Set(recentAgents.map(a => a.id));
				const fromRecent = recentAgents
					.map(r => sessions.find(s => s.id === r.id))
					.filter((s): s is NonNullable<typeof s> => Boolean(s));
				const fallback = [...sessions]
					.sort((a, b) => b.updatedAt - a.updatedAt)
					.filter(s => !recentIds.has(s.id))
					.slice(0, 8);
				const merged = [...fromRecent, ...fallback].slice(0, 8);
				pushAgents('Recent Agents', merged);
			} else {
				pushAgents(
					'Agents',
					[...sessions].sort((a, b) => b.updatedAt - a.updatedAt),
					20,
				);
			}
		}

		if (filter === 'all' || filter === 'files') {
			if (!q) {
				for (const f of recentFiles.slice(0, 8)) {
					out.push({
						id: `file:${f.path}`,
						filter: 'files',
						section: 'Recent Files',
						label: f.name,
						detail: fileDirLabel(f.path),
						meta: formatRelativeShort(f.touchedAt, now),
						icon: <FileRowIcon name={f.name} kind="file" />,
						run: () => openFilePath(f.path, f.name),
					});
				}
			} else {
				for (const hit of fileHits) {
					out.push({
						id: `file:${hit.path}`,
						filter: 'files',
						section: filesLoading ? 'Files…' : 'Files',
						label: hit.name,
						detail: fileDirLabel(hit.path),
						icon: <FileRowIcon name={hit.name} kind={hit.kind} />,
						run: () => openFilePath(hit.path, hit.name),
					});
				}
			}
		}

		if (filter === 'all' || filter === 'actions') {
			const actions: Omit<PaletteItem, 'filter' | 'section'>[] = [
				{
					id: 'action:new-agent',
					label: '新建对话',
					detail: '创建新对话',
					meta: 'Ctrl+N',
					icon: (
						<MessageSquarePlus
							className="h-4 w-4 shrink-0 text-mute"
							strokeWidth={1.75}
						/>
					),
				run: () =>
					void runAndClose(async () => {
						// 统一入口：新建会话 + 路由。
						await newSession();
					}),
			},
			{
				id: 'action:open-folder',
				label: 'Open Folder',
				detail: '打开工作区文件夹',
				meta: 'Ctrl+O',
				icon: (
					<FolderOpen className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
				),
				run: () =>
					void runAndClose(async () => {
						const path = await pickFolder();
						if (!path) {
							return;
						}
						const spaceId = await openFolder(path);
						const id = await enterSpace(spaceId);
						await openSession(id);
					}),
			},
				{
					id: 'action:terminal',
					label: 'Open Terminal',
					detail: '右侧工作区终端',
					icon: (
						<Terminal className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
					),
					run: () =>
						void runAndClose(() => {
							useWorkspaceStore.getState().setOpen(true);
							useWorkspaceStore.getState().setActiveTool('terminal');
						}),
				},
				{
					id: 'action:browser',
					label: '打开浏览器预览',
					detail: '右侧工作区嵌入式预览',
					icon: (
						<Globe className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
					),
					run: () =>
						void runAndClose(() => {
							useWorkspaceStore.getState().setOpen(true);
							useWorkspaceStore.getState().setActiveTool('browser');
						}),
				},
				...(showExperimental
					? [
							{
								id: 'action:map',
								label: '打开地图',
								detail: '架构 / 代码 / 本轮落点（实验功能）',
								icon: (
									<Map
										className="h-4 w-4 shrink-0 text-mute"
										strokeWidth={1.75}
									/>
								),
								run: () =>
									void runAndClose(() => {
										useWorkspaceStore.getState().setOpen(true);
										useWorkspaceStore.getState().setActiveTool('map');
									}),
							},
						]
					: []),
				{
					id: 'action:usage',
					label: '用量',
					detail: '查看 Token 与费用',
					icon: (
						<ChartNoAxesColumn
							className="h-4 w-4 shrink-0 text-mute"
							strokeWidth={1.75}
						/>
					),
				run: () =>
					void runAndClose(() => {
						openPageView('usage');
					}),
			},
			{
				id: 'action:remote',
					label: remoteLoggedIn ? '断开远程' : '远程连接',
					detail: '微信远程通道',
					icon: (
						<QrCode className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
					),
					run: () =>
						void runAndClose(() => {
							void toggleRemote();
						}),
				},
				{
					id: 'action:mode-agent',
					label: '模式：Agent',
					detail: '切换到 Agent 模式',
					run: () =>
						void runAndClose(() => {
							setAgentMode('agent');
						}),
				},
				{
					id: 'action:mode-ask',
					label: '模式：Ask',
					detail: '切换到 Ask 模式',
					run: () =>
						void runAndClose(() => {
							setAgentMode('ask');
						}),
				},
				{
					id: 'action:mode-plan',
					label: '模式：Plan',
					detail: '切换到 Plan 模式',
					run: () =>
						void runAndClose(() => {
							setAgentMode('plan');
						}),
				},
				{
					id: 'action:settings',
					label: '设置',
					detail: '打开设置',
					icon: (
						<Settings className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
					),
					run: () =>
						void runAndClose(() => {
							openSettings();
						}),
				},
			];
			for (const a of actions) {
				if (!matchesQuery(`${a.label} ${a.detail ?? ''} ${a.meta ?? ''}`, q)) {
					continue;
				}
				const coreIdle =
					a.id === 'action:new-agent' ||
					a.id === 'action:open-folder' ||
					a.id === 'action:settings';
				if (filter === 'all' && !q && !coreIdle) {
					continue;
				}
				out.push({
					...a,
					filter: 'actions',
					section: 'Actions',
				});
			}
		}

		if (filter === 'all' || filter === 'settings') {
			for (const s of SETTINGS_ITEMS) {
				if (!matchesQuery(`${s.label} ${s.detail}`, q)) {
					continue;
				}
				if (filter === 'all' && !q) {
					continue;
				}
				out.push({
					id: `settings:${s.tab}`,
					filter: 'settings',
					section: 'Settings',
					label: s.label,
					detail: s.detail,
					icon: (
						<Settings className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
					),
					run: () =>
						void runAndClose(() => {
							openSettings(s.tab);
						}),
				});
			}
		}

		// Slash 命令：/ 前缀开启命令搜索；Composer 自动补全同款（usage + summary）。
		if (filter === 'all' || filter === 'commands') {
			if (filter === 'commands' || isSlashQuery) {
				// 同时按带 / 的 usage 与去掉 / 的 name/summary/别名匹配。
				const qStripped = isSlashQuery ? q.slice(1) : q;
				for (const c of slashCommands) {
					if (!c.surfaces.some(s => s === 'gui')) {
						continue;
					}
					const haystack = `${c.usage} ${c.name} ${c.summary} ${c.aliases.join(' ')}`;
					if (
						!matchesQuery(haystack, q) &&
						!matchesQuery(haystack, qStripped)
					) {
						continue;
					}
					out.push({
						id: `slash:${c.name}`,
						filter: 'commands',
						section: 'Commands',
						label: c.usage,
						detail: c.summary,
						icon: (
							<Terminal
								className="h-4 w-4 shrink-0 text-mute"
								strokeWidth={1.75}
							/>
						),
						run: () => runSlash(c),
					});
				}
			}
		}

		return out;
	}, [
		query,
		filter,
		sessions,
		recentAgents,
		recentFiles,
		fileHits,
		filesLoading,
		spaceName,
		openAgent,
		openFilePath,
		runSlash,
		newSession,
		openFolder,
		enterSpace,
		runAndClose,
		openPageView,
		remoteLoggedIn,
		toggleRemote,
		setAgentMode,
		openSettings,
	]);

	// 收敛高亮下标范围
	useEffect(() => {
		setActiveIndex(i => {
			if (items.length === 0) {
				return 0;
			}
			return Math.min(i, items.length - 1);
		});
	}, [items]);

	// 保证高亮行可见
	useEffect(() => {
		const root = listRef.current;
		if (!root) {
			return;
		}
		const el = root.querySelector<HTMLElement>(`[data-palette-index="${activeIndex}"]`);
		el?.scrollIntoView({block: 'nearest'});
	}, [activeIndex, items]);

	const cycleFilter = useCallback((dir: 1 | -1) => {
		setFilter(prev => {
			const idx = FILTERS.findIndex(f => f.id === prev);
			const next = (idx + dir + FILTERS.length) % FILTERS.length;
			return FILTERS[next]!.id;
		});
		setActiveIndex(0);
	}, []);

	const onKeyDown = useCallback(
		(e: ReactKeyboardEvent) => {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				setActiveIndex(i => (items.length === 0 ? 0 : (i + 1) % items.length));
				return;
			}
			if (e.key === 'ArrowUp') {
				e.preventDefault();
				setActiveIndex(i =>
					items.length === 0 ? 0 : (i - 1 + items.length) % items.length,
				);
				return;
			}
			if (e.key === 'Tab') {
				e.preventDefault();
				cycleFilter(e.shiftKey ? -1 : 1);
				return;
			}
			if (e.key === 'Enter') {
				e.preventDefault();
				const item = items[activeIndex];
				if (item) {
					void item.run();
				}
			}
		},
		[items, activeIndex, cycleFilter],
	);

	// Global Ctrl/Cmd+K（capture，避免被输入框/其它监听吃掉）
	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) {
				return;
			}
			const isK = e.code === 'KeyK' || e.key.toLowerCase() === 'k';
			if (!isK) {
				return;
			}
			e.preventDefault();
			e.stopPropagation();
			useCommandPaletteStore.getState().togglePalette();
		};
		window.addEventListener('keydown', onKey, true);
		return () => window.removeEventListener('keydown', onKey, true);
	}, []);

	if (!mounted && !open) {
		return null;
	}

	let lastSection = '';

	return createPortal(
		<div
			ref={a11yRootRef}
			className={cn(
				'fixed inset-0 z-[9999] flex items-start justify-center bg-black/45 px-4 pt-[12vh] backdrop-blur-[3px]',
				visible
					? 'pointer-events-auto opacity-100'
					: 'pointer-events-none opacity-0',
			)}
			style={{transition: 'opacity 120ms ease'}}
			onMouseDown={e => {
				if (e.target === e.currentTarget) {
					close();
				}
			}}
		>
			<div
				role="dialog"
				aria-modal="true"
				aria-labelledby={titleId}
				className={cn(
					'xy-menu-flyout flex w-full max-w-[640px] flex-col overflow-hidden rounded-2xl border border-line/50',
					visible
						? 'translate-y-0 scale-100 opacity-100'
						: 'translate-y-2 scale-[0.98] opacity-0',
				)}
				style={{transition: 'opacity 120ms ease, transform 120ms ease'}}
				onKeyDown={onKeyDown}
				onMouseDown={e => e.stopPropagation()}
			>
				<h2 id={titleId} className="sr-only">
					搜索
				</h2>
				<div className="flex items-center gap-2 border-b border-line/60 px-4 py-3">
					<Search className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.75} />
					<input
						ref={inputRef}
						type="text"
						value={query}
						onChange={e => {
							setQuery(e.target.value);
							setActiveIndex(0);
						}}
						placeholder="Search agents, files, actions…"
						className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-mute"
						autoComplete="off"
						spellCheck={false}
					/>
				</div>

				<div className="flex flex-wrap gap-1 border-b border-line/50 px-3 py-2">
					{FILTERS.map(f => (
						<button
							key={f.id}
							type="button"
							onClick={() => {
								setFilter(f.id);
								setActiveIndex(0);
								inputRef.current?.focus();
							}}
							className={cn(
								'rounded-lg px-2.5 py-1 text-[12px] transition-colors',
								filter === f.id
									? 'bg-glass-hover text-ink'
									: 'text-mute hover:bg-glass-hover/60 hover:text-ink-soft',
							)}
						>
							{f.label}
						</button>
					))}
				</div>

				<div
					ref={listRef}
					className="max-h-[min(52vh,420px)] min-h-[120px] overflow-y-auto px-2 py-2"
					role="listbox"
					aria-label="搜索结果"
				>
					{items.length === 0 ? (
						<p className="px-3 py-8 text-center text-[13px] text-mute">
							{filesLoading ? '搜索文件中…' : '没有匹配结果'}
						</p>
					) : (
						items.map((item, index) => {
							const showSection = item.section !== lastSection;
							lastSection = item.section;
							return (
								<div key={item.id}>
									{showSection ? (
										<div className="px-2.5 pb-1 pt-2 font-mono text-[10px] uppercase tracking-wider text-mute">
											{item.section}
										</div>
									) : null}
									<button
										type="button"
										role="option"
										aria-selected={index === activeIndex}
										data-palette-index={index}
										onMouseEnter={() => setActiveIndex(index)}
										onClick={() => void item.run()}
										className={cn(
											'xy-menu-row flex w-full items-center gap-2.5 px-2.5 py-2 text-left',
											index === activeIndex && 'is-hover',
										)}
									>
										<span className="flex h-5 w-5 shrink-0 items-center justify-center">
											{item.icon}
										</span>
										<span className="min-w-0 flex-1 truncate text-[13px] text-ink">
											{item.label}
										</span>
										{item.detail ? (
											<span className="max-w-[40%] shrink-0 truncate text-[12px] text-mute">
												{item.detail}
											</span>
										) : null}
										{item.meta ? (
											<span className="shrink-0 font-mono text-[11px] text-mute">
												{item.meta}
											</span>
										) : null}
									</button>
								</div>
							);
						})
					)}
				</div>

				<div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line/50 px-4 py-2">
					<KbdHint>
						<Kbd label="↑↓" /> Select
					</KbdHint>
					<KbdHint>
						<Kbd label="↵" /> Open
					</KbdHint>
					<KbdHint>
						<Kbd label="⇥" /> or <Kbd label="⇧⇥" /> Change Filter
					</KbdHint>
					<KbdHint>
						<Kbd label="Esc" /> Close
					</KbdHint>
				</div>
			</div>
		</div>,
		document.body,
	);
}
