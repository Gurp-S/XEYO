import {memo, useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ChevronRight, Columns2, CornerDownLeft, Maximize2, Minimize2, X} from 'lucide-react';
import {PanelExpandOverlay} from '@/components/PanelExpandOverlay';
import {PaneResizeHandle} from '@/components/PaneResizeHandle';
import {PaneSlot} from '@/components/PaneSlot';
import {useHoverScroll} from '@/hooks/useHoverScroll';
import {usePaneResize} from '@/hooks/usePaneResize';
import {usePresence} from '@/hooks/usePresence';
import {cn} from '@/lib/utils';
import {execWorkspaceTerminal, gitLog, gitStatus, type GitLogResult, type GitStatusEntry, type GitStatusResult} from '@/lib/api';
import {groupTranscript, type TurnItem} from '@/lib/groupTranscript';
import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore, PANE_WIDTH_MAX, PANE_WIDTH_MIN, isSmoothnessOn} from '@/stores/settingsStore';
import {useWorkspaceStore, type WorkspaceTool} from '@/stores/workspaceStore';
import {useExplorerStore} from '@/stores/explorerStore';
import {AgentMapPanel} from '@/components/AgentMapPanel';
import {BrowserPreviewPanel} from '@/components/BrowserPreviewPanel';
import {WorkspaceToolSubtitleContext, usePanelSubtitle} from '@/components/workspaceToolSubtitle';
const LABELS: Record<WorkspaceTool, string> = {
	git: 'Git',
	terminal: '终端',
	history: '历史命令',
	commits: '提交记录',
	map: '地图',
	browser: '浏览器',
};

/* ==== 副标题上报：标题栏只在面板顶栏渲染一次，各 Body 通过它把
 * 「当前对话 · N 条」「PS 根目录」等副标题上报到顶栏，避免出现两行标题 ==== */

/* ==== 历史命令行：当前对话的所有命令行（终端风格展示） ==== */
/**
 * 把 tool.input（对 Bash 等结构化工具是 JSON.stringify 后的字符串）还原为
 * 可读的多行命令文本。多行命令在 JSON 里会变成字面 \n 转义，直接渲染时
 * whitespace-pre-wrap 无法换行，这里还原成真实换行符以便分行阅读。
 */
function commandDisplayText(input: string): string {
	try {
		const parsed = JSON.parse(input) as unknown;
		if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
			const command = (parsed as Record<string, unknown>).command;
			if (typeof command === 'string') {
				return command;
			}
		}
	} catch {
		/* 非 JSON，走下方转义还原 */
	}
	return input.replace(/\\r\\n|\\n/g, '\n').replace(/\\t/g, '\t');
}

function collectCommands(messages: ChatMessageLike[]): Array<{name: string; input: string; display: string}> {
	try {
		const blocks = groupTranscript(messages);
		const items = blocks.flatMap(b => (b.kind === 'turn' ? b.items : []));
		return items
			.filter((it): it is Extract<TurnItem, {kind: 'tool'}> => it.kind === 'tool')
			.filter(it => it.tool.name && it.tool.input)
			.map(it => ({name: it.tool.name, input: it.tool.input, display: commandDisplayText(it.tool.input)}));
	} catch {
		return [];
	}
}

type ChatMessageLike = Parameters<typeof groupTranscript>[0][number];

