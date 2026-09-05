import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {useShallow} from 'zustand/react/shallow';
import {
	ChevronLeft,
	ChevronRight,
	ExternalLink,
	Pause,
	Play,
	RefreshCw,
	Sparkles,
	Square,
	Undo2,
	X,
} from 'lucide-react';
import {AgentMapCanvas, useLaneLayout} from '@/components/AgentMapCanvas';
import {usePanelSubtitle} from '@/components/workspaceToolSubtitle';
import {cn} from '@/lib/utils';
import {
	buildOpsTrail,
	buildReplayScript,
	collectAgentPresence,
	latestHitForNode,
	type AgentPresenceHit,
} from '@/lib/agentPresence';
import {filterGraph, focusFiles, pathsLooselyEqual, type LaidNode} from '@/lib/codeMapLayout';
import {
	buildTurnWorkflow,
	turnWorkflowToLanes,
} from '@/lib/turnWorkflow';
import {
	explainMapNode,
	fetchWorkspaceOutline,
	type WorkspaceOutlineSymbol,
} from '@/lib/workspaceMapApi';
import {openWorkspacePreview} from '@/lib/openWorkspacePreview';
import type {MultiAgentTaskView} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {useCodeMapStore, type MapViewMode} from '@/stores/codeMapStore';

const VIEW_TABS: Array<{id: MapViewMode; label: string}> = [
	{id: 'turn', label: '本轮'},
	{id: 'code', label: '代码'},
	{id: 'architecture', label: '架构'},
	{id: 'authored', label: '图稿'},
];

const EMPTY_MESSAGES: ChatMessage[] = [];
const EMPTY_TASKS: MultiAgentTaskView[] = [];

