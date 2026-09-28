import {useEffect, useLayoutEffect, useRef} from 'react';
import {AppShell} from '@/components/AppShell';
import {ChatHeader} from '@/components/ChatHeader';


import {Composer} from '@/components/Composer';
import {WorkspacePanel} from '@/components/WorkspacePanel';
import {WorkspaceToolPanel} from '@/components/WorkspaceToolPanel';
import {FilePreview} from '@/components/FilePreview';
import {MessageList} from '@/components/MessageList';
import {SubAgentView} from '@/components/SubAgentView';
import {RemotePoller} from '@/components/RemotePoller';
import {RemoteSseClient} from '@/components/RemoteSseClient';
import {RemoteQrPanel} from '@/components/RemoteQrPanel';
import {Sidebar} from '@/components/Sidebar';
import {useChatStore} from '@/stores/chatStore';
import {ChatUiStoreProvider} from '@/stores/chatUiStore';
import {useRemoteStore} from '@/stores/remoteStore';
import {useSettingsStore, isSmoothnessOn} from '@/stores/settingsStore';
import {DEFAULT_SPACE_ID, SIDE_SPACE_ID} from '@/lib/db';
import {useLocation, useNavigate, useParams} from 'react-router-dom';
import {ImmersiveLayer} from '@/components/immersive/ImmersiveLayer';
import {UsagePanel} from '@/components/UsagePanel';
import {PluginsPanel} from '@/components/PluginsPanel';
import {DiagnosticsPanel} from '@/features/diagnostics/DiagnosticsPanel';
import {PageViewPane} from '@/components/PageViewPane';
import {usePresence} from '@/hooks/usePresence';
import {closePageView, isSideChatPath, pageViewFromPath} from '@/lib/appNav';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';

function RecoveryBanner() {
	const activeId = useChatStore(s => s.activeId);
	const activeSessionArchived = useChatStore(s =>
		Boolean(activeId && s.sessions.some(session => session.id === activeId && session.archived)),
	);
	const recovery = useChatStore(s =>
		activeId ? s.recoveryBySession[activeId] : undefined,
	);
	const continueRecovery = useChatStore(s => s.continueRecovery);
	const abandonRecovery = useChatStore(s => s.abandonRecovery);
	if (!activeId || !recovery || activeSessionArchived) {
		return null;
	}
	const goal = (recovery.goalText || '').trim().slice(0, 120);
	return (
		<div className="mx-3 mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-line/60 bg-paper-deep/40 px-3 py-2 font-sans text-[13px] text-ink">
			<span className="min-w-0 flex-1 text-mute">
				上次任务在重启前未完成
				{goal ? `：${goal}` : ''}
				。要继续吗？
			</span>
			<button
				type="button"
				className="xy-press rounded-md bg-ink px-2.5 py-1 text-[12px] text-paper"
				onClick={() => void continueRecovery(activeId)}
			>
				继续
			</button>
			<button
				type="button"
				className="xy-press rounded-md px-2.5 py-1 text-[12px] text-mute hover:text-ink"
				onClick={() => void abandonRecovery(activeId)}
			>
				放弃
			</button>
		</div>
	);
}