function HistoryCommandsBody() {
	const messages = useChatStore(s => (s.activeId ? s.messagesById[s.activeId] ?? [] : []));
	const commands = useMemo(() => collectCommands(messages), [messages]);
	usePanelSubtitle(`当前对话 · ${commands.length} 条`);
	const [copied, setCopied] = useState<string | null>(null);
	// 文件树式折叠：每个节点独立展开/收起（常挂载 grid-rows 平滑动画）。
	const [expanded, setExpanded] = useState<Record<string, boolean>>({});

	const onCopy = async (input: string) => {
		try {
			await navigator.clipboard.writeText(input);
			setCopied(input);
			setTimeout(() => setCopied(null), 1500);
		} catch {
			/* 忽略 */
		}
	};

	return (
		<div className="flex h-full flex-col">
			<div className="xy-hover-scroll min-h-0 flex-1 overflow-auto px-1.5 py-2">
				{commands.length === 0 ? (
					<p className="py-4 text-center text-[12px] text-mute">当前对话还没有命令行</p>
				) : (
					commands.map((c, i) => {
						const key = `${c.name}-${i}`;
						const open = Boolean(expanded[key]);
						return (
							<div key={key} className="group">
								<div className="flex items-center gap-1.5 rounded-md pr-1 text-left text-[13px] transition-colors hover:bg-glass-hover">
									<button
										type="button"
										aria-expanded={open}
										onClick={() => setExpanded(o => ({...o, [key]: !open}))}
										className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-ink-soft"
									>
										<span className="flex w-3.5 shrink-0 items-center justify-center text-mute">
											<ChevronRight
												className={cn(
													'h-3.5 w-3.5 transition-transform duration-150',
													open && 'rotate-90',
												)}
												strokeWidth={1.8}
											/>
										</span>
										<span className="min-w-0 flex-1 truncate">
											{c.display.split('\n')[0] || '(空命令)'}
										</span>
									</button>
									<span className="shrink-0 rounded bg-glass-strong px-1 py-0.5 font-mono text-[10px] leading-none text-mute">
										{c.name}
									</span>
									<button
										type="button"
										className="shrink-0 rounded px-1 font-mono text-[10px] text-mute opacity-0 transition-opacity hover:text-ink group-hover:opacity-100 group-focus-within:opacity-100 xy-hover-reveal"
										title="复制命令"
										aria-label="复制命令"
										onClick={() => void onCopy(c.input)}
									>
										{copied === c.input ? '已复制' : '复制'}
									</button>
								</div>
								<div
									className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')}
									aria-hidden={!open}
								>
									<ul className="min-h-0 overflow-hidden">
									<li className="whitespace-pre-wrap break-all rounded-md px-7 py-1 text-[12px] leading-5 text-ink-soft">
										{c.display}
									</li>
									</ul>
								</div>
							</div>
						);
					})
				)}
			</div>
		</div>
	);
}

function StatusGroup({title, entries, tone}: {title: string; entries: GitStatusEntry[]; tone: 'ok' | 'warn' | 'mute'}) {
	if (entries.length === 0) {
		return null;
	}
	const color = tone === 'ok' ? 'text-ok' : tone === 'warn' ? 'text-danger' : 'text-ink-soft';
	return (
		<div className="mb-2">
			<div className="mb-1 text-[11px] text-mute">
				{title} <span className={color}>({entries.length})</span>
			</div>
			{entries.map(e => (
				<div key={e.path} className="flex items-center gap-2 rounded px-1 py-0.5 leading-5 hover:bg-glass-hover/50">
					<span className={cn('w-7 shrink-0 text-right text-[10px]', color)}>{e.status}</span>
					<span className="min-w-0 flex-1 truncate">{e.path}</span>
				</div>
			))}
		</div>
	);
}

