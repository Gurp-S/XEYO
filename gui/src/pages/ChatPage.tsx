import {useEffect, useRef} from 'react';
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
import {useSettingsStore} from '@/stores/settingsStore';
import {useLocation, useNavigate, useParams} from 'react-router-dom';
import {ImmersiveLayer} from '@/components/immersive/ImmersiveLayer';
import {UsagePanel} from '@/components/UsagePanel';
import {PluginsPanel} from '@/components/PluginsPanel';
import {PageViewPane} from '@/components/PageViewPane';
import {usePresence} from '@/hooks/usePresence';
import {closePageView, pageViewFromPath} from '@/lib/appNav';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {cn} from '@/lib/utils';

function RecoveryBanner() {
	const activeId = useChatStore(s => s.activeId);
	const recovery = useChatStore(s =>
		activeId ? s.recoveryBySession[activeId] : undefined,
	);
	const continueRecovery = useChatStore(s => s.continueRecovery);
	const abandonRecovery = useChatStore(s => s.abandonRecovery);
	if (!activeId || !recovery) {
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
	const hydrated = useChatStore(s => s.hydrated);
	const hydrate = useChatStore(s => s.hydrate);
	const hydrateSettings = useSettingsStore(s => s.hydrate);
	// 页面视图（用量/扩展中心）→ 真路由派生（/usage、/plugins），无独立状态。
	const location = useLocation();
	const pageView = pageViewFromPath(location.pathname);
	const pageViewOpen = pageView !== null;
	const usageActive = pageView === 'usage';
	const pluginsActive = pageView === 'plugins';
	const {mounted: usageMounted} = usePresence(usageActive, 200, 1);
	const {mounted: pluginsMounted} = usePresence(pluginsActive, 200, 1);
	const recoverStuckStream = useChatStore(s => s.recoverStuckStream);
	const activeId = useChatStore(s => s.activeId);
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

	const isSideChat = location.pathname.startsWith('/side/');
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
		if (sessionId) {
			// URL → store。不要依赖 activeId — 否则 open-folder /
			// createSession 会在 navigate 前更新 activeId，此 effect
			// 会重新选中过期的 URL session（发送看似无反应）。
			// 路由与会话类型必须匹配：/c/ 只接主会话，/side/ 只接 side- 会话。
			const exists =
				st.sessions.some(s => s.id === sessionId) &&
				sessionId.startsWith('side-') === isSideChat;
			if (!exists) {
				if (isSideChat) {
					const sideNext = st.sessions.find(s => s.id.startsWith('side-'));
					navigate(sideNext ? `/side/${sideNext.id}` : '/', {replace: true});
					return;
				}
				if (st.activeId) {
					navigate(`/c/${st.activeId}`, {replace: true});
					return;
				}
				if (creatingRef.current) {
					return;
				}
				creatingRef.current = true;
				void createSession().then(id => {
					navigate(`/c/${id}`, {replace: true});
					creatingRef.current = false;
				});
				return;
			}
			void selectSession(sessionId);
			return;
		}
		// 路径无 session id：store → URL。
		if (isSideChat) {
			const sideNext = st.sessions.find(s => s.id.startsWith('side-'));
			navigate(sideNext ? `/side/${sideNext.id}` : '/', {replace: true});
			return;
		}
		// 主路由只回主会话；activeId 停在侧聊时新开一个主会话。
		if (activeId && !activeId.startsWith('side-')) {
			navigate(`/c/${activeId}`, {replace: true});
			return;
		}
		if (creatingRef.current) {
			return;
		}
		creatingRef.current = true;
		void createSession().then(id => {
			navigate(`/c/${id}`, {replace: true});
			creatingRef.current = false;
		});
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
							<main className="xy-chat-independent-top-mask relative flex min-h-0 min-w-[180px] flex-1 flex-col bg-transparent">
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
						<PageViewPane active={usageActive} mounted={usageMounted}>
							<UsagePanel active={usageActive} />
						</PageViewPane>
						<PageViewPane active={pluginsActive} mounted={pluginsMounted}>
							<PluginsPanel active={pluginsActive} />
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