export function ChatPage() {
	const {sessionId} = useParams();
	const navigate = useNavigate();
	const offlineReplay =
		import.meta.env.DEV &&
		typeof window !== 'undefined' &&
		window.location.pathname === '/bench/chat';
	const creatingRef = useRef(false);
	const chatMainRef = useRef<HTMLElement>(null);
	const wasPageViewOpenRef = useRef(false);
	const hydrated = useChatStore(s => s.hydrated);
	const hydrate = useChatStore(s => s.hydrate);
	const hydrateSettings = useSettingsStore(s => s.hydrate);
	// 页面视图（用量/扩展中心/诊断中心）→ 真路由派生（/usage、/plugins、/diagnostics），无独立状态。
	const location = useLocation();
	const pageView = pageViewFromPath(location.pathname);
	const pageViewOpen = pageView !== null;
	const usageActive = pageView === 'usage';
	const pluginsActive = pageView === 'plugins';
	const diagnosticsActive = pageView === 'diagnostics';
	const mainLandmarkLabel =
		pageView === 'usage'
			? '用量'
			: pageView === 'plugins'
				? '扩展'
				: pageView === 'diagnostics'
					? '诊断'
					: '对话';
	useLayoutEffect(() => {
		if (!pageViewOpen && wasPageViewOpenRef.current) {
			chatMainRef.current?.focus({preventScroll: true});
		}
		wasPageViewOpenRef.current = pageViewOpen;
	}, [pageViewOpen]);
	// 页面视图的进入必须等满 rAF 帧（shown）：只订 mounted 会让新页面硬切进来，
	// 盖在还在淡出的上一个页面视图上（两块都是 absolute inset-0），
	// 用户看到两层半透明面板叠在一起 —— 正是聊天列让位淡出想避免的事。
	// 退出时长跟随 smoothness（与 Sidebar/FilePreview 等一致）。
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const {mounted: usageMounted, shown: usageShown} = usePresence(
		usageActive,
		smoothness ? 200 : 0,
		1,
	);
	const {mounted: pluginsMounted, shown: pluginsShown} = usePresence(
		pluginsActive,
		smoothness ? 200 : 0,
		1,
	);
	const {mounted: diagnosticsMounted, shown: diagnosticsShown} = usePresence(
		diagnosticsActive,
		smoothness ? 200 : 0,
		1,
	);
	const recoverStuckStream = useChatStore(s => s.recoverStuckStream);
	const activeId = useChatStore(s => s.activeId);
	const activeSessionIsSide = useChatStore(s =>
		s.sessions.some(
			session => session.id === s.activeId && session.spaceId === SIDE_SPACE_ID,
		),
	);
	const selectSession = useChatStore(s => s.selectSession);
	const createSession = useChatStore(s => s.createSession);

	const immersiveOpen = useChatStore(s => s.immersive);

	// 页面视图(用量/扩展中心)的万能出口:Esc 关闭 —— 统一走 escStack
	// (2026-09-05 复用审计 ④):与命令面板等浮层同一套层级语义,后入栈者先处理。
	useEffect(() => {
		if (!pageViewOpen) {
			return;
		}
		pushEscLayer('page-view', () => closePageView());
		return () => popEscLayer('page-view');
	}, [pageViewOpen]);

	// 页面视图使用全局 URL；恢复当前会话的侧聊上下文供共享 chrome 使用。
	// 大小写判定与侧栏共用 isSideChatPath（React Router 忽略大小写）。
	const isSideChat =
		isSideChatPath(location.pathname) || (pageViewOpen && activeSessionIsSide);
	useEffect(() => {
		if (offlineReplay) {
			return;
		}
		hydrateSettings();
		void useRemoteStore.getState().hydrateRemote();
		void hydrate().then(() => {
			useChatStore.getState().recoverStuckStream();
			void useChatStore.getState().reattachActiveStreams();
		});
	}, [hydrate, hydrateSettings, offlineReplay]);

	// 软刷新 / HMR / 标签页聚焦：只清幽灵 isLoading（abort 已死）。
	// recoverStuckStream 不得动仍在跑或仍在等晚到 tool_result 的行。
	useEffect(() => {
		if (offlineReplay) {
			return;
		}
		recoverStuckStream();
		const onFocus = () => {
			recoverStuckStream();
			void useChatStore.getState().reattachActiveStreams();
		};
		window.addEventListener('focus', onFocus);
		return () => window.removeEventListener('focus', onFocus);
	}, [recoverStuckStream, hydrated, activeId, offlineReplay]);

	// 路由 ↔ store 双向对齐（合并原两个镜像 effect，2026-09-05 复用审计 ⑥）。
	// 页面视图路由（/usage、/plugins）不参与会话对齐。
	useEffect(() => {
		if (offlineReplay || !hydrated || pageViewOpen) {
			return;
		}
		const st = useChatStore.getState();
		const createAndNavigate = () => {
			if (creatingRef.current) return;
			creatingRef.current = true;
			const routeAtStart = window.location.pathname;
			void createSession()
				.then(id => {
					// 用户可能在 IndexedDB / 服务端创建期间切到别处；旧完成回调不能
					// 把路由拉回它启动时的会话。
					if (
						useChatStore.getState().activeId === id &&
						window.location.pathname === routeAtStart
					) {
						navigate(`/c/${id}`, {replace: true});
					}
				})
				.catch(error => {
					toast.error(error instanceof Error ? error.message : '创建会话失败');
				})
				.finally(() => {
					creatingRef.current = false;
				});
		};
		if (sessionId) {
			// URL → store。不要依赖 activeId — 否则 open-folder /
			// createSession 会在 navigate 前更新 activeId，此 effect
			// 会重新选中过期的 URL session（发送看似无反应）。
			// 路由与会话类型必须匹配：/c/ 只接主会话，/side/ 只接侧聊。
			const session = st.sessions.find(s => s.id === sessionId);
			const exists =
				session != null && (session.spaceId === SIDE_SPACE_ID) === isSideChat;
			if (!exists) {
				if (isSideChat) {
					const sideNext = st.sessions.find(
						s => s.spaceId === SIDE_SPACE_ID && !s.archived,
					);
					navigate(sideNext ? `/side/${sideNext.id}` : '/', {replace: true});
					return;
				}
				const active = st.sessions.find(item => item.id === st.activeId);
				if (active?.spaceId === SIDE_SPACE_ID && !active.archived) {
					navigate(`/side/${active.id}`, {replace: true});
					return;
				}
				if (active && active.spaceId !== SIDE_SPACE_ID && !active.archived) {
					navigate(`/c/${active.id}`, {replace: true});
					return;
				}
				const mainNext = st.sessions.find(
					item => item.spaceId !== SIDE_SPACE_ID && !item.archived,
				);
				if (mainNext) {
					navigate(`/c/${mainNext.id}`, {replace: true});
					return;
				}
				navigate('/', {replace: true});
				return;
			}
			void selectSession(sessionId);
			return;
		}
		// 路径无 session id：store → URL。
		if (isSideChat) {
			const sideNext = st.sessions.find(
				s => s.spaceId === SIDE_SPACE_ID && !s.archived,
			);
			navigate(sideNext ? `/side/${sideNext.id}` : '/', {replace: true});
			return;
		}
		// 主路由只回主会话；activeId 停在侧聊时新开一个主会话。
		const activeSession = activeId
			? st.sessions.find(s => s.id === activeId)
			: undefined;
		if (activeSession?.spaceId === SIDE_SPACE_ID && !activeSession.archived) {
			navigate(`/side/${activeSession.id}`, {replace: true});
			return;
		}
		if (
			activeSession &&
			activeSession.spaceId !== SIDE_SPACE_ID &&
			!activeSession.archived
		) {
			navigate(`/c/${activeId}`, {replace: true});
			return;
		}
		// 默认 space（空 IDB 或未开工作区）下自动建 DEFAULT_SPACE_ID 孤儿
		// session 没有意义：streamSendSlice 的工作区守卫会一律拒其发送，
		// 用户看到「请先打开一个项目文件夹」banner,这条 orphan 永远不能
		// 消费、只会在 IDB 残留并污染 rewind/会话选择。引导用户显式开工作
		// 区即可（FileMenu/CommandPalette/Sidebar 的「打开工作区」入口）。
		// 仅当 activeSpaceId 已是真实 space（IDB 恢复 / 已 openFolder）
		// 才允许自动建会话。
		if (!st.activeSpaceId || st.activeSpaceId === DEFAULT_SPACE_ID) {
			return;
		}
		createAndNavigate();
	}, [offlineReplay, hydrated, sessionId, activeId, createSession, navigate, isSideChat, pageViewOpen, selectSession]);

	return (
			<AppShell>
				<RemotePoller />
				<RemoteSseClient />
				<div className="xy-pane-row relative flex min-h-0 min-w-0 flex-1 overflow-hidden">
					<Sidebar />
					{/* 聊天列 + 文件预览/工具面板共用宿主，放大时预览 absolute 盖住聊天。 */}
					<div className="xy-pane-chat-host relative flex min-h-0 min-w-0 flex-1 overflow-hidden">
						<ChatUiStoreProvider store={useChatStore}>
							<main
								ref={chatMainRef}
								aria-label={mainLandmarkLabel}
								tabIndex={-1}
								className="xy-chat-independent-top-mask relative flex min-h-0 min-w-[180px] flex-1 flex-col bg-transparent"
							>
								<ChatHeader mode={isSideChat ? "side" : "main"} />
								<div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
									<div
										className={cn(
											'absolute inset-0 flex min-h-0 min-w-0 flex-col transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none',
											// 页面视图路由（用量/扩展中心）打开时聊天列让位淡出
											// (2026-09-05):否则透明面板与聊天内容互相透字。
											pageViewOpen
												? 'pointer-events-none translate-y-1 opacity-0'
												: 'pointer-events-auto translate-y-0 opacity-100',
										)}
										aria-hidden={pageViewOpen}
										inert={pageViewOpen}
									>
										<div className="xy-chat-col relative flex min-h-0 min-w-0 flex-1 flex-col">
											{!isSideChat ? (
											// 多 Agent 子视图：同一容器内切换聊天记录
											// （头部/输入框/侧栏样式零变化），主子视图互斥渲染。
											<SubAgentView>
												<MessageList />
											</SubAgentView>
										) : (
											<MessageList />
										)}
										</div>
							<RecoveryBanner />
							<Composer showTodoDock={!isSideChat} />
							</div>
						<PageViewPane active={usageActive} mounted={usageMounted} shown={usageShown} label="用量">
							<UsagePanel active={usageActive} />
						</PageViewPane>
						<PageViewPane active={pluginsActive} mounted={pluginsMounted} shown={pluginsShown} label="扩展中心">
							<PluginsPanel active={pluginsActive} />
						</PageViewPane>
						<PageViewPane active={diagnosticsActive} mounted={diagnosticsMounted} shown={diagnosticsShown} label="诊断中心">
							<DiagnosticsPanel active={diagnosticsActive} />
						</PageViewPane>
								</div>
							</main>
						</ChatUiStoreProvider>
						<FilePreview />
						<WorkspaceToolPanel />
					</div>
					<WorkspacePanel />
					<RemoteQrPanel />
				</div>
				{immersiveOpen ? <ImmersiveLayer /> : null}
			</AppShell>
	);
}