/* ==== 提交记录：全部 git log（终端风格，单条最多两行，与「历史命令」一致） ==== */
function CommitsBody() {
	const [log, setLog] = useState<GitLogResult | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [copied, setCopied] = useState<string | null>(null);
	// 文件树式折叠：每个提交独立展开/收起（常挂载 grid-rows 平滑动画）。
	const [expanded, setExpanded] = useState<Record<string, boolean>>({});

	useEffect(() => {
		let disposed = false;
		void gitLog(500)
			.then(result => {
				if (!disposed) {
					setLog(result);
					setError(null);
				}
			})
			.catch(err => {
				if (!disposed) {
					setError(err instanceof Error ? err.message : String(err));
				}
			});
		return () => {
			disposed = true;
		};
	}, []);

	const onCopy = async (hash: string) => {
		try {
			await navigator.clipboard.writeText(hash);
			setCopied(hash);
			setTimeout(() => setCopied(null), 1500);
		} catch {
			/* 忽略 */
		}
	};

	const commits = log?.repo ? log.commits : [];
	usePanelSubtitle(log?.repo ? `git log · ${commits.length} 条` : '');

	return (
		<div className="flex h-full flex-col">
			<div className="xy-hover-scroll min-h-0 flex-1 overflow-auto px-1.5 py-2">
				{error ? (
					<p className="py-2 text-[11px] text-danger">加载失败：{error}</p>
				) : !log ? (
					<p className="py-2 text-[11px] text-mute/70">加载中…</p>
				) : !log.repo ? (
					<p className="py-2 text-[11px] text-mute/70">当前工作区不是 Git 仓库</p>
				) : commits.length === 0 ? (
					<p className="py-3 text-center text-[12px] text-mute">暂无提交</p>
				) : (
					<ul>
						{commits.map(c => {
							const open = Boolean(expanded[c.hash]);
							return (
								<li key={c.hash} className="group">
									<div className="flex items-center gap-1.5 rounded-md pr-1 text-left text-[13px] transition-colors hover:bg-glass-hover">
										<button
											type="button"
											title={c.hash}
											aria-expanded={open}
											onClick={() => setExpanded(o => ({...o, [c.hash]: !open}))}
											className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-ink-soft"
										>
											<span className="flex w-3.5 shrink-0 items-center justify-center text-mute">
												<ChevronRight
													className={cn(
														'h-3.5 w-3.5 transition-transform duration-150',
														open && 'rotate-90',
													)}
													strokeWidth={1.8}
												/>
											</span>
											<span className="min-w-0 flex-1 truncate">{c.subject}</span>
											<span className="shrink-0 whitespace-nowrap text-[10px] text-mute">
												{c.author} · {c.date}
											</span>
										</button>
										<span className="shrink-0 font-mono text-[10px] text-mute">{c.short}</span>
										<button
											type="button"
											className="shrink-0 rounded px-1 font-mono text-[10px] text-mute opacity-0 transition-opacity hover:text-ink group-hover:opacity-100 group-focus-within:opacity-100 xy-hover-reveal"
											title="复制完整 hash"
											aria-label="复制完整 hash"
											onClick={() => void onCopy(c.hash)}
										>
											{copied === c.hash ? '已复制' : 'hash'}
										</button>
									</div>
									<div
										className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')}
										aria-hidden={!open}
									>
										<ul className="min-h-0 overflow-hidden">
											<li className="px-7 py-1 text-[12px] leading-5 text-ink-soft">
												<span className="text-ink">{c.subject}</span>
												<span className="ml-2 font-mono text-[10px] text-mute">
													{c.author} · {c.date} · <span className="select-all">{c.hash}</span>
												</span>
											</li>
										</ul>
									</div>
								</li>
							);
						})}
					</ul>
				)}
			</div>
		</div>
	);
}

function GitBody() {
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [status, setStatus] = useState<GitStatusResult | null>(null);

	useEffect(() => {
		let disposed = false;
		void (async () => {
			try {
				const next = await gitStatus();
				if (!disposed) {
					setStatus(next);
					setError(null);
				}
			} catch (err) {
				if (!disposed) {
					setError(err instanceof Error ? err.message : String(err));
				}
			} finally {
				if (!disposed) {
					setLoading(false);
				}
			}
		})();
		return () => {
			disposed = true;
		};
	}, []);
	usePanelSubtitle(status?.repo && status.branch ? `${status.branch}${status.head ? ` · ${status.head}` : ''}` : '');

	return (
		<div className="flex h-full flex-col">
			<div className="min-h-0 flex-1 overflow-auto px-3 py-3 font-mono text-[12px] leading-6 text-ink-soft">
				{loading ? <span className="text-mute">加载中…</span> : null}
				{error ? (
					<span className="text-danger">加载失败：{error}</span>
				) : null}
				{!loading && !error && !status?.repo ? (
					<span className="text-mute">当前工作区不是 Git 仓库</span>
				) : null}
				{status?.repo ? (
					status.clean ? (
						<span className="text-ok">✓ 工作区干净</span>
					) : (
						<>
							<StatusGroup title="已暂存" entries={status.staged ?? []} tone="ok" />
							<StatusGroup title="未暂存" entries={status.unstaged ?? []} tone="warn" />
							<StatusGroup title="未跟踪" entries={status.untracked ?? []} tone="mute" />
						</>
					)
				) : null}
			</div>
		</div>
	);
}

