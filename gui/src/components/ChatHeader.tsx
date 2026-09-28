import {PanelLeft, Plus, Search} from 'lucide-react';
import {memo} from 'react';
import {useLocation} from 'react-router-dom';
import {useChatUiStore} from '@/stores/chatUiStore';
import {useChatStore} from '@/stores/chatStore';
import {newSession, openPageView, pageViewFromPath} from '@/lib/appNav';
import {cn} from '@/lib/utils';
import {formatUsageChipPreview} from '@/lib/formatUsage';
import {SessionJobsBadge} from '@/components/SessionJobsBadge';
import {getCachedModelContextLimit} from '@/lib/api';
import {useSettingsStore} from '@/stores/settingsStore';
import {
	registeredWindowFromSettings,
	resolveWindowLimit,
	windowUsagePercent,
} from '@/lib/modelWindow';
import {useShallow} from 'zustand/react/shallow';

/**
 * 「模型窗口」的活口径（@/lib/modelWindow）：**设置里登记的窗口优先**，厂商
 * /models 缓存兜底；两者都没有才回退会话快照里厂商回传的实测窗口。
 * 直接订阅 settingsStore（profiles / 激活账号 / 激活模型都是它派生投影），所以
 * 保存账号、切账号、换模型都会**立即**改分母，不再等下一次请求的 usage 事件。
 * 返回原始数值 → 引用稳定，不会造成额外重渲染。
 */
const selectDeclaredWindow = (
	s: ReturnType<typeof useSettingsStore.getState>,
): number | null =>
	resolveWindowLimit({
		registered: registeredWindowFromSettings(s),
		vendorCached: getCachedModelContextLimit(
			s.provider,
			s.resolvedBaseUrl(),
			s.model,
		),
	}) ?? null;


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
	// 扩展中心 / 诊断中心与用量同为页面级视图:打开时标题切换、用量预览让位(2026-09-05)。
	const pluginsOpen = pageView === 'plugins';
	const diagnosticsOpen = pageView === 'diagnostics';
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
			: diagnosticsOpen
				? '诊断中心'
				: shortAgent
					? `${sessionTitle} / ${shortAgent}`
					: sessionTitle;
	const workspace = spaces.find(s => s.id === activeSpaceId);
	const workspaceLabel = mode === 'main' && !pageViewOpen && workspace?.rootPath
		? workspace.name
		: null;
		// 持久化的整个会话累计 usage；Token 以厂商响应为准。
	const usage = pageViewOpen ? null : sessionUsageById[activeId ?? ''] ?? null;
	const totalTokens = usage && Number.isFinite(usage.tokens)
		? Math.max(0, usage.tokens)
		: 0;
	const totalOut =
		usage && Number.isFinite(usage.completionTokens)
			? Math.max(0, usage.completionTokens)
			: null;
	const declaredWindow = useSettingsStore(selectDeclaredWindow);
	const measuredWindow =
		usage && Number.isFinite(usage.contextLimit) && usage.contextLimit! > 0
			? usage.contextLimit!
			: null;
	const contextLimit = declaredWindow ?? measuredWindow;
	const contextTokens =
		usage && Number.isFinite(usage.contextTokens) && usage.contextTokens! >= 0
			? usage.contextTokens!
			: null;
	const contextPercent =
		windowUsagePercent({contextTokens, limit: contextLimit}) ??
		(contextLimit == null && usage && Number.isFinite(usage.contextPercent)
			? Math.max(0, Math.min(100, usage.contextPercent!))
			: null);
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
									'xy-hdr-title flex min-w-0 items-center overflow-hidden whitespace-nowrap px-1 text-[13px] text-ink-soft',
									sidebarOpen && !pageViewOpen
										? 'pointer-events-none max-w-0 shrink-0 -translate-x-1.5 opacity-0'
										: 'max-w-[28ch] translate-x-0 opacity-100',
								)}

							>
								{/* 主文本（会话标题）与次文本（工作区名）分开截断：
								    次文本自己封顶 10ch，长路径不再吃掉标题；两截都可从 title 复原。 */}
								<span className="min-w-0 flex-1 truncate" title={title}>
									{title}
								</span>
								{workspaceLabel ? (
									<span className="max-w-[10ch] min-w-0 shrink truncate text-mute" title={workspaceLabel}> · {workspaceLabel}</span>
								) : null}
							</span>
				{!pageViewOpen && activeId != null ? (
					<button
						type="button"
						aria-label="打开 A3 用量报告"
						title="打开 A3 日常监控报告"
						onClick={() => openPageView('usage')}
						className="xy-usage-chip inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 font-mono text-[11px] text-mute transition-colors hover:bg-glass-hover hover:text-ink"
					>
						{usage
							? formatUsageChipPreview(
								totalTokens,
								totalOut,
								contextPercent != null ? contextPercent.toFixed(1) : null,
							)
							: 'A3 用量'}
					</button>
				) : null}
				</div>
				{!pageViewOpen && mode === 'main' ? (
					<SessionJobsBadge sessionId={backendSessionId} mode={mode} />
				) : null}
			</header>
		</>
	);
});
