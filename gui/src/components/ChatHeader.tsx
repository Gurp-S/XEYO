import {ChevronDown, PanelLeft, Plus, Search, X} from 'lucide-react';
import {memo, useEffect, useRef, useState} from 'react';
import {useLocation} from 'react-router-dom';
import {useChatUiStore} from '@/stores/chatUiStore';
import {useChatStore} from '@/stores/chatStore';
import {newSession, pageViewFromPath} from '@/lib/appNav';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {cn} from '@/lib/utils';
import {
	formatCacheHitPercent,
	formatTokenCount,
	formatUsageChipPreview,
} from '@/lib/formatUsage';
import {SessionJobsBadge} from '@/components/SessionJobsBadge';
import {
	fetchMemoryNotes,
	fetchSessionCompression,
	requestManualCompact,
	type MemoryNoteRow,
	type SessionCompression,
} from '@/lib/api';
import {useShallow} from 'zustand/react/shallow';
import {computeUsageSegments, segmentWidths} from '@/lib/usageSegments';

export const ChatHeader = memo(function ChatHeader({
	mode = 'main',
}: {
	mode?: 'main' | 'side';
}) {
		const {
			activeId,
		activeSpaceId,
		sessions,
		spaces,
		sessionUsageById,
		} = useChatUiStore(

			useShallow(s => ({
			activeId: s.activeId,
			activeSpaceId: s.activeSpaceId,
			sessions: s.sessions,
			spaces: s.spaces,
			sessionUsageById: s.sessionUsageById,
		})),
	);
		const sidebarOpen = useChatStore(s => s.sidebarOpen);
		const setSidebarOpen = useChatStore(s => s.setSidebarOpen);
		const requestSearchFocus = useChatStore(s => s.requestSearchFocus);
	// 页面视图（用量/扩展中心）→ 路由派生（/usage、/plugins），无独立状态。
	const location = useLocation();
	const pageView = pageViewFromPath(location.pathname);
	const usageOpen = pageView === 'usage';
	// 扩展中心与用量同为页面级视图:打开时标题切换、用量预览让位(2026-09-05)。
	const pluginsOpen = pageView === 'plugins';
	const pageViewOpen = pageView !== null;
	const historyById = useChatStore(s => s.historyById);
	const backendSessionId = activeId
		? historyById[activeId]?.activeBranch?.backendSessionId ?? activeId
		: null;
	// 多 Agent 子视图（Q4）：标题变为「原对话标题 / 子agent标题」，仅子视图生效。
	const agentTitle = useChatStore(s => {
		const cur = s.agentViewStack[s.agentViewIndex];
		if (!cur || cur === 'main' || !s.activeId) {
			return null;
		}
		return (
			s.multiAgentTasksBySession[s.activeId]?.find(t => t.agentId === cur)?.desc ??
			null
		);
	});
	const sessionTitle =
		sessions.find(s => s.id === activeId)?.title?.trim() || '新对话';
	const shortAgent = agentTitle
		? agentTitle.length > 16
			? `${agentTitle.slice(0, 16)}…`
			: agentTitle
		: null;
	const title = usageOpen
		? '用量'
		: pluginsOpen
			? '扩展中心'
			: shortAgent
				? `${sessionTitle} / ${shortAgent}`
				: sessionTitle;
	const workspace = spaces.find(s => s.id === activeSpaceId);
	const workspaceLabel = mode === 'main' && !pageViewOpen && workspace?.rootPath
		? workspace.name
		: null;
		// 持久化的整个会话累计 usage；Token 以厂商响应为准。
const usage = pageViewOpen ? null : sessionUsageById[activeId ?? ''] ?? null;
			const usagePreviewVisible = !pageViewOpen && activeId != null;
			const [usagePreviewOpen, setUsagePreviewOpen] = useState(false);
		const [compression, setCompression] = useState<SessionCompression | null>(null);
		const [, setMemoryNotes] = useState<MemoryNoteRow[]>([]);
		const [compactBusy, setCompactBusy] = useState(false);
		const usagePreviewRef = useRef<HTMLDivElement>(null);
		const usagePreviewId = 'chat-usage-preview';
		// 悬停分段条显示明细（与预览一致：label + Tokens + 占窗口），并高亮当前区域。
		const [segTip, setSegTip] = useState<{key: string; label: string; tokens: number; chars?: number; share: number; color: string; x: number; y: number} | null>(null);
		const hoverSegKey = segTip?.key ?? null;
		const contextLimit = usage && Number.isFinite(usage.contextLimit) && usage.contextLimit! > 0
			? usage.contextLimit!
			: null;
		const contextTokens = usage && Number.isFinite(usage.contextTokens) && usage.contextTokens! >= 0
			? usage.contextTokens!
			: null;
		const contextPercent = usage && Number.isFinite(usage.contextPercent)
			? Math.max(0, Math.min(100, usage.contextPercent!))
			: contextLimit && contextTokens != null
				? Math.max(0, Math.min(100, (contextTokens / contextLimit) * 100))
				: null;
		// 「消耗」必须是单调的会话累计值；contextTokens（最近一枪的输入大小）会在
		// 收尾请求（去 tools）或 C2 压缩后缩小，显示它会把真实消耗画出"倒退"。
		const totalTokens = usage && Number.isFinite(usage.tokens)
			? Math.max(0, usage.tokens)
			: 0;
		// 最近一枪的单轮拆分（非累计）：上下文构成回退条只能用它，
		// 累计的 cacheHit/cacheMiss 会随会话增长超过窗口，不能当"本轮构成"。
		const lastHit = usage?.lastCacheHitTokens != null && Number.isFinite(usage.lastCacheHitTokens)
			? Math.max(0, usage.lastCacheHitTokens!)
			: null;
		const lastMiss = usage?.lastCacheMissTokens != null && Number.isFinite(usage.lastCacheMissTokens)
			? Math.max(0, usage.lastCacheMissTokens!)
			: null;
		// 会话累计输出（权威，单调）；lastCompletionTokens 只是最近一枪，不用。
		const totalOut = usage && Number.isFinite(usage.completionTokens)
			? Math.max(0, usage.completionTokens)
			: null;
		const cacheHitRateText = usage
			? formatCacheHitPercent(usage.cacheHitTokens, usage.cacheMissTokens)
			: null;
		const measuredContext = contextLimit != null && contextTokens != null;
		// 细粒度的「上下文构成」分段条（后端下发的按内容分类 token 数）。
		// 计算抽到 @/lib/usageSegments（纯函数、可单测）：权威段 sum === context_tokens，
		// 回退段只含输入命中/未命中（输出不属于窗口占用，2026-09-09 修正）。
		const {segments, denominator: segDenom} = computeUsageSegments({
			contextBreakdown: usage?.contextBreakdown,
			contextLimit,
			contextTokens,
			lastCacheHitTokens: lastHit,
			lastCacheMissTokens: lastMiss,
		});
		// 渲染宽度（%），带命中最窄 0.5% 的钳制（与 UI 一致），供按坐标命中测试。
		const segWidths = segmentWidths(segments, segDenom);
		const segRanges: {seg: (typeof segments)[number]; start: number; end: number}[] = [];
		{
			let cursor = 0;
			segments.forEach((seg, i) => {
				const start = cursor;
				const end = cursor + segWidths[i];
				segRanges.push({seg, start, end});
				cursor = end;
			});
		}
		const barRef = useRef<HTMLDivElement>(null);
		type SegMouseEvent = {clientX: number; clientY: number};
		// 在整根条上按鼠标 X 坐标命中分段：切换分段时才更新内容/高亮，
		// 不会因为过窄分段反复 enter/leave 而产生闪烁。
		const segAtX = (clientX: number): (typeof segments)[number] | null => {
			const el = barRef.current;
			if (!el) return null;
			const rect = el.getBoundingClientRect();
			if (rect.width <= 0) return null;
			const xPct = ((clientX - rect.left) / rect.width) * 100;
			for (const r of segRanges) {
				if (xPct >= r.start && xPct < r.end) return r.seg;
			}
			return null;
		};
		const onBarMove = (e: SegMouseEvent) => {
			const seg = segAtX(e.clientX);
			if (!seg) { setSegTip(null); return; }
			setSegTip(prev => {
				if (prev && prev.key === seg.key) return {...prev, x: e.clientX, y: e.clientY};
				return {
					key: seg.key,
					label: seg.label,
					tokens: seg.tokens,
					chars: 'chars' in seg ? Number((seg as {chars?: number}).chars) || 0 : 0,
					share: Math.min(100, Math.round((seg.value / segDenom) * 100)),
					color: seg.color,
					x: e.clientX,
					y: e.clientY,
				};
			});
		};
		const onBarLeave = () => setSegTip(null);

		useEffect(() => {
			if (!usagePreviewOpen) {
				return;
			}
			const onDocumentMouseDown = (event: MouseEvent) => {
				if (!usagePreviewRef.current?.contains(event.target as Node)) {
					setUsagePreviewOpen(false);
				}
			};
			pushEscLayer('usage-popover', () => setUsagePreviewOpen(false));
			document.addEventListener('mousedown', onDocumentMouseDown);
			return () => {
				document.removeEventListener('mousedown', onDocumentMouseDown);
				popEscLayer('usage-popover');
			};
		}, [usagePreviewOpen]);

		useEffect(() => {
			setUsagePreviewOpen(false);
			setCompression(null);
			setMemoryNotes([]);
		}, [activeId, mode, usageOpen]);

		useEffect(() => {
			if (!usagePreviewOpen || !backendSessionId) {
				return;
			}
			let cancelled = false;
			void fetchSessionCompression(backendSessionId).then(data => {
				if (!cancelled) {
					setCompression(data);
				}
			});
			void fetchMemoryNotes('', 12).then(rows => {
				if (!cancelled) {
					setMemoryNotes(rows);
				}
			});
			return () => {
				cancelled = true;
			};
		}, [usagePreviewOpen, backendSessionId]);

		const onManualCompact = async () => {
			if (!backendSessionId || compactBusy) return;
			setCompactBusy(true);
			try {
				const res = await requestManualCompact(backendSessionId);
				const data = await fetchSessionCompression(backendSessionId);
				setCompression(data);
				if (!res.ok) {
					console.warn('manual compact', res.reason);
				}
			} finally {
				setCompactBusy(false);
			}
		};

		const onNew = () => {
		// 统一入口：新建会话 + 路由（页面视图若开着随路由自动退出）。
		void newSession(mode === 'main' ? undefined : {side: true});
	};

	return (
		<>
			<header className="relative flex h-7 shrink-0 items-center justify-between gap-2 bg-transparent px-2">
				<div className="flex min-w-0 items-center gap-0.5">
					<div
						className={cn(
							'xy-header-tools',
							sidebarOpen && 'is-collapsed',
						)}
						aria-hidden={sidebarOpen}
					>
						<div className="xy-header-tools-inner">
							<button
								type="button"
								aria-label="展开侧栏"
								tabIndex={sidebarOpen ? -1 : 0}
								onClick={() => setSidebarOpen(true)}
className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
									
							>
								<PanelLeft className="h-4 w-4" />
							</button>
							<button
								type="button"
								aria-label="搜索"
								tabIndex={sidebarOpen ? -1 : 0}
								onClick={() => requestSearchFocus()}
className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
									
							>
								<Search className="h-4 w-4" />
							</button>
							{/* 页面视图(用量/扩展中心)不显示「新对话」:会话操作与该视图无关 */}
							{!pageViewOpen ? (
							<button
								type="button"
								aria-label="新对话"
								tabIndex={sidebarOpen ? -1 : 0}
								onClick={() => void onNew()}
className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"

							>
								<Plus className="h-4 w-4" />
							</button>
							) : null}
							<span className="mx-1 h-3 w-px shrink-0 bg-line/80" />
						</div>
					</div>
						<span
							aria-hidden={sidebarOpen && !pageViewOpen}
							className={cn(
									'xy-hdr-title overflow-hidden whitespace-nowrap px-1 text-[13px] text-ink-soft',
									sidebarOpen && !pageViewOpen
										? 'pointer-events-none max-w-0 shrink-0 -translate-x-1.5 opacity-0'
										: 'min-w-0 max-w-[28ch] translate-x-0 truncate opacity-100',
								)}

							>
								{title}
								{workspaceLabel ? (
									<span className="text-mute"> · {workspaceLabel}</span>
								) : null}
							</span>
{usagePreviewVisible ? (
						<div
							key={sidebarOpen ? 'side-open' : 'side-closed'}
						data-xy-usage-anchor
							ref={usagePreviewRef}
						className="group relative shrink-0 whitespace-nowrap font-mono text-[10px] text-mute"
					>
					<button
							type="button"
							aria-label="展开用量详情"
							aria-expanded={usagePreviewOpen}
							aria-controls={usagePreviewId}
							title="本对话累计消耗（厂商 usage 逐次累计）与费用"
							onClick={() => setUsagePreviewOpen(open => !open)}
							className={cn(
								'xy-usage-chip inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 transition-colors hover:bg-glass-hover hover:text-ink',
								usagePreviewOpen && 'bg-glass-hover text-ink',
							)}
						>
							{usage
								? formatUsageChipPreview(
										totalTokens,
										totalOut,
										// 与弹窗「模型窗口占用」同口径：context_tokens / context_limit。
										// 曾误用累计输出 token 当分子——输出增长慢，百分比长期趴在低位。
										contextPercent != null ? contextPercent.toFixed(1) : null,
									)
								: '用量 · 暂无数据'}
												<ChevronDown className={cn('h-3 w-3 transition-transform', usagePreviewOpen && 'rotate-180')} strokeWidth={1.8} />
						</button>
						{usagePreviewOpen ? (
								<div
									id={usagePreviewId}
									role="dialog"
									aria-label="本对话用量详情"
									className="xy-menu-flyout xy-usage-card anim-pop absolute left-0 right-auto top-full z-50 mt-2 w-[min(340px,calc(100vw-1rem))] origin-top-left whitespace-normal rounded-xl border border-line/50 p-3 text-left text-[11px] leading-4 text-ink-soft"
								>
									<div className="flex items-center justify-between gap-2">
										<h3 className="font-semibold text-ink">本对话用量</h3>
										<button
											type="button"
											aria-label="关闭用量详情"
											onClick={() => setUsagePreviewOpen(false)}
											className="xy-icon-btn -mr-1 rounded-md p-1 text-mute hover:bg-glass-hover hover:text-ink"
										>
											<X className="h-3.5 w-3.5" strokeWidth={1.8} />
										</button>
									</div>
									<div className="mt-2 grid grid-cols-2 gap-2">
										<div className="min-w-0 rounded-lg border border-line/70 bg-glass-hover px-2.5 py-2">
											<div className="text-mute">消耗 Token（累计）</div>
											<div className="mt-0.5 font-mono text-[18px] font-semibold leading-tight text-ink">
												{usage
													? formatTokenCount(totalTokens)
													: '暂无数据'}
											</div>
										</div>
										<div className="min-w-0 rounded-lg border border-line/70 bg-glass-hover px-2.5 py-2">
											<div className="text-mute">模型窗口</div>
											<div className="mt-0.5 font-mono text-[18px] font-semibold leading-tight text-ink">
												{contextLimit != null
													? formatTokenCount(contextLimit)
													: '暂无数据'}
											</div>
											<div className="mt-0.5 text-right font-mono text-[11px] leading-tight text-mute">
												{contextLimit != null && contextTokens != null
													? `${Math.min(100, Math.round((contextTokens / contextLimit) * 100))}%` : '—'} 占用
											</div>
										</div>
										<div className="min-w-0 rounded-lg border border-line/70 bg-glass-hover px-2.5 py-2">
											<div className="text-mute">缓存命中（累计）</div>
											<div className="mt-0.5 font-mono text-[18px] font-semibold leading-tight text-ink">{cacheHitRateText == null ? '暂无数据' : `${cacheHitRateText}%`}</div>
										</div>
										<div className="min-w-0 rounded-lg border border-line/70 bg-glass-hover px-2.5 py-2">
											<div className="text-mute">本轮输出</div>
											<div className="mt-0.5 font-mono text-[18px] font-semibold leading-tight text-ink">{totalOut != null ? formatTokenCount(totalOut) : '暂无数据'}</div>
										</div>
									</div>
									{(() => {
										const cursor =
											compression?.compact_cursor ?? usage?.compactCursor ?? 0;
										const active =
											compression?.active ??
											(cursor > 0 && (usage?.c2SummaryChars ?? 0) > 0);
										const chars =
											compression?.c2_summary_chars ?? usage?.c2SummaryChars ?? 0;
										const action =
											compression?.last_action || usage?.lastAction || '';
										return (
											<div className="mt-2 rounded-lg border border-line/70 bg-glass-hover px-2.5 py-2">
												<div className="flex items-center justify-between gap-2">
													<div className="font-semibold text-ink">C2 压缩</div>
													<span
														className={cn(
															'rounded-full px-1.5 py-0.5 font-mono text-[10px]',
															active
																? 'bg-ink/10 text-ink'
																: 'bg-glass text-mute',
														)}
													>
														{active ? '已压缩' : '未触发'}
													</span>
												</div>
												<div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
													<div className="text-mute">游标</div>
													<div className="font-mono text-ink text-right">
														{cursor > 0 ? cursor : '—'}
													</div>
													<div className="text-mute">摘要</div>
													<div className="font-mono text-ink text-right">
														{chars > 0 ? `${chars} 字` : '—'}
													</div>
													<div className="text-mute">上一动作</div>
													<div className="font-mono text-ink text-right">
														{action || '—'}
													</div>
												</div>
												<div className="mt-2 flex items-center justify-between gap-2">
													{compression?.c2_gate ? (
														<button
															type="button"
															disabled={compactBusy || !backendSessionId}
															onClick={() => void onManualCompact()}
															className="rounded-md border border-line/80 bg-glass px-2 py-1 text-[10px] font-medium text-ink hover:bg-glass-hover disabled:opacity-50"
														>
															{compactBusy ? '压缩中…' : '立即压缩 /compact'}
														</button>
													) : null}
													<span className="text-[10px] text-mute">不改历史 JSONL</span>
												</div>
												{compression?.c2_summary_preview ? (
													<p className="mt-2 mb-0 max-h-24 overflow-y-auto whitespace-pre-wrap break-words text-[10px] leading-4 text-ink-soft">
														{compression.c2_summary_preview}
													</p>
												) : (
													<p className="mt-2 mb-0 text-[10px] text-mute">
														{active
															? '本会话已进入 C2 压缩态；继续对话可保持前缀缓存。'
															: ''}
													</p>
												)}
																							</div>
										);
									})()}
									<div className="mt-2.5 flex items-baseline justify-between">
										<span className="text-[10px] text-mute">最近一枪上下文构成</span>
										<span className="text-[10px] text-mute">{measuredContext ? '占模型窗口' : '占本轮已用量'}</span>
									</div>
									<div
										ref={barRef}
										onMouseMove={onBarMove}
										onMouseLeave={onBarLeave}
										className="mt-1 flex h-[10px] w-full overflow-hidden rounded-full bg-glass-hover"
										aria-label="最近一枪上下文构成"
									>
										{segments.map((segment, i) => {
											const active = hoverSegKey === segment.key;
											return (
												<span
													key={segment.key}
													className="h-full shrink-0 transition-opacity duration-100"
													style={{width: `${segWidths[i]}%`, background: segment.color, opacity: !hoverSegKey || active ? 1 : 0.35}}
												/>
											);
										})}
									</div>
									{usage ? (
										<p className="mt-2 mb-0 leading-relaxed text-ink-soft">
											{measuredContext
											? '预览为「最近一枪输入的上下文构成 / 模型窗口」；消耗与费用见「消耗 Token（累计）」与侧栏用量页。'
											: '模型窗口未知，比例按「最近一枪各部分 / 本轮已用量」计；消耗与费用见侧栏用量页。'}
										</p>
									) : (
										<p className="mt-2 mb-0 text-ink-soft">当前会话暂无 usage 数据，发送消息后将显示详细用量。</p>
									)}
								</div>
						) : null}
						{usagePreviewOpen && segTip ? (
							<div
								data-xy-seg-tip
								className="pointer-events-none fixed z-[70] whitespace-nowrap rounded-xl border border-frame bg-glass-strong px-3 py-2 text-[11px] leading-5 text-mute shadow-[var(--xy-modal-shadow)]"
								style={{
									left: Math.min(segTip.x + 14, window.innerWidth - 150),
									top: Math.min(segTip.y + 16, window.innerHeight - 90),
								}}
							>
								<div className="flex items-center gap-1.5">
									<span className="h-2.5 w-2.5 rounded-sm" style={{background: segTip.color === 'transparent' ? 'var(--line)' : segTip.color}} />
									<span className="font-semibold text-ink">{segTip.label}</span>
								</div>
								<div className="mt-0.5 flex items-baseline justify-between gap-5">
									<span className="text-mute">Tokens</span>
									<span className="font-mono text-[12px] text-ink">{formatTokenCount(segTip.tokens)}</span>
								</div>
								{segTip.chars != null && segTip.chars > 0 ? (
									<div className="flex items-baseline justify-between gap-5">
										<span className="text-mute">字符</span>
										<span className="font-mono text-[12px] text-ink">{segTip.chars}</span>
									</div>
								) : null}
									<div className="flex items-baseline justify-between gap-5">
										<span className="text-mute">{measuredContext ? '占窗口' : '占已用'}</span>
										<span className="font-mono text-[12px] text-ink">{segTip.share}%</span>
									</div>
							</div>
						) : null}
					</div>
				) : null}
				</div>
				{!pageViewOpen && mode === 'main' ? (
					<SessionJobsBadge sessionId={backendSessionId} mode={mode} />
				) : null}
			</header>
		</>
	);
});