type TermLine = {kind: 'in' | 'out' | 'err' | 'info'; text: string};

function TerminalBody() {
	const root = useExplorerStore(s => s.loadedRoot);
	const [cmd, setCmd] = useState('');
	const [lines, setLines] = useState<TermLine[]>([]);
	const [busy, setBusy] = useState(false);
	const [history, setHistory] = useState<string[]>([]);
	const [cursor, setCursor] = useState(-1);
	const scrollerRef = useRef<HTMLDivElement | null>(null);
	usePanelSubtitle(root ? `PS ${root}` : '');

	useEffect(() => {
		scrollerRef.current?.scrollTo({top: scrollerRef.current.scrollHeight});
	}, [lines]);

	const run = async (text?: string) => {
		const value = (text ?? cmd).trim();
		if (!value || busy) {
			return;
		}
		setCmd('');
		setCursor(-1);
		setLines(l => [...l, {kind: 'in', text: value}]);
		setBusy(true);
		try {
			const res = await execWorkspaceTerminal(value, 120);
			if (res.stdout) {
				setLines(l => [...l, {kind: 'out', text: res.stdout.replace(/\s+$/, '')}]);
			}
			if (res.stderr) {
				setLines(l => [...l, {kind: 'err', text: res.stderr.replace(/\s+$/, '')}]);
			}
			if (res.timed_out) {
				setLines(l => [...l, {kind: 'info', text: `[命令超时（已执行 ${res.elapsed_ms}ms）]`}]);
			}
			setLines(l => [
				...l,
				{kind: 'info', text: `[退出码 ${res.exit_code ?? '—'} · ${res.elapsed_ms}ms${res.truncated.stdout || res.truncated.stderr ? ' · 输出已截断' : ''}]`},
			]);
			setHistory(h => [value, ...h.filter(x => x !== value)].slice(0, 30));
		} catch (err) {
			setLines(l => [...l, {kind: 'err', text: String(err instanceof Error ? err.message : err)}]);
		} finally {
			setBusy(false);
		}
	};

	const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			void run();
			return;
		}
		if (history.length === 0) {
			return;
		}
		if (e.key === 'ArrowUp') {
			e.preventDefault();
			const next = cursor === -1 ? 0 : Math.min(cursor + 1, history.length - 1);
			setCursor(next);
			setCmd(history[next]);
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			const next = cursor - 1;
			setCursor(next);
			setCmd(next === -1 ? '' : history[next]);
		}
	};

	return (
		<div className="flex h-full flex-col">
			<div ref={scrollerRef} className="xy-hover-scroll min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[12px] leading-6 text-ink-soft">
				{lines.map((line, i) => (
					<div key={i} className="whitespace-pre-wrap break-words">
						{line.kind === 'in' ? (
							<>
								<span className="text-accent">{root ? `PS ${root}>` : '❯'}</span>{' '}
								<span className="text-ink">{line.text}</span>
							</>
						) : line.kind === 'err' ? (
							<span className="whitespace-pre-wrap text-danger">{line.text}</span>
						) : line.kind === 'info' ? (
							<span className="text-mute">{line.text}</span>
						) : (
							<span className="whitespace-pre-wrap">{line.text}</span>
						)}
					</div>
				))}
				{lines.length === 0 ? (
					<div className="text-mute">
						在工作区根目录执行 shell 命令。支持方向键回看历史。
						<br />
						例：<span className="text-ink-soft">npm run dev</span>、<span className="text-ink-soft">git status</span>
					</div>
				) : null}
			</div>
			<div className="flex shrink-0 items-center gap-1 border-t border-line/40 px-2 py-1.5">
				<span className="shrink-0 font-mono text-[12px] text-accent">{root ? '>' : '❯'}</span>
				<input
					type="text"
					value={cmd}
					onChange={e => setCmd(e.target.value)}
					onKeyDown={onKeyDown}
					disabled={busy}
					placeholder="输入命令，回车执行"
					aria-label="终端命令"
					className="min-w-0 flex-1 bg-transparent font-mono text-[12px] text-ink outline-none placeholder:text-mute/60"
				/>
				<button
					type="button"
					className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
					aria-label="运行命令"
					title="运行命令"
					disabled={busy || !cmd.trim()}
					onClick={() => void run()}
				>
					<CornerDownLeft className="h-3.5 w-3.5" />
				</button>
			</div>
		</div>
	);
}