export function AgentMapPanel() {
	const {
		graph,
		loading,
		error,
		view,
		query,
		selectedId,
		cardId,
		cardKind,
		authored,
		summaries,
		summaryLoading,
	} = useCodeMapStore(
		useShallow(s => ({
			graph: s.graph,
			loading: s.loading,
			error: s.error,
			view: s.view,
			query: s.query,
			selectedId: s.selectedId,
			cardId: s.cardId,
			cardKind: s.cardKind,
			authored: s.authored,
			summaries: s.summaries,
			summaryLoading: s.summaryLoading,
		})),
	);
	const load = useCodeMapStore(s => s.load);
	const reload = useCodeMapStore(s => s.reload);
	const setView = useCodeMapStore(s => s.setView);
	const setQuery = useCodeMapStore(s => s.setQuery);
	const setCard = useCodeMapStore(s => s.setCard);
	const setSummary = useCodeMapStore(s => s.setSummary);
	const setSummaryLoading = useCodeMapStore(s => s.setSummaryLoading);

	const messages = useChatStore(s =>
		s.activeId ? (s.messagesById[s.activeId] ?? EMPTY_MESSAGES) : EMPTY_MESSAGES,
	);
	const tasks = useChatStore(s =>
		s.activeId
			? (s.multiAgentTasksBySession[s.activeId] ?? EMPTY_TASKS)
			: EMPTY_TASKS,
	);
	const spaceRoot = useChatStore(s => {
		const space = s.spaces.find(sp => sp.id === s.activeSpaceId);
		return space?.rootPath?.trim() || '';
	});

	const [symbols, setSymbols] = useState<WorkspaceOutlineSymbol[]>([]);
	const [symbolsFor, setSymbolsFor] = useState<string | null>(null);
	const [symbolsLoading, setSymbolsLoading] = useState(false);
	/** 强制 Canvas 跳镜：id#seq，同 id 也可再触发。 */
	const [focusRequest, setFocusRequest] = useState<string | null>(null);
	const [focusHistLen, setFocusHistLen] = useState(0);
	const focusHistRef = useRef<string[]>([]);
	const skipHistRef = useRef(false);

	useEffect(() => {
		// 本轮/图稿不依赖全仓图：推迟扫描，避免一开地图就卡死超大仓。
		if (view === 'code' || view === 'architecture') {
			void load(spaceRoot);
		}
	}, [load, spaceRoot, view]);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key !== 'Escape') {
				return;
			}
			const t = e.target as HTMLElement | null;
			if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) {
				return;
			}
			if (useCodeMapStore.getState().cardId) {
				setCard(null);
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [setCard]);

	const hits = useMemo(
		() => collectAgentPresence(messages, spaceRoot || graph?.cwd || '', tasks),
		[messages, spaceRoot, graph?.cwd, tasks],
	);
	const turnHits = useMemo(() => {
		let since = 0;
		for (let i = messages.length - 1; i >= 0; i -= 1) {
			if (messages[i]?.role === 'user') {
				since = messages[i]!.createdAt;
				break;
			}
		}
		if (!since) {
			return hits;
		}
		return hits.filter(h => h.createdAt >= since);
	}, [hits, messages]);
	const opsTrail = useMemo(() => buildOpsTrail(turnHits, 8), [turnHits]);
	const replayScript = useMemo(() => {
		const src = turnHits.length >= 2 ? turnHits : hits;
		return buildReplayScript(src, 40);
	}, [turnHits, hits]);
	const [replayIdx, setReplayIdx] = useState<number | null>(null);
	const [replayPlaying, setReplayPlaying] = useState(false);
	const [summaryOpen, setSummaryOpen] = useState(false);
	const replayFrame =
		replayIdx != null ? (replayScript[replayIdx] ?? null) : null;
	const live = useMemo(() => hits.filter(h => h.running), [hits]);
	const headline = live[live.length - 1] ?? hits[hits.length - 1] ?? null;

	const subtitle = headline
		? `${headline.verb} ${headline.relPath.split('/').pop() ?? headline.relPath}`
		: graph
			? `${graph.fileCount} 个文件${graph.truncated ? '（已截断）' : ''}`
			: '';
	usePanelSubtitle(subtitle);

	const turnSteps = useMemo(() => buildTurnWorkflow(messages), [messages]);
	const turnTouchedPaths = useMemo(() => {
		const paths: string[] = [];
		const seen = new Set<string>();
		for (const hit of turnHits) {
			const p = hit.relPath.replace(/\\/g, '/');
			if (!p || seen.has(p)) {
				continue;
			}
			seen.add(p);
			paths.push(p);
		}
		return paths;
	}, [turnHits]);
	const turnBundle = useMemo(
		() => turnWorkflowToLanes(turnSteps, turnTouchedPaths),
		[turnSteps, turnTouchedPaths],
	);

	const archItems = useMemo(() => {
		const pkgs = graph?.packages ?? [];
		// 架构视图不用 query 过滤：query 曾被用来做「点包下钻」，
		// 会把架构滤成单节点；下钻过滤只作用在代码视图。
		return pkgs.map(p => ({
			id: p.id,
			name: p.name,
			layer: p.layer,
			files: p.files,
		}));
	}, [graph]);

	const codeBundle = useMemo(() => {
		if (!graph) {
			return {files: [] as Array<{id: string; name: string; layer: string}>, edges: [] as Array<{from: string; to: string}>};
		}
		const focusIds = hits.map(h => h.relPath);
		const focused = focusFiles(graph.files, graph.fileEdges, focusIds);
		return {
			files: filterGraph(
				focused.files.map(f => ({
					id: f.id,
					name: f.name,
					layer: f.layer,
				})),
				query,
			),
			edges: focused.edges,
		};
	}, [graph, hits, query]);

	const authoredItems = useMemo(() => {
		if (!authored) {
			return {
				items: [] as Array<{id: string; name: string; layer: string}>,
				edges: [] as Array<{from: string; to: string}>,
			};
		}
		const items = filterGraph(
			authored.nodes.map(n => ({
				id: n.id,
				name: n.label,
				layer: n.lane || 'core',
			})),
			query,
		);
		return {items, edges: authored.edges.map(e => ({from: e.from, to: e.to}))};
	}, [authored, query]);

	const symbolItems = useMemo(() => {
		if (!symbols.length) {
			return [] as Array<{id: string; name: string; layer: string}>;
		}
		return filterGraph(
			symbols.map(s => ({
				id: `${symbolsFor ?? ''}#${s.parent ? `${s.parent}.` : ''}${s.name}`,
				name: s.parent ? `${s.parent}.${s.name}` : s.name,
				layer: s.kind === 'class' || s.kind === 'interface' ? 'core' : 'tools',
			})),
			query,
		);
	}, [symbols, symbolsFor, query]);

	const showingSymbols =
		view === 'code' && Boolean(symbolsFor) && symbols.length > 0;

	const items =
		view === 'architecture'
			? archItems
			: view === 'turn'
				? turnBundle.items
				: view === 'authored'
					? authoredItems.items
					: showingSymbols
						? symbolItems
						: codeBundle.files;

	const edges =
		view === 'architecture'
			? (graph?.packageEdges ?? [])
			: view === 'turn'
				? turnBundle.edges
				: view === 'authored'
					? authoredItems.edges
					: showingSymbols
						? []
						: codeBundle.edges;

	const kind: LaidNode['kind'] =
		view === 'architecture'
			? 'package'
			: view === 'turn'
				? 'step'
				: view === 'authored'
					? 'authored'
					: showingSymbols
						? 'symbol'
						: 'file';

	const {hostRef, laid} = useLaneLayout(items, edges, kind);

	const turnTrail = useMemo(() => {
		if (view !== 'turn') {
			return null;
		}
		return turnBundle.edges;
	}, [view, turnBundle.edges]);

	const followId = useMemo(() => {
		if (view === 'turn') {
			const running = turnSteps.filter(s => s.running);
			return running[running.length - 1]?.id ?? null;
		}
		if (!live.length) {
			return null;
		}
		const last = live[live.length - 1]!;
		if (view === 'architecture') {
			const pkg = graph?.files.find(
				f =>
					f.id === last.relPath ||
					last.relPath.endsWith(`/${f.id}`) ||
					f.id.endsWith(`/${last.relPath}`),
			)?.pkg;
			return (
				pkg ??
				graph?.packages.find(
					p => last.relPath === p.id || last.relPath.startsWith(`${p.id}/`),
				)?.id ??
				null
			);
		}
		if (view === 'code' && !showingSymbols) {
			return (
				codeBundle.files.find(
					f =>
						f.id === last.relPath ||
						last.relPath.endsWith(`/${f.id}`) ||
						f.id.endsWith(`/${last.relPath}`),
				)?.id ?? last.relPath
			);
		}
		if (showingSymbols && last.symbol && symbolsFor) {
			return `${symbolsFor}#${last.symbol}`;
		}
		return null;
	}, [
		view,
		turnSteps,
		live,
		graph,
		codeBundle.files,
		showingSymbols,
		symbolsFor,
	]);

	const stepRunningIds = useMemo(
		() => new Set(turnSteps.filter(s => s.running).map(s => s.id)),
		[turnSteps],
	);
	const stepSeenIds = useMemo(
		() => new Set(turnSteps.map(s => s.id)),
		[turnSteps],
	);
	const stepVerbs = useMemo(
		() => new Map(turnSteps.map(s => [s.id, s.verb])),
		[turnSteps],
	);

	const hitByNodeId = useMemo(() => {
		const m = new Map<string, AgentPresenceHit>();
		for (const node of laid.nodes) {
			if (node.kind !== 'file' && node.kind !== 'package') {
				continue;
			}
			const hit = latestHitForNode(hits, node.id, node.kind);
			if (hit) {
				m.set(node.id, hit);
			}
		}
		return m;
	}, [laid.nodes, hits]);

	const searchHitIds = useMemo(() => {
		const q = query.trim().toLowerCase();
		if (q.length < 2) {
			return undefined;
		}
		const s = new Set<string>();
		for (const node of laid.nodes) {
			if (
				node.id.toLowerCase().includes(q) ||
				node.name.toLowerCase().includes(q) ||
				node.layer.toLowerCase().includes(q)
			) {
				s.add(node.id);
			}
		}
		return s;
	}, [laid.nodes, query]);

	const onSelect = useCallback(
		async (id: string, nodeKind: LaidNode['kind']) => {
			setCard(id, nodeKind);
			if (nodeKind === 'package') {
				// 先切视图（会清空 query），再写入包过滤，避免污染架构视图。
				setView('code');
				setQuery(id);
				setSymbols([]);
				setSymbolsFor(null);
				return;
			}
			if (nodeKind === 'file') {
				setSymbolsLoading(true);
				setSymbolsFor(id);
				try {
					const out = await fetchWorkspaceOutline(id);
					setSymbols(out.symbols ?? []);
				} catch {
					setSymbols([]);
				} finally {
					setSymbolsLoading(false);
				}
			}
		},
		[setCard, setView, setQuery],
	);

	const cardHit: AgentPresenceHit | null = useMemo(() => {
		if (!cardId) {
			return null;
		}
		if (cardKind === 'file' || cardKind === 'package') {
			return latestHitForNode(hits, cardId, cardKind);
		}
		if (cardKind === 'step') {
			const step = turnBundle.stepById.get(cardId);
			if (!step) {
				return null;
			}
			return {
				relPath: step.relPath ?? step.detail,
				verb: step.verb,
				running: step.running,
				toolName: step.toolName,
				createdAt: step.createdAt,
			};
		}
		if (cardKind === 'authored' && authored) {
			const node = authored.nodes.find(n => n.id === cardId);
			if (!node?.file) {
				return null;
			}
			return latestHitForNode(hits, node.file, 'file');
		}
		return null;
	}, [cardId, cardKind, hits, turnBundle.stepById, authored]);

	const openRelFile = (relPath: string) => {
		const path = relPath.trim().replace(/\\/g, '/');
		if (!path) {
			return;
		}
		// 有改动 → diff；未动 → 文件。地图关开由 explorer selectedPath XOR 处理。
		void openWorkspacePreview(path, {preferDiff: true});
	};

	const openFileFromCard = () => {
		if (!cardId) {
			return;
		}
		let path = cardId;
		if (cardKind === 'step') {
			path = turnBundle.stepById.get(cardId)?.relPath ?? '';
		} else if (cardKind === 'authored') {
			path = authored?.nodes.find(n => n.id === cardId)?.file ?? '';
		} else if (cardKind === 'symbol' && symbolsFor) {
			path = symbolsFor;
		} else if (cardKind === 'package') {
			return;
		}
		openRelFile(path);
	};

	const onExplain = async () => {
		if (!cardId || (cardKind !== 'file' && cardKind !== 'package')) {
			return;
		}
		if (summaries[cardId]) {
			setSummaryOpen(open => !open);
			return;
		}
		setSummaryLoading(cardId);
		setSummaryOpen(true);
		try {
			const res = await explainMapNode(cardId, cardKind ?? 'file');
			setSummary(cardId, res.summary || '（无摘要）');
		} catch (err) {
			setSummary(
				cardId,
				err instanceof Error ? err.message : '摘要请求失败',
			);
		}
	};

	useEffect(() => {
		setSummaryOpen(false);
	}, [cardId]);

	const bumpFocus = (id: string | null | undefined) => {
		if (!id) {
			return;
		}
		if (!skipHistRef.current && cardId && cardId !== id) {
			const hist = focusHistRef.current;
			if (hist[hist.length - 1] !== cardId) {
				hist.push(cardId);
				if (hist.length > 24) {
					hist.shift();
				}
				setFocusHistLen(hist.length);
			}
		}
		skipHistRef.current = false;
		setFocusRequest(`${id}#${Date.now()}`);
	};

	const goBackFocus = () => {
		const prev = focusHistRef.current.pop();
		setFocusHistLen(focusHistRef.current.length);
		if (!prev) {
			return;
		}
		const node = laid.nodes.find(n => n.id === prev);
		if (!node) {
			return;
		}
		skipHistRef.current = true;
		setCard(node.id, node.kind);
		bumpFocus(node.id);
	};

	const focusReplayFrame = useCallback(
		(relPath: string) => {
			const fileNode = laid.nodes.find(
				n => n.kind === 'file' && pathsLooselyEqual(n.id, relPath),
			);
			if (fileNode) {
				setCard(fileNode.id, 'file');
				bumpFocus(fileNode.id);
				return;
			}
			const pkgNode = laid.nodes.find(
				n =>
					n.kind === 'package' &&
					(relPath === n.id || relPath.startsWith(`${n.id}/`)),
			);
			if (pkgNode) {
				setCard(pkgNode.id, 'package');
				bumpFocus(pkgNode.id);
				return;
			}
			setCard(relPath, 'file');
			bumpFocus(relPath);
		},
		[laid.nodes, setCard],
	);

	useEffect(() => {
		if (replayIdx == null) {
			return;
		}
		if (replayScript.length < 1) {
			setReplayPlaying(false);
			setReplayIdx(null);
			return;
		}
		if (replayIdx >= replayScript.length) {
			setReplayIdx(replayScript.length - 1);
			return;
		}
		const frame = replayScript[replayIdx];
		if (!frame) {
			return;
		}
		focusReplayFrame(frame.relPath);
	}, [replayIdx, replayScript, focusReplayFrame]);

	useEffect(() => {
		if (!replayPlaying || replayIdx == null) {
			return;
		}
		if (replayIdx >= replayScript.length - 1) {
			setReplayPlaying(false);
			return;
		}
		const timer = window.setTimeout(() => {
			setReplayIdx(i => (i == null ? i : Math.min(i + 1, replayScript.length - 1)));
		}, 720);
		return () => window.clearTimeout(timer);
	}, [replayPlaying, replayIdx, replayScript.length]);

	const startReplay = () => {
		if (replayScript.length < 1) {
			return;
		}
		if (view === 'architecture' || view === 'authored') {
			setView('code');
		}
		// 本轮自带文件泳道，可直接回放，不必强制切代码视图。
		setReplayIdx(0);
		setReplayPlaying(true);
	};

	const stopReplay = () => {
		setReplayPlaying(false);
		setReplayIdx(null);
	};

	const replayTrail = useMemo(() => {
		if (replayIdx == null) {
			return null;
		}
		const prefix = replayScript.slice(0, replayIdx + 1).map(f => ({
			relPath: f.relPath,
			verb: f.verb,
			running: false,
			toolName: f.toolName,
			createdAt: f.createdAt,
		}));
		return buildOpsTrail(prefix, 12);
	}, [replayIdx, replayScript]);

	const emptyHint =
		view === 'authored' && !authored
			? '对话里输出 ```xeyo-map 图稿后会出现在这里'
			: view === 'turn' && turnSteps.length === 0
				? '当前轮还没有工具步骤'
				: '没有可展示的节点';

	return (
		<div className="xy-agent-map-panel flex h-full min-h-0 flex-col">
			<div className="flex shrink-0 items-center gap-1.5 border-b border-line/40 px-2 py-1.5">
				<div className="xy-agent-map-panel__tabs">
					{VIEW_TABS.map(tab => (
						<button
							key={tab.id}
							type="button"
							className={cn(
								'xy-agent-map-panel__tab',
								view === tab.id && 'xy-agent-map-panel__tab--on',
							)}
							onClick={() => {
								setView(tab.id);
								if (tab.id !== 'code') {
									setSymbols([]);
									setSymbolsFor(null);
								}
							}}
						>
							{tab.label}
						</button>
					))}
				</div>
				<button
					type="button"
					className="xy-icon-btn ml-auto rounded-full p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-35"
					aria-label="返回上一个节点"
					title="返回上一个"
					disabled={focusHistLen < 1}
					onClick={goBackFocus}
				>
					<Undo2 className="h-3.5 w-3.5" />
				</button>
				<button
					type="button"
					className="xy-icon-btn rounded-full p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
					aria-label="重新扫描地图"
					title="重新扫描"
					onClick={() => void reload()}
				>
					<RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
				</button>
			</div>
			<div ref={hostRef} className="relative min-h-0 flex-1">
				{error ? (
					<p className="px-3 py-6 text-center text-[12px] text-mute">{error}</p>
				) : loading && !graph && view !== 'turn' && view !== 'authored' ? (
					<p className="px-3 py-6 text-center text-[12px] text-mute">
						scanning workspace…
					</p>
				) : symbolsLoading ? (
					<p className="px-3 py-6 text-center text-[12px] text-mute">
						loading outline…
					</p>
				) : laid.nodes.length === 0 ? (
					<p className="px-3 py-6 text-center text-[12px] text-mute">
						{emptyHint}
					</p>
				) : (
					<AgentMapCanvas
						nodes={laid.nodes}
						edges={view === 'turn' ? [] : laid.edges}
						lanes={laid.lanes}
						width={laid.width}
						height={laid.height}
						selectedId={selectedId}
						followId={replayFrame ? null : followId}
						focusRequestId={focusRequest}
						onSelect={onSelect}
						hitByNodeId={hitByNodeId}
						searchHitIds={searchHitIds}
						replayPath={replayFrame?.relPath ?? null}
						replayVerb={replayFrame?.verb ?? null}
						opsTrail={
							view === 'architecture' || view === 'authored'
								? undefined
								: view === 'turn'
									? (replayTrail ?? turnTrail ?? undefined)
									: (replayTrail ?? opsTrail)
						}
						trailAnimate={replayPlaying}
						stepRunningIds={view === 'turn' ? stepRunningIds : undefined}
						stepSeenIds={view === 'turn' ? stepSeenIds : undefined}
						stepVerbs={view === 'turn' ? stepVerbs : undefined}
					/>
				)}
				{replayScript.length > 0 || cardId ? (
					<div className="xy-agent-map-panel__dock">
						{cardId ? (
							<>
								{summaryOpen &&
								(summaryLoading === cardId || summaries[cardId]) ? (
									<div className="xy-agent-map-panel__summary" role="status">
										{summaryLoading === cardId && !summaries[cardId]
											? '生成摘要…'
											: (summaries[cardId] ?? '')}
									</div>
								) : null}
								<div className="xy-agent-map-panel__card">
									<span className="xy-agent-map-panel__path truncate">
										{cardId.split('/').pop() ?? cardId}
									</span>
									{cardHit ? (
										<span className="shrink-0 text-[9px] text-mute">
											{cardHit.verb}
										</span>
									) : null}
									{cardKind === 'file' ||
									cardKind === 'step' ||
									cardKind === 'symbol' ||
									(cardKind === 'authored' &&
										authored?.nodes.find(n => n.id === cardId)?.file) ? (
										<button
											type="button"
											className="xy-agent-map-panel__btn"
											onClick={openFileFromCard}
											title="有改动开 diff，否则开文件"
										>
											<ExternalLink className="h-3 w-3" />
										</button>
									) : null}
									{cardKind === 'file' || cardKind === 'package' ? (
										<button
											type="button"
											className="xy-agent-map-panel__btn"
											disabled={summaryLoading === cardId}
											onClick={() => void onExplain()}
											title={
												summaries[cardId] ? '显示/隐藏摘要' : '生成摘要'
											}
											aria-pressed={summaryOpen}
										>
											<Sparkles className="h-3 w-3" />
										</button>
									) : null}
									<button
										type="button"
										className="xy-icon-btn shrink-0 rounded-full p-0.5 text-mute hover:bg-glass-hover hover:text-ink"
										aria-label="关闭卡片"
										onClick={() => setCard(null)}
									>
										<X className="h-3 w-3" />
									</button>
								</div>
							</>
						) : null}
						{replayScript.length > 0 ? (
							<div className="xy-agent-map-panel__float" aria-label="操作回放">
								{replayFrame ? (
									<button
										type="button"
										className="xy-agent-map-panel__float-cap"
										title={`打开 ${replayFrame.relPath}`}
										onClick={() => openRelFile(replayFrame.relPath)}
									>
										{replayIdx! + 1}/{replayScript.length} · {replayFrame.verb}{' '}
										{replayFrame.relPath.split('/').pop()}
									</button>
								) : headline ? (
									<button
										type="button"
										className="xy-agent-map-panel__float-cap"
										title={`打开 ${headline.relPath}`}
										onClick={() => openRelFile(headline.relPath)}
									>
										{headline.running ? 'RUN' : 'DONE'} {headline.verb} ·{' '}
										{headline.relPath.split('/').pop()}
									</button>
								) : null}
								<button
									type="button"
									className="xy-agent-map-panel__replay-btn"
									aria-label={replayPlaying ? '暂停回放' : '播放回放'}
									title={replayPlaying ? '暂停' : '回放'}
									onClick={() => {
										if (replayPlaying) {
											setReplayPlaying(false);
											return;
										}
										if (replayIdx == null) {
											startReplay();
											return;
										}
										setReplayPlaying(true);
									}}
								>
									{replayPlaying ? (
										<Pause className="h-3 w-3" />
									) : (
										<Play className="h-3 w-3" />
									)}
								</button>
								<button
									type="button"
									className="xy-agent-map-panel__replay-btn"
									aria-label="上一步"
									disabled={replayIdx == null || replayIdx <= 0}
									onClick={() => {
										setReplayPlaying(false);
										setReplayIdx(i => (i == null ? 0 : Math.max(0, i - 1)));
									}}
								>
									<ChevronLeft className="h-3 w-3" />
								</button>
								<button
									type="button"
									className="xy-agent-map-panel__replay-btn"
									aria-label="下一步"
									disabled={
										replayScript.length < 1 ||
										(replayIdx != null &&
											replayIdx >= replayScript.length - 1)
									}
									onClick={() => {
										setReplayPlaying(false);
										if (replayIdx == null) {
											if (view === 'architecture' || view === 'authored') {
												setView('code');
											}
											setReplayIdx(0);
											return;
										}
										setReplayIdx(i =>
											i == null
												? 0
												: Math.min(i + 1, replayScript.length - 1),
										);
									}}
								>
									<ChevronRight className="h-3 w-3" />
								</button>
								{replayIdx != null ? (
									<button
										type="button"
										className="xy-agent-map-panel__replay-btn"
										aria-label="停止回放"
										onClick={stopReplay}
									>
										<Square className="h-3 w-3" />
									</button>
								) : null}
							</div>
						) : null}
					</div>
				) : null}
			</div>
		</div>
	);
}