function ToolBody({tool}: {tool: WorkspaceTool}) {
	if (tool === 'git') {
		return <GitBody />;
	}
	if (tool === 'terminal') {
		return <TerminalBody />;
	}
	if (tool === 'history') {
		return <HistoryCommandsBody />;
	}
	if (tool === 'commits') {
		return <CommitsBody />;
	}
	if (tool === 'map') {
		return <AgentMapPanel />;
	}
	if (tool === 'browser') {
		return <BrowserPreviewPanel />;
	}
	return <CommitsBody />;
}

export const WorkspaceToolPanel = memo(function WorkspaceToolPanel() {
	const activeTool = useWorkspaceStore(s => s.activeTool);
	const setActiveTool = useWorkspaceStore(s => s.setActiveTool);
	const navHidden = useWorkspaceStore(s => s.navHidden);
	const toggleNavHidden = useWorkspaceStore(s => s.toggleNavHidden);
	const workspaceOpen = useWorkspaceStore(s => s.open);
	const collapseWorkspace = useWorkspaceStore(s => s.collapseWorkspace);
	// 功能区宽度与文件预览共用 previewWidth：切换功能区界面（git/终端 ↔ 文件预览）
	// 保持宽度不变；树导航宽度（explorerWidth）独立。
	const width = useSettingsStore(s => s.previewWidth);
	const explorerWidth = useSettingsStore(s => s.explorerWidth);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const updateSettings = useSettingsStore(s => s.update);
	// 各 Body 上报的副标题（如「当前对话 · N 条」「PS 根目录」），显示在顶栏标题右侧。
	const [subtitle, setSubtitle] = useState('');
	// 「放大到全屏」开关：与文件预览放大同款形态，覆盖当前功能面板（地图/浏览器/Git/终端/历史/提交）。
	const [expanded, setExpanded] = useState(false);
	const hover = useHoverScroll();
	const paneRef = useRef<HTMLElement | null>(null);
	const onWidth = useCallback(
		(next: number) => updateSettings({previewWidth: next}),
		[updateSettings],
	);
	// 仅在工作区打开时隐藏树导航才有意义；关闭时不扩宽、不出按钮。
	const navEff = workspaceOpen && navHidden;
	// 隐藏树导航时，功能面板占满整个工作区（自身宽度 + 工作区侧栏宽度）。
	const displayWidth = width + (navEff ? explorerWidth : 0);
	// 拖拽钳制在“槽宽域”进行（见 usePaneResize）：槽宽上限 = 窗口可用宽 -
	// 聊天区最小列宽，避免窄窗口下拖满后把聊天区顶出视口。
	const CHAT_COL_MIN = 180;
	const slotOf = useCallback(
		(base: number) => base + (navEff ? explorerWidth : 0),
		[navEff, explorerWidth],
	);
	const slotMax = useCallback(() => {
		const host = document.querySelector<HTMLElement>('.xy-pane-chat-host');
		const avail = host
			? host.clientWidth
			: document.querySelector<HTMLElement>('.xy-pane-row')?.clientWidth ??
				PANE_WIDTH_MAX + PANE_WIDTH_MAX;
		return Math.max(PANE_WIDTH_MIN, avail - CHAT_COL_MIN - 2);
	}, []);
	const {dragging, onResizeStart} = usePaneResize(
		width,
		onWidth,
		PANE_WIDTH_MIN,
		PANE_WIDTH_MAX,
		{invert: true, paneRef, slotOf, slotMax},
	);
	const displayWidthShown = Math.min(
		displayWidth,
		slotMax(),
	);
	// 功能区占满整个工作区（只剩左边内容）时，关闭直接收起整个工作区，
	// 避免关掉之后留下一段没有树导航的死空档；收起的是用户显式关闭的面板，不再恢复。
	const onClose = () => {
		setActiveTool(null);
		if (navEff) {
			collapseWorkspace();
		}
	};
	// 工作区未展开时不显示功能面板，收起状态下无任何工作区按钮。
	const open = Boolean(activeTool && workspaceOpen);
	// 功能面板关闭（activeTool 置空或工作区收起）时，放大态一并复位。
	useEffect(() => {
		if (!open) {
			setExpanded(false);
		}
	}, [open]);
	// 功能界面切换（预览 ↔ 工具面板）时硬切，不播滑动动画。
	const previewState = useExplorerStore(
		s => Boolean(s.selectedPath || s.reviewDiff || s.loadingFile),
	);
	const previewOn = workspaceOpen && previewState;
	const previewOnRef = useRef(previewOn);
	const hardSwitch = previewOn !== previewOnRef.current;
	previewOnRef.current = previewOn;
	const {mounted, shown} = usePresence(open, smoothness ? 200 : 0, 0);
	const hoverRef = useRef<HTMLDivElement | null>(null);

	useEffect(() => {
		hoverRef.current && hover.scrollerRef(hoverRef.current);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	if (!smoothness && !mounted) {
		return null;
	}

	const headerBar = (
		<div className="flex h-10 shrink-0 items-center justify-between gap-2 px-2">
			<div className="flex min-w-0 items-center gap-2 px-1">
				<span className="shrink-0 text-[12px] text-ink-soft">
					{activeTool ? LABELS[activeTool] : ''}
				</span>
				{subtitle ? (
					<span className="min-w-0 truncate text-[11px] text-mute">{subtitle}</span>
				) : null}
			</div>
			<div className="flex shrink-0 items-center gap-0.5">
				{activeTool && navEff ? (
					<button
						type="button"
						className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
						aria-label="展开右边内容"
						title="展开右边内容"
						onClick={toggleNavHidden}
					>
						<Columns2 className="h-3.5 w-3.5" />
					</button>
				) : null}
				{activeTool ? (
					<button
						type="button"
						className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
						aria-label={expanded ? '退出放大' : '放大面板'}
						title={expanded ? '退出放大' : '放大面板'}
						onClick={() => setExpanded(v => !v)}
					>
						{expanded ? (
							<Minimize2 className="h-3.5 w-3.5" strokeWidth={1.75} />
						) : (
							<Maximize2 className="h-3.5 w-3.5" strokeWidth={1.75} />
						)}
					</button>
				) : null}
				{activeTool ? (
					<button
						type="button"
						className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
						aria-label="关闭功能面板"
						onClick={onClose}
					>
						<X className="h-3.5 w-3.5" />
					</button>
				) : null}
			</div>
		</div>
	);

	const body = (
		<WorkspaceToolSubtitleContext.Provider value={setSubtitle}>
			<div
				ref={hoverRef}
				className={cn(
					'min-h-0 flex-1',
					activeTool === 'map' ? 'overflow-hidden' : 'overflow-auto',
				)}
			>
				{activeTool ? <ToolBody tool={activeTool} /> : null}
			</div>
		</WorkspaceToolSubtitleContext.Provider>
	);

	// 放大：整块面板进入 fixed inset-0 全屏遮罩（复用 header + body，Esc 退出）。
	if (expanded) {
		return (
			<PanelExpandOverlay open onClose={() => setExpanded(false)}>
				{headerBar}
				{body}
			</PanelExpandOverlay>
		);
	}

	return (
		<PaneSlot
			as="section"
			open={open}
			mounted={mounted}
			shown={shown}
			width={displayWidthShown}
			smoothness={smoothness}
			dragging={dragging}
			side="right"
			paneRef={paneRef}
			instant={hardSwitch}
			className={cn(
				'xy-workspace-chrome bg-transparent',
				!open && 'pointer-events-none',
			)}
			onMouseEnter={hover.onMouseEnter}
			onMouseLeave={hover.onMouseLeave}
		>
			{open || mounted ? (
				<PaneResizeHandle
					edge="left"
					dragging={dragging}
					label="拖动调整功能面板宽度"
					onMouseDown={onResizeStart}
				/>
			) : null}
			{headerBar}
			{body}
		</PaneSlot>
	);
});
